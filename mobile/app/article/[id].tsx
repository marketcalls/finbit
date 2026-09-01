/**
 * The full story, opened from a feed card or a search result.
 *
 * The feed card is deliberately clamped: it is one page of a pager and it shows
 * the 50 to 80 word summary and nothing more. This screen is where everything
 * the pipeline resolved actually fits, in the order a reader wants it: the
 * story, then why it matters to an Indian market reader, then the machine's
 * impact call, then the tickers and the topics, then the reporting it came from.
 *
 * The article is refetched by id rather than handed over through navigation
 * params. A deep link into this route from a notification or a pasted URL has no
 * params to hand over, and one fetch path is easier to reason about than two
 * that can disagree about how stale the payload is.
 *
 * The screen draws its own header because the root Stack runs with headerShown
 * false. The back control falls back to the feed when there is no history, which
 * is exactly the deep link case.
 */

import { router, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useRef, useState, type ReactElement } from 'react';
import { Pressable, StyleSheet, Text, View, type TextStyle } from 'react-native';
import Svg, { Path } from 'react-native-svg';

import { api, describeError, isAbortError } from '@/src/api/client';
import { CardImage, categoryLabel } from '@/src/components/CardImage';
import { ImpactBadge } from '@/src/components/ImpactBadge';
import { Screen } from '@/src/components/Screen';
import { SourcesSheet } from '@/src/components/SourcesSheet';
import { SymbolChips } from '@/src/components/SymbolChips';
import { EmptyState, ErrorState, Skeleton } from '@/src/components/StateViews';
import { absoluteTime, readingMinutes, sourceCountLabel } from '@/src/lib/format';
import {
  type ArticleCard,
  type ImpactEntryDirection,
  type Sentiment,
} from '@/src/lib/types';
import { useBookmarks } from '@/src/store/BookmarksProvider';
import { MIN_TOUCH_TARGET, useTheme, type ColorTokens } from '@/src/theme';

/** CONTRACT.md section 10: the impact block is never presented as a signal. */
const DISCLAIMER = 'AI assessment, not investment advice.';

const SENTIMENT_LABELS: Record<Sentiment, string> = {
  positive: 'Positive',
  negative: 'Negative',
  neutral: 'Neutral',
  mixed: 'Mixed',
};

const IMPACT_ENTRY_LABELS: Record<ImpactEntryDirection, string> = {
  positive: 'Positive',
  negative: 'Negative',
  neutral: 'Neutral',
  mixed: 'Mixed',
};

function entryColor(colors: ColorTokens, direction: ImpactEntryDirection): string {
  if (direction === 'positive') {
    return colors.bull;
  }
  if (direction === 'negative') {
    return colors.bear;
  }
  return direction === 'mixed' ? colors.fg : colors.flat;
}

function sentimentColor(colors: ColorTokens, sentiment: Sentiment): string {
  if (sentiment === 'positive') {
    return colors.bull;
  }
  if (sentiment === 'negative') {
    return colors.bear;
  }
  return sentiment === 'mixed' ? colors.fg : colors.flat;
}

function BackGlyph({ color }: { color: string }): ReactElement {
  return (
    <Svg width={22} height={22} viewBox="0 0 24 24" fill="none">
      <Path
        d="M15 5L8 12L15 19"
        stroke={color}
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </Svg>
  );
}

function BookmarkGlyph({ color, filled }: { color: string; filled: boolean }): ReactElement {
  return (
    <Svg width={21} height={21} viewBox="0 0 24 24" fill="none">
      <Path
        d="M6 4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v17l-6-4l-6 4V4z"
        stroke={color}
        strokeWidth={1.9}
        strokeLinejoin="round"
        fill={filled ? color : 'none'}
      />
    </Svg>
  );
}

/** A small all-caps label above a block, used for every section on this page. */
function SectionLabel({ children }: { children: string }): ReactElement {
  const { colors, fonts, fontSizes } = useTheme();

  return (
    <Text
      accessibilityRole="header"
      style={{
        color: colors.mutedFg,
        fontFamily: fonts.body,
        fontSize: fontSizes.xs,
        fontWeight: '700',
        letterSpacing: 1,
        textTransform: 'uppercase',
      }}
    >
      {children}
    </Text>
  );
}

/** The placeholder shown while the article is in flight. */
function ArticleSkeleton(): ReactElement {
  const { radii, space } = useTheme();

  return (
    <View
      accessibilityLabel="Loading the story"
      accessibilityRole="progressbar"
      style={{ rowGap: space.lg, paddingTop: space.md }}
    >
      <Skeleton height={180} radius={radii.lg} />
      <Skeleton height={26} />
      <Skeleton height={26} width="75%" />
      <View style={{ rowGap: space.sm }}>
        <Skeleton height={14} />
        <Skeleton height={14} />
        <Skeleton height={14} />
        <Skeleton height={14} width="60%" />
      </View>
    </View>
  );
}

