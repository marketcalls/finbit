/**
 * The feed: one story per screen, swiped vertically.
 *
 * This is the shape of the product (CONTRACT_MOBILE_ADMIN.md section 8.1). A
 * full-screen pager is built here out of a plain FlatList rather than a pager
 * package, because a FlatList already virtualises, already recycles rows and
 * already knows how to page: pagingEnabled plus snapToInterval plus a
 * getItemLayout that agrees with the measured card height gives exactly one card
 * per viewport with none of the recycling bugs a third-party pager brings.
 *
 * Three details make or break the feel:
 *
 *   - The card height is measured, never assumed. The chrome above the list
 *     changes height when the market filters expand, and a hardcoded height
 *     would slowly drift out of step with the snap points. The list is not
 *     rendered at all until the container has reported a height, which also
 *     means getItemLayout is never wrong.
 *   - The haptic fires from onViewableItemsChanged, not from onScroll. onScroll
 *     runs on every frame of a swipe and would buzz continuously; viewability
 *     changes once per card. The callback and its config are held in refs
 *     because React Native refuses to accept a new onViewableItemsChanged after
 *     mount and throws if one arrives.
 *   - The next page is requested a full screen before the user reaches the end,
 *     so a swipe never lands on a spinner.
 *
 * Maintenance mode is not handled here. app/_layout.tsx gates every tab behind
 * one maintenance screen, so a second check in this file would be dead code that
 * looks load bearing.
 */

import * as Haptics from 'expo-haptics';
import { router } from 'expo-router';
import { useCallback, useEffect, useRef, useState, type ReactElement } from 'react';
import {
  FlatList,
  Platform,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
  type ViewToken,
} from 'react-native';

import { api, describeError, isAbortError } from '@/src/api/client';
import { CategoryTabs } from '@/src/components/CategoryTabs';
import { FeedSkeleton } from '@/src/components/FeedSkeleton';
import { MarketFilters } from '@/src/components/MarketFilters';
import { NewsCard } from '@/src/components/NewsCard';
import { Screen } from '@/src/components/Screen';
import { EmptyState, ErrorState } from '@/src/components/StateViews';
import { type ArticleCard, type FeedCategory, type SortMode } from '@/src/lib/types';
import { useConfig } from '@/src/store/ConfigProvider';
import { MIN_TOUCH_TARGET, useTheme } from '@/src/theme';

/** One full page short of the end, so the next batch is already in flight. */
const END_REACHED_THRESHOLD = 1;

/** A card counts as the current one once most of it is on screen. */
const VIEWABILITY = { itemVisiblePercentThreshold: 60 } as const;

const PAGE_SIZE = 20;

type Phase = 'loading' | 'ready' | 'error';

/** The compact Top and Latest switch that sits beside the category strip. */
function SortToggle({
  value,
  onChange,
}: {
  value: SortMode;
  onChange: (next: SortMode) => void;
}): ReactElement {
  const { colors, radii, space, fonts, fontSizes } = useTheme();
  const next: SortMode = value === 'top' ? 'latest' : 'top';

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={
        value === 'top'
          ? 'Sorted by importance. Switch to newest first.'
          : 'Sorted by newest. Switch to most important first.'
      }
      onPress={() => onChange(next)}
      style={({ pressed }) => [
        styles.sort,
        {
          borderRadius: radii.pill,
          borderColor: colors.border,
          backgroundColor: colors.muted,
          paddingHorizontal: space.md,
          marginRight: space.lg,
          opacity: pressed ? 0.7 : 1,
        },
      ]}
    >
      <Text
        style={{
          color: colors.fg,
          fontFamily: fonts.body,
          fontSize: fontSizes.xs,
          fontWeight: '700',
          letterSpacing: 0.5,
        }}
      >
        {value === 'top' ? 'TOP' : 'LATEST'}
      </Text>
    </Pressable>
  );
}

/**
 * The page after the last story. It is a whole viewport tall on purpose: a short
 * footer under a paging list leaves the final card snapped half off screen.
 */
function EndPage({
  height,
  loading,
  title,
  message,
}: {
  height: number;
  loading: boolean;
  title: string;
  message: string;
}): ReactElement {
  const { colors, fonts, fontSizes, lineHeights, space } = useTheme();

  if (loading) {
    return <FeedSkeleton height={height} />;
  }

  return (
    <View style={[styles.endPage, { height, paddingHorizontal: space.xl }]}>
      <Text
        accessibilityRole="header"
        style={{
          color: colors.fg,
          fontFamily: fonts.headline,
          fontSize: fontSizes.xl,
          lineHeight: lineHeights.xl,
          textAlign: 'center',
        }}
      >
        {title}
      </Text>
      <Text
        style={{
          color: colors.mutedFg,
          fontFamily: fonts.body,
          fontSize: fontSizes.md,
          lineHeight: lineHeights.md,
          marginTop: space.sm,
          textAlign: 'center',
        }}
      >
        {message}
      </Text>
    </View>
  );
}

