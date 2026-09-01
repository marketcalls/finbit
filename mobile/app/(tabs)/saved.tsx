/**
 * Saved.
 *
 * Everything on this screen comes from BookmarksProvider, which is also what the
 * feed and search read, so unsaving here flips the bookmark on the card behind
 * it without a refetch. Bookmarks are per device with no account behind them,
 * which the empty state says out loud: a user who cannot find their saved
 * stories on a second phone should learn why from the app, not from support.
 *
 * Swiping a row removes it, and every removal offers an undo for a few seconds.
 * A swipe is easy to fire by accident while scrolling, and the alternative
 * safeguard, a confirmation dialog on every unsave, would make the common case
 * cost two taps to protect against the rare one. The undo also covers the
 * screen reader path, because the action panel is a real labelled button rather
 * than a decorative panel that only a gesture can reach.
 *
 * The provider's toggle and remove never throw and roll themselves back, so the
 * handlers here read their returned boolean rather than wrapping calls in
 * try/catch: a removal that did not happen must not offer to undo itself.
 */

import * as Haptics from 'expo-haptics';
import { useRouter } from 'expo-router';
import { useCallback, useEffect, useRef, useState, type ReactElement } from 'react';
import { FlatList, Pressable, RefreshControl, StyleSheet, Text, View } from 'react-native';
import Swipeable, {
  SwipeDirection,
  type SwipeableMethods,
} from 'react-native-gesture-handler/ReanimatedSwipeable';

import { CompactArticleRow } from '@/src/components/CompactArticleRow';
import { Screen } from '@/src/components/Screen';
import { EmptyState, ErrorState, Skeleton } from '@/src/components/StateViews';
import type { ArticleCard } from '@/src/lib/types';
import { useBookmarks } from '@/src/store/BookmarksProvider';
import { MIN_TOUCH_TARGET, useTheme } from '@/src/theme';

/** How long the undo stays offered. Long enough to notice, short enough to pass. */
const UNDO_MS = 6000;

/** Width of the revealed action panel. */
const ACTION_WIDTH = 104;

/** How far the row must travel before the panel counts as open. */
const RIGHT_THRESHOLD = ACTION_WIDTH * 0.6;

const SKELETON_ROWS = 5;
const SKELETON_THUMB = 72;

export default function SavedScreen(): ReactElement {
  const router = useRouter();
  const { colors, space, fonts, fontSizes } = useTheme();
  const { items, loading, error, refresh, remove, toggle } = useBookmarks();

  const [refreshing, setRefreshing] = useState(false);
  const [undoFor, setUndoFor] = useState<ArticleCard | null>(null);
  const undoTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearUndoTimer = useCallback(() => {
    if (undoTimer.current !== null) {
      clearTimeout(undoTimer.current);
      undoTimer.current = null;
    }
  }, []);

  useEffect(() => clearUndoTimer, [clearUndoTimer]);

  const openArticle = useCallback(
    (article: ArticleCard) => {
      router.push({ pathname: '/article/[id]', params: { id: String(article.id) } });
    },
    [router],
  );

  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await refresh();
    setRefreshing(false);
  }, [refresh]);

  const onRemove = useCallback(
    async (article: ArticleCard) => {
      // Haptics are the screen's job, not the provider's, and are best effort:
      // the web preview has no motor to buzz.
      void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => undefined);

      const stillSaved = await remove(article.id);
      if (stillSaved) {
        // The request failed and the provider put the story back. Its error is
        // already on screen; offering to undo something that did not happen
        // would be worse than saying nothing.
        return;
      }

      clearUndoTimer();
      setUndoFor(article);
      undoTimer.current = setTimeout(() => {
        setUndoFor(null);
        undoTimer.current = null;
      }, UNDO_MS);
    },
    [clearUndoTimer, remove],
  );

  const onUndo = useCallback(async () => {
    const article = undoFor;
    if (article === null) {
      return;
    }
    clearUndoTimer();
    setUndoFor(null);
    void Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => undefined);
    await toggle(article);
  }, [clearUndoTimer, toggle, undoFor]);

  let empty: ReactElement;
  if (loading) {
    empty = <SavedSkeletons />;
  } else if (error !== null && items.length === 0) {
    empty = (
      <View style={styles.centred}>
        <ErrorState message={error} onRetry={() => void refresh()} />
      </View>
    );
  } else {
    empty = (
      <View style={styles.centred}>
        <EmptyState
          title="Nothing saved yet"
          body="Tap the bookmark on a story to keep it here. Saved stories belong to this device, so there is no account to create and nothing to sign in to."
        />
      </View>
    );
  }

  return (
    <Screen edges={['top']}>
      <FlatList
        data={items}
        keyExtractor={(item) => String(item.id)}
        renderItem={({ item }) => (
          <SavedRow article={item} onOpen={openArticle} onRemove={onRemove} />
        )}
        ItemSeparatorComponent={Separator}
        ListEmptyComponent={empty}
        ListHeaderComponent={
          items.length === 0 ? null : (
            <Text
              accessibilityLiveRegion="polite"
              style={{
                color: colors.mutedFg,
                fontFamily: fonts.body,
                fontSize: fontSizes.xs,
                paddingHorizontal: space.lg,
                paddingTop: space.md,
                paddingBottom: space.sm,
              }}
            >
              {savedLabel(items.length)}
            </Text>
          )
        }
        contentContainerStyle={[
          styles.content,
          { paddingBottom: undoFor === null ? space.xxl : space.xxl * 2 },
        ]}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => void onRefresh()}
            tintColor={colors.accent}
            colors={[colors.accent]}
            progressBackgroundColor={colors.card}
          />
        }
      />

      {undoFor === null ? null : (
        <UndoBar headline={undoFor.headline} onUndo={() => void onUndo()} />
      )}
    </Screen>
  );
}

