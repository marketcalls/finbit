/**
 * The story card, in both of its shapes.
 *
 * Full mode is one page of the feed pager, so the card is given an exact height
 * and must fill it without ever exceeding it: a card one point too tall would
 * push the snap points out of step with getItemLayout and the feed would drift
 * by a growing offset as the user swipes. Every block therefore either has a
 * fixed size or is clamped with numberOfLines, the reading column takes the
 * slack with flex, and the container clips whatever a very long headline still
 * manages to overflow.
 *
 * The summary is clamped rather than scrolled. A card that scrolls inside a
 * pager fights the pager for the same gesture, and the 50 to 80 word summary is
 * the whole point of the format anyway: when a reader wants more, the reading
 * column opens the full story.
 *
 * Compact mode is a leading-thumbnail row for the search and saved lists.
 *
 * The card itself is not a button. The reading column, the sources control and
 * the bookmark toggle are the interactive elements, which is what lets a screen
 * reader offer "open the full story" and "save" as two separate actions instead
 * of one ambiguous tap target wrapping the whole page.
 */

import * as Haptics from 'expo-haptics';
import { useCallback, useState, type ReactElement } from 'react';
import {
  Pressable,
  StyleSheet,
  Text,
  View,
  type StyleProp,
  type TextStyle,
  type ViewStyle,
} from 'react-native';
import Animated, {
  useAnimatedStyle,
  useReducedMotion,
  useSharedValue,
  withSequence,
  withSpring,
} from 'react-native-reanimated';
import Svg, { Path } from 'react-native-svg';

import { CardImage, categoryLabel } from '@/src/components/CardImage';
import { ImpactBadge } from '@/src/components/ImpactBadge';
import { SourcesSheet } from '@/src/components/SourcesSheet';
import { SymbolChips } from '@/src/components/SymbolChips';
import { relativeTime, sourceCountLabel } from '@/src/lib/format';
import { type ArticleCard, type Sentiment } from '@/src/lib/types';
import { useBookmarks } from '@/src/store/BookmarksProvider';
import { MIN_TOUCH_TARGET, useTheme, type ColorTokens } from '@/src/theme';

/** The share of a full-screen card the lead image may claim. */
const IMAGE_MAX_FRACTION = 0.34;

/**
 * How many summary lines fit, by card height. Measured against the other fixed
 * blocks rather than computed, because the alternative is measuring text on
 * every card and re-rendering the pager mid-swipe.
 */
function summaryLines(height: number | undefined): number {
  if (height === undefined) {
    return 6;
  }
  if (height >= 820) {
    return 8;
  }
  if (height >= 720) {
    return 6;
  }
  if (height >= 620) {
    return 5;
  }
  return 4;
}

const SENTIMENT_LABELS: Record<Sentiment, string> = {
  positive: 'Positive',
  negative: 'Negative',
  neutral: 'Neutral',
  mixed: 'Mixed',
};

function sentimentColor(colors: ColorTokens, sentiment: Sentiment): string {
  if (sentiment === 'positive') {
    return colors.bull;
  }
  if (sentiment === 'negative') {
    return colors.bear;
  }
  return sentiment === 'mixed' ? colors.fg : colors.flat;
}