export default function FeedScreen(): ReactElement {
  const { colors, space } = useTheme();
  const { categories, marketFilters, defaultSort } = useConfig();

  const [category, setCategory] = useState<FeedCategory>('all');
  const [symbol, setSymbol] = useState<string | null>(null);
  const [sort, setSort] = useState<SortMode>(defaultSort);

  const [items, setItems] = useState<ArticleCard[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [phase, setPhase] = useState<Phase>('loading');
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);

  const [cardHeight, setCardHeight] = useState(0);

  const list = useRef<FlatList<ArticleCard> | null>(null);
  const mounted = useRef(true);
  /*
    Every fetch carries the generation it was started in. A response from a
    filter the user has already moved on from is dropped rather than merged,
    which is what stops a slow request for "RBI" from repopulating a feed the
    user has since switched to "Crypto".
  */
  const generation = useRef(0);
  const inFlight = useRef(false);
  // The cursor as of this instant, so onEndReached does not page from whatever
  // value the last render closed over.
  const cursorRef = useRef<string | null>(null);
  // Whether the user has chosen a sort, which freezes the config default.
  const sortChosen = useRef(false);
  // The card the user is on, so the haptic fires once per change rather than
  // once per frame.
  const activeIndex = useRef(0);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  // The config arrives after the first paint, so the server's default sort is
  // adopted once, and only while the user has not picked one.
  useEffect(() => {
    if (!sortChosen.current) {
      setSort(defaultSort);
    }
  }, [defaultSort]);

  const load = useCallback(
    async (mode: 'initial' | 'refresh' | 'more') => {
      if (mode === 'more' && (inFlight.current || cursorRef.current === null)) {
        return;
      }
      inFlight.current = true;
      const era = generation.current;

      if (mode === 'refresh') {
        setRefreshing(true);
      } else if (mode === 'more') {
        setLoadingMore(true);
      } else {
        setPhase('loading');
      }

      try {
        const response = await api.getFeed({
          category,
          symbol: symbol ?? undefined,
          sort,
          cursor: mode === 'more' ? (cursorRef.current ?? undefined) : undefined,
          limit: PAGE_SIZE,
        });

        if (!mounted.current || era !== generation.current) {
          return;
        }

        cursorRef.current = response.next_cursor;
        setHasMore(response.has_more);
        setItems((current) => (mode === 'more' ? [...current, ...response.items] : response.items));
        setError(null);
        setPhase('ready');
      } catch (caught) {
        if (!mounted.current || era !== generation.current || isAbortError(caught)) {
          return;
        }
        const message = describeError(caught);
        setError(message);
        // A failed page load keeps the stories already on screen and reports the
        // failure on the end page. Only a failed first load takes over the tab.
        if (mode !== 'more') {
          setPhase('error');
        }
      } finally {
        inFlight.current = false;
        if (mounted.current) {
          setRefreshing(false);
          setLoadingMore(false);
        }
      }
    },
    [category, sort, symbol],
  );

  // A filter change is a new feed, not an update to this one: the list is
  // emptied, scrolled back to the top and reloaded from the first page.
  useEffect(() => {
    generation.current += 1;
    inFlight.current = false;
    cursorRef.current = null;
    activeIndex.current = 0;
    setItems([]);
    setHasMore(false);
    setError(null);
    list.current?.scrollToOffset({ offset: 0, animated: false });
    void load('initial');
  }, [load]);

  /*
    Haptics. The callback is held in a ref so it stays referentially stable for
    the lifetime of the screen: React Native throws when onViewableItemsChanged
    changes after mount.
  */
  const onViewableItemsChanged = useRef(
    (info: { viewableItems: Array<ViewToken<ArticleCard>> }) => {
      const first = info.viewableItems[0];
      if (first === undefined || first.index === null || first.index === undefined) {
        return;
      }
      if (first.index === activeIndex.current) {
        return;
      }
      activeIndex.current = first.index;
      void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {
        // No haptic engine on a simulator or on web. Never worth surfacing.
      });
    },
  ).current;
  const viewabilityConfig = useRef(VIEWABILITY).current;

  const getItemLayout = useCallback(
    (_data: ArrayLike<ArticleCard> | null | undefined, index: number) => ({
      length: cardHeight,
      offset: cardHeight * index,
      index,
    }),
    [cardHeight],
  );

  const openArticle = useCallback((articleId: number) => {
    router.push(`/article/${articleId}`);
  }, []);

  const clearFilters = useCallback(() => {
    setCategory('all');
    setSymbol(null);
  }, []);

  const filtered = category !== 'all' || symbol !== null;
  const activeLabel =
    symbol ??
    categories.find((entry) => entry.key === category)?.label ??
    category;

  let body: ReactElement;

  if (cardHeight === 0) {
    // Nothing can be drawn correctly before the pager knows its own height, and
    // a placeholder is what would be drawn anyway on the first frame.
    body = <FeedSkeleton />;
  } else if (phase === 'loading' && items.length === 0) {
    body = <FeedSkeleton height={cardHeight} />;
  } else if (phase === 'error' && items.length === 0) {
    body = (
      <View style={styles.centre}>
        <ErrorState
          title="The feed did not load"
          message={error ?? 'Something went wrong. Please try again.'}
          onRetry={() => void load('initial')}
        />
      </View>
    );
  } else if (items.length === 0) {
    body = (
      <View style={styles.centre}>
        {filtered ? (
          <EmptyState
            title={`Nothing in ${activeLabel}`}
            body="There is news in FinBit, just none matching this filter right now."
            action={{ label: 'Show all stories', onPress: clearFilters }}
          />
        ) : (
          <EmptyState
            title="No stories yet"
            body="FinBit has not pulled any news into this feed. Try again in a moment."
            action={{ label: 'Check again', onPress: () => void load('initial') }}
          />
        )}
      </View>
    );
  } else {
    body = (
      <FlatList
        ref={list}
        data={items}
        keyExtractor={(item) => String(item.id)}
        renderItem={({ item }) => (
          <NewsCard
            article={item}
            height={cardHeight}
            onPress={() => openArticle(item.id)}
            onSelectSymbol={setSymbol}
          />
        )}
        pagingEnabled
        snapToInterval={cardHeight}
        snapToAlignment="start"
        decelerationRate="fast"
        getItemLayout={getItemLayout}
        showsVerticalScrollIndicator={false}
        // Detaching off-screen rows is a real win on Android, where each card
        // holds a decoded bitmap, and a known source of blank rows on iOS.
        removeClippedSubviews={Platform.OS === 'android'}
        initialNumToRender={2}
        maxToRenderPerBatch={3}
        windowSize={5}
        onViewableItemsChanged={onViewableItemsChanged}
        viewabilityConfig={viewabilityConfig}
        onEndReached={() => void load('more')}
        onEndReachedThreshold={END_REACHED_THRESHOLD}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => void load('refresh')}
            tintColor={colors.mutedFg}
            colors={[colors.accent]}
            progressBackgroundColor={colors.card}
          />
        }
        ListFooterComponent={
          <EndPage
            height={cardHeight}
            loading={loadingMore}
            title={error === null ? 'You are all caught up' : 'More stories did not load'}
            message={
              error ??
              (hasMore
                ? 'Swipe back up, then pull down to try the next stories again.'
                : 'That is every story FinBit has for this filter. Pull down to refresh.')
            }
          />
        }
      />
    );
  }

  return (
    <Screen edges={['top']}>
      <View style={[styles.header, { paddingVertical: space.sm }]}>
        <CategoryTabs
          categories={categories}
          value={category}
          onChange={setCategory}
          style={styles.grow}
        />
        <SortToggle
          value={sort}
          onChange={(next) => {
            sortChosen.current = true;
            setSort(next);
          }}
        />
      </View>

      <MarketFilters
        filters={marketFilters}
        value={symbol}
        onChange={setSymbol}
        style={{ paddingBottom: space.sm }}
      />

      <View
        style={styles.grow}
        onLayout={(event) => {
          // Rounded, because a fractional height would differ by a hair from the
          // one getItemLayout hands the list and the snap points would creep.
          const measured = Math.round(event.nativeEvent.layout.height);
          if (measured > 0 && measured !== cardHeight) {
            setCardHeight(measured);
          }
        }}
      >
        {body}
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  grow: {
    flex: 1,
  },
  centre: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  sort: {
    height: MIN_TOUCH_TARGET - 8,
    minWidth: MIN_TOUCH_TARGET,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: StyleSheet.hairlineWidth,
  },
  endPage: {
    alignItems: 'center',
    justifyContent: 'center',
  },
});