/** "1 story saved" or "7 stories saved". */
function savedLabel(count: number): string {
  return count === 1 ? '1 story saved' : `${count} stories saved`;
}

/**
 * One saved story, wrapped in the swipe container.
 *
 * The removal is guarded against firing twice, because settling the panel open
 * and tapping the button inside it can both arrive for the same row. The guard
 * is released once the request resolves, so a failed removal can be retried.
 */
function SavedRow({
  article,
  onOpen,
  onRemove,
}: {
  article: ArticleCard;
  onOpen: (article: ArticleCard) => void;
  onRemove: (article: ArticleCard) => Promise<void>;
}): ReactElement {
  const { colors, space, fonts, fontSizes } = useTheme();
  const swipeable = useRef<SwipeableMethods | null>(null);
  const firing = useRef(false);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const trigger = useCallback(() => {
    if (firing.current) {
      return;
    }
    firing.current = true;

    void onRemove(article).finally(() => {
      firing.current = false;
      // Only touch the panel while this row still exists. A successful removal
      // unmounts it, and closing an unmounted swipeable animates nothing.
      if (mounted.current) {
        swipeable.current?.close();
      }
    });
  }, [article, onRemove]);

  return (
    <Swipeable
      ref={swipeable}
      friction={2}
      rightThreshold={RIGHT_THRESHOLD}
      overshootRight={false}
      onSwipeableOpen={(direction) => {
        if (direction === SwipeDirection.RIGHT) {
          trigger();
        }
      }}
      renderRightActions={() => (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`Remove ${article.headline} from saved`}
          onPress={trigger}
          style={({ pressed }) => [
            styles.action,
            {
              backgroundColor: pressed ? colors.border : colors.muted,
              paddingHorizontal: space.md,
            },
          ]}
        >
          <Text
            style={{
              color: colors.bear,
              fontFamily: fonts.body,
              fontSize: fontSizes.sm,
              fontWeight: '700',
            }}
          >
            Remove
          </Text>
        </Pressable>
      )}
    >
      <CompactArticleRow article={article} onPress={onOpen} />
    </Swipeable>
  );
}

/** The undo affordance, pinned over the list for a few seconds after a removal. */
function UndoBar({ headline, onUndo }: { headline: string; onUndo: () => void }): ReactElement {
  const { colors, radii, space, fonts, fontSizes } = useTheme();

  return (
    <View
      accessibilityLiveRegion="polite"
      style={[
        styles.undo,
        {
          backgroundColor: colors.card,
          borderColor: colors.border,
          borderRadius: radii.md,
          bottom: space.lg,
          left: space.lg,
          right: space.lg,
          paddingLeft: space.lg,
          paddingRight: space.sm,
          columnGap: space.md,
        },
      ]}
    >
      <Text
        numberOfLines={1}
        style={{
          color: colors.fg,
          flex: 1,
          fontFamily: fonts.body,
          fontSize: fontSizes.sm,
        }}
      >
        Removed {headline}
      </Text>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Undo remove"
        onPress={onUndo}
        style={({ pressed }) => [
          styles.undoButton,
          { paddingHorizontal: space.md, opacity: pressed ? 0.7 : 1 },
        ]}
      >
        <Text
          style={{
            color: colors.accent,
            fontFamily: fonts.body,
            fontSize: fontSizes.md,
            fontWeight: '700',
          }}
        >
          Undo
        </Text>
      </Pressable>
    </View>
  );
}

function Separator(): ReactElement {
  const { colors, space } = useTheme();

  return <View style={[styles.separator, { backgroundColor: colors.border, marginLeft: space.lg }]} />;
}

/** The shape of a saved row, so the list does not reflow when data lands. */
function SavedSkeletons(): ReactElement {
  const { space, radii } = useTheme();

  return (
    <View accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
      {Array.from({ length: SKELETON_ROWS }, (_unused, index) => (
        <View
          key={index}
          style={[
            styles.skeletonRow,
            { paddingHorizontal: space.lg, paddingVertical: space.md, columnGap: space.md },
          ]}
        >
          <Skeleton width={SKELETON_THUMB} height={SKELETON_THUMB} radius={radii.sm} />
          <View style={[styles.fill, { rowGap: space.sm }]}>
            <Skeleton height={14} />
            <Skeleton width="80%" height={14} />
            <Skeleton width="45%" height={10} />
          </View>
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  fill: {
    flex: 1,
  },
  content: {
    flexGrow: 1,
  },
  centred: {
    flex: 1,
    justifyContent: 'center',
  },
  separator: {
    height: StyleSheet.hairlineWidth,
  },
  action: {
    width: ACTION_WIDTH,
    alignItems: 'center',
    justifyContent: 'center',
  },
  undo: {
    position: 'absolute',
    flexDirection: 'row',
    alignItems: 'center',
    minHeight: MIN_TOUCH_TARGET + 8,
    borderWidth: StyleSheet.hairlineWidth,
  },
  undoButton: {
    minHeight: MIN_TOUCH_TARGET,
    minWidth: MIN_TOUCH_TARGET,
    alignItems: 'center',
    justifyContent: 'center',
  },
  skeletonRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
  },
});
