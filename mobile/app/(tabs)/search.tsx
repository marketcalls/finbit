/**
 * Search.
 *
 * The screen has one job that is easy to state and easy to get wrong: turn
 * keystrokes into as few requests as possible while never feeling slow. Three
 * things do that here.
 *
 * The field is never debounced, only the request is (300 ms, the same figure the
 * web app uses in CONTRACT.md section 11), so the text always keeps up with the
 * typing. A query shorter than two characters is not sent at all, because the
 * API answers those with a 422 and an error state for "r" would be a lie about
 * what went wrong. And every request carries an AbortSignal that the effect
 * cleanup fires, so a fast typist's earlier searches cannot land after a later
 * one and overwrite the results with stale rows.
 *
 * Before anything is typed the screen shows what the last 48 hours were about
 * rather than an empty box, because a search screen with no starting point is a
 * dead end for anyone who does not already know the ticker they want.
 */

import { useRouter } from 'expo-router';
import { useCallback, useEffect, useState, type ReactElement } from 'react';
import { FlatList, Keyboard, ScrollView, StyleSheet, Text, View } from 'react-native';

import { api, describeError, isAbortError } from '@/src/api/client';
import { CompactArticleRow } from '@/src/components/CompactArticleRow';
import { Screen } from '@/src/components/Screen';
import { SearchInput } from '@/src/components/SearchInput';
import { EmptyState, ErrorState, Skeleton } from '@/src/components/StateViews';
import { TrendingChips } from '@/src/components/TrendingChips';
import type { ArticleCard, TrendingResponse } from '@/src/lib/types';
import { useTheme } from '@/src/theme';

/** Long enough to skip the letters of a word, short enough to feel immediate. */
const DEBOUNCE_MS = 300;

/** CONTRACT.md section 5: the API returns 422 for a shorter query. */
const MIN_QUERY_LENGTH = 2;

/** The API default. Stated here so the number on screen is not a mystery. */
const SEARCH_LIMIT = 30;

/** Placeholder rows while the first results for a query are on the way. */
const SKELETON_ROWS = 6;

/** Matches the thumbnail in CompactArticleRow so the shape does not jump. */
const SKELETON_THUMB = 72;