export default function ArticleScreen(): ReactElement {
  const { colors, radii, space, fonts, fontSizes, lineHeights } = useTheme();
  const { id } = useLocalSearchParams<{ id: string }>();
  const { isBookmarked, isPending, toggle, loading: bookmarksLoading } = useBookmarks();

  const articleId = Number.parseInt(String(id ?? ''), 10);
  const validId = Number.isFinite(articleId) && articleId > 0;

  const [article, setArticle] = useState<ArticleCard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [attempt, setAttempt] = useState(0);

  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    if (!validId) {
      setLoading(false);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);

    void (async () => {
      try {
        const next = await api.getArticle(articleId);
        if (!cancelled && mounted.current) {
          setArticle(next);
        }
      } catch (caught) {
        if (!cancelled && mounted.current && !isAbortError(caught)) {
          setError(describeError(caught));
        }
      } finally {
        if (!cancelled && mounted.current) {
          setLoading(false);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [articleId, attempt, validId]);

  const goBack = useCallback(() => {
    if (router.canGoBack()) {
      router.back();
      return;
    }
    // Opened from a deep link with nothing behind it. The feed is the only
    // sensible place to land.
    router.replace('/');
  }, []);

  const saved =
    article !== null && (bookmarksLoading ? article.bookmarked : isBookmarked(article.id));

  const bodyText: TextStyle = {
    color: colors.fg,
    fontFamily: fonts.body,
    fontSize: fontSizes.md,
    lineHeight: lineHeights.md,
  };

  const metaText: TextStyle = {
    color: colors.mutedFg,
    fontFamily: fonts.body,
    fontSize: fontSizes.xs,
  };

  let body: ReactElement;

  if (!validId) {
    body = (
      <EmptyState
        title="Story not found"
        body="That link does not point at a story FinBit knows about."
        action={{ label: 'Back to the feed', onPress: goBack }}
      />
    );
  } else if (loading && article === null) {
    body = <ArticleSkeleton />;
  } else if (error !== null && article === null) {
    body = (
      <ErrorState
        title="The story did not load"
        message={error}
        onRetry={() => setAttempt((current) => current + 1)}
      />
    );
  } else if (article === null) {
    body = (
      <EmptyState
        title="Story not found"
        body="This story may have been removed since you saved it."
        action={{ label: 'Back to the feed', onPress: goBack }}
      />
    );
  } else {
    const tickers = article.symbols.map((tag) => tag.symbol);
    const published = absoluteTime(article.published_at);

    body = (
      <View style={{ rowGap: space.lg, paddingTop: space.md, paddingBottom: space.xxl }}>
        <CardImage
          src={article.image_url}
          category={article.category}
          symbols={tickers}
          direction={article.impact_direction}
        />

        {article.is_breaking ? (
          <View
            style={[
              styles.breaking,
              {
                backgroundColor: colors.breaking,
                borderRadius: radii.sm,
                paddingHorizontal: space.sm,
              },
            ]}
          >
            <Text
              style={{
                color: colors.onBreaking,
                fontFamily: fonts.body,
                fontSize: fontSizes.xs,
                fontWeight: '700',
                letterSpacing: 1,
              }}
            >
              BREAKING
            </Text>
          </View>
        ) : null}

        <View style={{ rowGap: space.sm }}>
          <Text style={[metaText, styles.metaLabel]}>
            {`${categoryLabel(article.category)} · ${published}`}
          </Text>
          <Text
            accessibilityRole="header"
            style={{
              color: colors.fg,
              fontFamily: fonts.headline,
              fontSize: fontSizes.xxl,
              lineHeight: lineHeights.xxl,
              fontWeight: '600',
            }}
          >
            {article.headline}
          </Text>
          <Text style={metaText}>
            {`${sourceCountLabel(article.sources.length)} · ${readingMinutes(article.summary)} min read`}
          </Text>
        </View>

        <Text style={bodyText}>{article.summary}</Text>

        {article.why_it_matters ? (
          <View
            style={[
              styles.aside,
              {
                backgroundColor: colors.muted,
                borderLeftColor: colors.accent,
                borderRadius: radii.md,
                padding: space.md,
                rowGap: space.xs,
              },
            ]}
          >
            <SectionLabel>Why it matters</SectionLabel>
            <Text style={bodyText}>{article.why_it_matters}</Text>
          </View>
        ) : null}

        <View style={{ rowGap: space.md }}>
          <SectionLabel>Market Impact</SectionLabel>

          <View style={[styles.impactRow, { columnGap: space.sm, rowGap: space.sm }]}>
            <ImpactBadge impact={article.impact} direction={article.impact_direction} />
            <View
              accessible
              accessibilityLabel={`Sentiment ${SENTIMENT_LABELS[article.sentiment] ?? 'neutral'}`}
              style={[styles.sentiment, { columnGap: space.xs }]}
            >
              <View
                style={[
                  styles.sentimentDot,
                  { backgroundColor: sentimentColor(colors, article.sentiment) },
                ]}
              />
              <Text style={metaText}>
                {SENTIMENT_LABELS[article.sentiment] ?? SENTIMENT_LABELS.neutral}
              </Text>
            </View>
          </View>

          {article.impact_map.length > 0 ? (
            <View
              style={{
                borderWidth: StyleSheet.hairlineWidth,
                borderColor: colors.border,
                borderRadius: radii.md,
              }}
            >
              {article.impact_map.map((entry, index) => (
                <View
                  key={`${entry.name}-${index}`}
                  style={[
                    styles.impactEntry,
                    {
                      paddingHorizontal: space.md,
                      paddingVertical: space.sm,
                      borderTopWidth: index === 0 ? 0 : StyleSheet.hairlineWidth,
                      borderTopColor: colors.border,
                    },
                  ]}
                >
                  <Text
                    numberOfLines={1}
                    style={{
                      color: colors.fg,
                      fontFamily: fonts.body,
                      fontSize: fontSizes.sm,
                      flex: 1,
                    }}
                  >
                    {entry.name}
                  </Text>
                  <Text
                    style={{
                      color: entryColor(colors, entry.direction),
                      fontFamily: fonts.body,
                      fontSize: fontSizes.sm,
                      fontWeight: '600',
                    }}
                  >
                    {IMPACT_ENTRY_LABELS[entry.direction] ?? IMPACT_ENTRY_LABELS.neutral}
                  </Text>
                </View>
              ))}
            </View>
          ) : null}

          <Text style={metaText}>{DISCLAIMER}</Text>
        </View>

        {article.symbols.length > 0 ? (
          <View style={{ rowGap: space.sm }}>
            <SectionLabel>Tickers</SectionLabel>
            <SymbolChips symbols={article.symbols} max={12} />
          </View>
        ) : null}

        {article.topics.length > 0 ? (
          <View style={{ rowGap: space.sm }}>
            <SectionLabel>Topics</SectionLabel>
            <Text style={[bodyText, { fontSize: fontSizes.sm }]}>{article.topics.join(', ')}</Text>
          </View>
        ) : null}

        {article.sources.length > 0 ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={`Show the ${sourceCountLabel(article.sources.length)} behind this story`}
            onPress={() => setSourcesOpen(true)}
            style={({ pressed }) => [
              styles.sourcesButton,
              {
                borderColor: colors.border,
                borderRadius: radii.md,
                paddingHorizontal: space.lg,
                opacity: pressed ? 0.7 : 1,
              },
            ]}
          >
            <Text
              style={{
                color: colors.fg,
                fontFamily: fonts.body,
                fontSize: fontSizes.md,
                fontWeight: '600',
              }}
            >
              {`Read the ${sourceCountLabel(article.sources.length)}`}
            </Text>
          </Pressable>
        ) : null}

        <SourcesSheet
          open={sourcesOpen}
          onClose={() => setSourcesOpen(false)}
          headline={article.headline}
          sources={article.sources}
        />
      </View>
    );
  }

  return (
    <Screen edges={['top']} scroll padded>
      <View style={[styles.header, { paddingVertical: space.xs }]}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Go back"
          onPress={goBack}
          style={({ pressed }) => [
            styles.iconButton,
            { marginLeft: -space.md, borderRadius: radii.md, opacity: pressed ? 0.6 : 1 },
          ]}
        >
          <BackGlyph color={colors.fg} />
        </Pressable>

        {article === null ? null : (
          <Pressable
            accessibilityRole="button"
            accessibilityState={{ selected: saved, busy: isPending(article.id) }}
            accessibilityLabel={saved ? 'Remove this story from saved' : 'Save this story'}
            onPress={() => void toggle(article)}
            style={({ pressed }) => [
              styles.iconButton,
              { marginRight: -space.md, borderRadius: radii.md, opacity: pressed ? 0.6 : 1 },
            ]}
          >
            <BookmarkGlyph color={saved ? colors.accent : colors.mutedFg} filled={saved} />
          </Pressable>
        )}
      </View>

      {body}
    </Screen>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  iconButton: {
    width: MIN_TOUCH_TARGET,
    height: MIN_TOUCH_TARGET,
    alignItems: 'center',
    justifyContent: 'center',
  },
  metaLabel: {
    fontWeight: '700',
    letterSpacing: 1,
    textTransform: 'uppercase',
  },
  breaking: {
    alignSelf: 'flex-start',
    height: 22,
    justifyContent: 'center',
  },
  aside: {
    borderLeftWidth: 3,
  },
  impactRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'center',
  },
  impactEntry: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  sentiment: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  sentimentDot: {
    width: 8,
    height: 8,
    borderRadius: 999,
  },
  sourcesButton: {
    minHeight: MIN_TOUCH_TARGET,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: StyleSheet.hairlineWidth,
  },
});