function AlertGlyph({ color }: { color: string }): ReactElement {
  return (
    <Svg width={13} height={13} viewBox="0 0 24 24" fill="none">
      <Path
        d="M12 8v5"
        stroke={color}
        strokeWidth={2.4}
        strokeLinecap="round"
      />
      <Path d="M12 17h0.01" stroke={color} strokeWidth={2.6} strokeLinecap="round" />
      <Path
        d="M12 3L22 20H2L12 3z"
        stroke={color}
        strokeWidth={2}
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

function ChevronGlyph({ color }: { color: string }): ReactElement {
  return (
    <Svg width={15} height={15} viewBox="0 0 24 24" fill="none">
      <Path
        d="M9 5L16 12L9 19"
        stroke={color}
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </Svg>
  );
}

/** A tiny dot separating two pieces of meta text. */
function Dot({ color }: { color: string }): ReactElement {
  return <View style={[styles.dot, { backgroundColor: color }]} />;
}

/**
 * The bookmark control, with a spring pop on the way in.
 *
 * The pop is the one place a small animation earns its keep: saving is the only
 * write the app makes, it happens on a card that fills the screen, and the icon
 * is the only thing that changes. It is skipped entirely under reduce motion,
 * and the icon still changes shape, so the state is never carried by the
 * animation alone.
 */
function BookmarkButton({ article }: { article: ArticleCard }): ReactElement {
  const { colors, radii } = useTheme();
  const { isBookmarked, isPending, toggle, loading } = useBookmarks();
  const reduceMotion = useReducedMotion();
  const scale = useSharedValue(1);

  // Until the provider has its first list, the feed payload is the best answer.
  const saved = loading ? article.bookmarked : isBookmarked(article.id);
  const pending = isPending(article.id);

  const animated = useAnimatedStyle(() => ({ transform: [{ scale: scale.value }] }));

  const onPress = useCallback(() => {
    if (!reduceMotion) {
      scale.value = withSequence(
        withSpring(1.25, { damping: 12, stiffness: 320 }),
        withSpring(1, { damping: 14, stiffness: 260 }),
      );
    }
    void Haptics.selectionAsync().catch(() => {
      // Haptics are absent on a simulator and on web. Never worth an error.
    });
    void toggle(article);
  }, [article, reduceMotion, scale, toggle]);

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ selected: saved, busy: pending }}
      accessibilityLabel={saved ? 'Remove this story from saved' : 'Save this story'}
      onPress={onPress}
      style={({ pressed }) => [
        styles.iconButton,
        { borderRadius: radii.md, opacity: pressed ? 0.6 : 1 },
      ]}
    >
      <Animated.View style={animated}>
        <BookmarkGlyph color={saved ? colors.accent : colors.mutedFg} filled={saved} />
      </Animated.View>
    </Pressable>
  );
}

export interface NewsCardProps {
  article: ArticleCard;
  /**
   * The pager viewport height. Setting it makes the card exactly one page tall,
   * which is what the feed does. Leaving it unset lets the card size itself.
   */
  height?: number;
  /** A leading-thumbnail row for the search and saved lists. */
  compact?: boolean;
  /** Opens the full story. */
  onPress?: () => void;
  /** Filters the feed by a tapped ticker. Omit for read-only chips. */
  onSelectSymbol?: (symbol: string) => void;
  style?: StyleProp<ViewStyle>;
}