export default function SearchScreen(): ReactElement {
  const router = useRouter();
  const { colors, space, fonts, fontSizes } = useTheme();

  // The live field value, and the debounced query actually sent to the API.
  const [text, setText] = useState('');
  const [term, setTerm] = useState('');

  const [results, setResults] = useState<ArticleCard[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  const [trending, setTrending] = useState<TrendingResponse | null>(null);
  const [trendingLoading, setTrendingLoading] = useState(true);
  const [trendingError, setTrendingError] = useState<string | null>(null);
  const [trendingAttempt, setTrendingAttempt] = useState(0);

  // Debounce: the timer restarts on every keystroke, so the query settles only
  // once the typing pauses.
  useEffect(() => {
    const handle = setTimeout(() => {
      setTerm(text.trim());
    }, DEBOUNCE_MS);

    return () => {
      clearTimeout(handle);
    };
  }, [text]);

  useEffect(() => {
    if (term.length < MIN_QUERY_LENGTH) {
      setResults(null);
      setError(null);
      setLoading(false);
      return;
    }

    const controller = new AbortController();
    let cancelled = false;

    setLoading(true);
    setError(null);

    void (async () => {
      try {
        const response = await api.search(term, {
          limit: SEARCH_LIMIT,
          signal: controller.signal,
        });
        if (!cancelled) {
          setResults(response.items);
          setLoading(false);
        }
      } catch (caught) {
        // A cancelled request is the normal outcome of typing another letter.
        if (cancelled || isAbortError(caught)) {
          return;
        }
        setError(describeError(caught));
        setResults(null);
        setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [term, attempt]);

  useEffect(() => {
    let cancelled = false;

    setTrendingLoading(true);
    setTrendingError(null);

    void (async () => {
      try {
        const response = await api.trending();
        if (!cancelled) {
          setTrending(response);
        }
      } catch (caught) {
        if (!cancelled) {
          setTrendingError(describeError(caught));
        }
      } finally {
        if (!cancelled) {
          setTrendingLoading(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [trendingAttempt]);

  const openArticle = useCallback(
    (article: ArticleCard) => {
      Keyboard.dismiss();
      router.push({ pathname: '/article/[id]', params: { id: String(article.id) } });
    },
    [router],
  );

  const live = text.trim();
  const searching = live.length >= MIN_QUERY_LENGTH;

  let body: ReactElement;

  if (!searching) {
    body = (
      <ScrollView
        // The keyboard is up while the chips are visible, so a drag has to put
        // it away or half the trending list is unreachable.
        keyboardDismissMode="on-drag"
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={[
          styles.idle,
          { paddingHorizontal: space.lg, paddingBottom: space.xxl },
        ]}
      >
        {live.length > 0 ? (
          <View style={styles.centred}>
            <EmptyState
              title="Keep typing"
              body={`Enter at least ${MIN_QUERY_LENGTH} characters to search.`}
            />
          </View>
        ) : trendingError !== null && trending === null ? (
          <View style={styles.centred}>
            <ErrorState
              title="Trending is unavailable"
              message={trendingError}
              onRetry={() => setTrendingAttempt((current) => current + 1)}
            />
          </View>
        ) : (
          <>
            <TrendingChips
              symbols={trending?.symbols ?? []}
              topics={trending?.topics ?? []}
              loading={trendingLoading}
              onSelect={setText}
            />
            {!trendingLoading &&
            (trending?.symbols.length ?? 0) === 0 &&
            (trending?.topics.length ?? 0) === 0 ? (
              <View style={styles.centred}>
                <EmptyState
                  title="Search FinBit"
                  body="Find a story by company, symbol or topic."
                />
              </View>
            ) : null}
          </>
        )}
      </ScrollView>
    );
  } else if (error !== null) {
    body = (
      <View style={styles.centred}>
        <ErrorState message={error} onRetry={() => setAttempt((current) => current + 1)} />
      </View>
    );
  } else if (results === null) {
    body = <ResultSkeletons />;
  } else if (results.length === 0) {
    body = (
      <View style={styles.centred}>
        <EmptyState
          title="No stories match"
          body={`Nothing published recently mentions "${term}". Try a company name, a ticker such as RELIANCE, or a topic such as RBI.`}
          action={{ label: 'Clear search', onPress: () => setText('') }}
        />
      </View>
    );
  } else {
    body = (
      <FlatList
        data={results}
        keyExtractor={(item) => String(item.id)}
        renderItem={({ item }) => <CompactArticleRow article={item} onPress={openArticle} />}
        ItemSeparatorComponent={Separator}
        keyboardDismissMode="on-drag"
        keyboardShouldPersistTaps="handled"
        contentContainerStyle={{ paddingBottom: space.xxl }}
        ListHeaderComponent={
          <Text
            // Announced so a screen reader hears how many stories arrived
            // without having to walk the list. It also says when a new query is
            // in flight, because the rows underneath are still the old ones
            // until it lands.
            accessibilityLiveRegion="polite"
            style={{
              color: colors.mutedFg,
              fontFamily: fonts.body,
              fontSize: fontSizes.xs,
              paddingHorizontal: space.lg,
              paddingBottom: space.sm,
            }}
          >
            {loading ? 'Searching…' : countLabel(results.length)}
          </Text>
        }
      />
    );
  }

  return (
    <Screen edges={['top']}>
      <View style={{ paddingHorizontal: space.lg, paddingVertical: space.md }}>
        <SearchInput value={text} onChangeText={setText} onSubmit={Keyboard.dismiss} />
      </View>
      <View style={styles.fill}>{body}</View>
    </Screen>
  );
}

/** "1 story" or "12 stories", so the header never prints "1 stories". */
function countLabel(count: number): string {
  return count === 1 ? '1 story' : `${count} stories`;
}

function Separator(): ReactElement {
  const { colors, space } = useTheme();

  return (
    <View
      style={[styles.separator, { backgroundColor: colors.border, marginLeft: space.lg }]}
    />
  );
}

/** The shape of a result row, so the list does not reflow when data lands. */
function ResultSkeletons(): ReactElement {
  const { space, radii } = useTheme();

  return (
    <View accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
      {Array.from({ length: SKELETON_ROWS }, (_unused, index) => (
        <View
          key={index}
          style={[
            styles.skeletonRow,
            {
              paddingHorizontal: space.lg,
              paddingVertical: space.md,
              columnGap: space.md,
            },
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
  idle: {
    flexGrow: 1,
  },
  centred: {
    flex: 1,
    justifyContent: 'center',
  },
  separator: {
    height: StyleSheet.hairlineWidth,
  },
  skeletonRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
  },
});