export function NewsCard({
  article,
  height,
  compact = false,
  onPress,
  onSelectSymbol,
  style,
}: NewsCardProps): ReactElement {
  const { colors, radii, space, fonts, fontSizes, lineHeights } = useTheme();
  const [sourcesOpen, setSourcesOpen] = useState(false);

  const published = relativeTime(article.published_at);
  const sourceCount = article.sources.length;
  const tickers = article.symbols.map((tag) => tag.symbol);

  const metaText: TextStyle = {
    color: colors.mutedFg,
    fontFamily: fonts.body,
    fontSize: fontSizes.xs,
  };

  const headlineStyle: TextStyle = {
    color: colors.fg,
    fontFamily: fonts.headline,
    fontSize: compact ? fontSizes.lg : fontSizes.xxl,
    lineHeight: compact ? lineHeights.lg : lineHeights.xxl,
    fontWeight: '600',
  };

  const summaryStyle: TextStyle = {
    color: colors.mutedFg,
    fontFamily: fonts.body,
    fontSize: compact ? fontSizes.sm : fontSizes.md,
    lineHeight: compact ? lineHeights.sm : lineHeights.md,
  };

  const meta = (
    <View style={[styles.meta, { columnGap: space.sm }]}>
      <Text style={[metaText, styles.metaLabel]}>{categoryLabel(article.category)}</Text>
      {published === '' ? null : (
        <>
          <Dot color={colors.mutedFg} />
          <Text style={metaText}>{published}</Text>
        </>
      )}
    </View>
  );

  if (compact) {
    return (
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={article.headline}
        accessibilityHint="Opens the full story"
        onPress={onPress}
        style={({ pressed }) => [
          styles.compact,
          {
            backgroundColor: colors.card,
            borderColor: colors.border,
            borderRadius: radii.md,
            padding: space.lg,
            columnGap: space.md,
            opacity: pressed ? 0.75 : 1,
          },
          style,
        ]}
      >
        <CardImage
          src={article.image_url}
          category={article.category}
          symbols={tickers}
          direction={article.impact_direction}
          variant="thumb"
        />

        <View style={styles.grow}>
          {article.is_breaking ? (
            <View style={{ marginBottom: space.xs }}>
              <BreakingFlag />
            </View>
          ) : null}
          <Text numberOfLines={3} style={headlineStyle}>
            {article.headline}
          </Text>
          <Text numberOfLines={2} style={[summaryStyle, { marginTop: space.xs }]}>
            {article.summary}
          </Text>
          <View style={{ marginTop: space.sm }}>{meta}</View>
        </View>

        {/*
          Nested inside the row on purpose: React Native gives the touch to the
          innermost responder, so tapping the icon saves the story and tapping
          anywhere else opens it.
        */}
        <BookmarkButton article={article} />
      </Pressable>
    );
  }

  return (
    <View
      style={[
        styles.page,
        {
          height,
          backgroundColor: colors.bg,
          paddingHorizontal: space.lg,
          paddingTop: space.md,
          paddingBottom: space.md,
          rowGap: space.md,
        },
        style,
      ]}
    >
      {article.is_breaking ? <BreakingFlag /> : null}

      <CardImage
        src={article.image_url}
        category={article.category}
        symbols={tickers}
        direction={article.impact_direction}
        maxHeight={height === undefined ? undefined : Math.round(height * IMAGE_MAX_FRACTION)}
      />

      {meta}

      <Pressable
        accessibilityRole="button"
        accessibilityLabel={article.headline}
        accessibilityHint="Opens the full story"
        onPress={onPress}
        style={({ pressed }) => [styles.reading, { opacity: pressed ? 0.75 : 1 }]}
      >
        <Text numberOfLines={3} style={headlineStyle}>
          {article.headline}
        </Text>
        <Text
          numberOfLines={summaryLines(height)}
          style={[summaryStyle, { marginTop: space.sm }]}
        >
          {article.summary}
        </Text>
      </Pressable>

      <View style={[styles.impact, { columnGap: space.sm, rowGap: space.sm }]}>
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

      <SymbolChips symbols={article.symbols} onSelect={onSelectSymbol} max={4} />

      <View
        style={[
          styles.footer,
          { borderTopColor: colors.border, paddingTop: space.sm, columnGap: space.sm },
        ]}
      >
        {sourceCount > 0 ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={`Show the ${sourceCountLabel(sourceCount)} behind this story`}
            onPress={() => setSourcesOpen(true)}
            style={({ pressed }) => [
              styles.sources,
              { borderRadius: radii.md, columnGap: space.xs, opacity: pressed ? 0.6 : 1 },
            ]}
          >
            <Text
              style={{
                color: colors.fg,
                fontFamily: fonts.body,
                fontSize: fontSizes.sm,
                fontWeight: '600',
              }}
            >
              {sourceCountLabel(sourceCount)}
            </Text>
            <ChevronGlyph color={colors.mutedFg} />
          </Pressable>
        ) : (
          <Text style={[metaText, styles.grow]}>
            {sourceCountLabel(article.source_count)} reported
          </Text>
        )}

        <View style={styles.grow} />
        <BookmarkButton article={article} />
      </View>

      <SourcesSheet
        open={sourcesOpen}
        onClose={() => setSourcesOpen(false)}
        headline={article.headline}
        sources={article.sources}
      />
    </View>
  );
}

/** The breaking flag. Colour plus the word, never colour alone. */
function BreakingFlag(): ReactElement {
  const { colors, radii, space, fonts, fontSizes } = useTheme();

  return (
    <View
      style={[
        styles.breaking,
        {
          backgroundColor: colors.breaking,
          borderRadius: radii.sm,
          paddingHorizontal: space.sm,
          columnGap: space.xs,
        },
      ]}
    >
      <AlertGlyph color={colors.onBreaking} />
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
  );
}

const styles = StyleSheet.create({
  page: {
    width: '100%',
    overflow: 'hidden',
  },
  compact: {
    flexDirection: 'row',
    borderWidth: StyleSheet.hairlineWidth,
  },
  reading: {
    flex: 1,
    overflow: 'hidden',
  },
  meta: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  metaLabel: {
    fontWeight: '700',
    letterSpacing: 1,
    textTransform: 'uppercase',
  },
  impact: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'center',
  },
  sentiment: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  footer: {
    flexDirection: 'row',
    alignItems: 'center',
    borderTopWidth: StyleSheet.hairlineWidth,
    minHeight: MIN_TOUCH_TARGET,
  },
  sources: {
    flexDirection: 'row',
    alignItems: 'center',
    minHeight: MIN_TOUCH_TARGET,
  },
  breaking: {
    flexDirection: 'row',
    alignItems: 'center',
    alignSelf: 'flex-start',
    height: 22,
  },
  iconButton: {
    width: MIN_TOUCH_TARGET,
    height: MIN_TOUCH_TARGET,
    alignItems: 'center',
    justifyContent: 'center',
  },
  dot: {
    width: 3,
    height: 3,
    borderRadius: 999,
  },
  sentimentDot: {
    width: 8,
    height: 8,
    borderRadius: 999,
  },
  grow: {
    flex: 1,
  },
});
