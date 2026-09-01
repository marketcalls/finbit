/**
 * One story as a list row, used by Search and Saved.
 *
 * The feed is a full-screen pager, but a result list is a scanning surface: the
 * user is looking for one story among many, not reading each one. So this row
 * carries only what distinguishes a story from its neighbours, which is the
 * headline, the section it belongs to, and how old it is. The summary, the
 * impact badge and the sources all live one tap away on the article screen.
 *
 * It is deliberately self-contained. Search and Saved are built alongside the
 * feed by a different agent, so this row shares no component with the feed card;
 * the only things it borrows are the tokens, the formatters and the API types
 * that every screen shares anyway.
 *
 * The thumbnail is the compact form CONTRACT.md section 14.5 specifies: a fixed
 * square, never a banner, so the row height is constant and the list cannot
 * shift while images arrive. The image is decorative in the accessibility sense
 * because the headline sits beside it and carries the meaning, so it is hidden
 * from the screen reader rather than given invented alt text.
 */

import { Image } from 'expo-image';
import { useState, type ReactElement } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { relativeTime, sourceCountLabel } from '@/src/lib/format';
import { CATEGORIES, type ArticleCard, type ImpactDirection } from '@/src/lib/types';
import { space, useTheme } from '@/src/theme';

/** CONTRACT.md section 14.5: a fixed 72 point square in compact mode. */
const THUMB_SIZE = 72;

/** How long the image fades in once decoded. Short enough not to read as motion. */
const IMAGE_FADE_MS = 160;

/** Display labels by key, built from the shared list so the two cannot drift. */
const CATEGORY_LABELS: Record<string, string> = Object.fromEntries(
  CATEGORIES.map((entry) => [entry.key, entry.label]),
);

export interface CompactArticleRowProps {
  article: ArticleCard;
  /** Usually a push to the article screen. The row does not navigate itself. */
  onPress: (article: ArticleCard) => void;
  testID?: string;
}

export function CompactArticleRow({
  article,
  onPress,
  testID,
}: CompactArticleRowProps): ReactElement {
  const { colors, space, fonts, fontSizes, lineHeights } = useTheme();

  const category = CATEGORY_LABELS[article.category] ?? article.category;
  const age = relativeTime(article.published_at);
  const sources = sourceCountLabel(article.source_count);

  // Spoken as one sentence, because a screen reader user hears the row before
  // deciding whether to open it and the meta line is what makes that decision.
  const spoken = [
    article.is_breaking ? 'Breaking.' : null,
    article.headline,
    [category, age, sources].filter((part) => part !== '').join(', '),
  ]
    .filter((part): part is string => part !== null && part !== '')
    .join('. ');

  return (
    <Pressable
      testID={testID}
      accessibilityRole="button"
      accessibilityLabel={spoken}
      accessibilityHint="Opens the full story"
      onPress={() => onPress(article)}
      style={({ pressed }) => [
        styles.row,
        {
          backgroundColor: pressed ? colors.muted : colors.bg,
          paddingHorizontal: space.lg,
          paddingVertical: space.md,
          columnGap: space.md,
        },
      ]}
    >
      <Thumbnail article={article} />

      <View style={styles.body}>
        <Text
          numberOfLines={3}
          style={{
            color: colors.fg,
            fontFamily: fonts.headline,
            fontSize: fontSizes.md,
            lineHeight: lineHeights.md,
          }}
        >
          {article.headline}
        </Text>

        <View style={[styles.meta, { columnGap: space.xs, marginTop: space.xs }]}>
          {article.is_breaking ? (
            <Text
              style={{
                color: colors.breaking,
                fontFamily: fonts.body,
                fontSize: fontSizes.xs,
                fontWeight: '700',
                letterSpacing: 0.6,
              }}
            >
              BREAKING
            </Text>
          ) : null}
          <MetaText text={category} />
          {age === '' ? null : <MetaDot />}
          {age === '' ? null : <MetaText text={age} />}
          <MetaDot />
          <MetaText text={sources} />
        </View>
      </View>
    </Pressable>
  );
}

/** A meta word. Its own component so the three of them cannot drift apart. */
function MetaText({ text }: { text: string }): ReactElement {
  const { colors, fonts, fontSizes } = useTheme();

  return (
    <Text
      numberOfLines={1}
      style={{
        color: colors.mutedFg,
        fontFamily: fonts.body,
        fontSize: fontSizes.xs,
      }}
    >
      {text}
    </Text>
  );
}

/** The separator between meta words. Punctuation, so it is not announced. */
function MetaDot(): ReactElement {
  const { colors, fonts, fontSizes } = useTheme();

  return (
    <Text
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
      style={{
        color: colors.border,
        fontFamily: fonts.body,
        fontSize: fontSizes.xs,
      }}
    >
      |
    </Text>
  );
}

/**
 * The lead image, or the typographic plate that stands in for it.
 *
 * A missing image is the normal case for roughly two stories in ten
 * (CONTRACT.md section 14.1), so the fallback is a designed state rather than an
 * error: the muted fill, the primary symbol or section name, tinted by the
 * impact direction. A broken image glyph must never be visible.
 */
function Thumbnail({ article }: { article: ArticleCard }): ReactElement {
  const { colors, radii } = useTheme();
  const [failed, setFailed] = useState(false);

  const usable = article.image_url !== null && article.image_url !== '' && !failed;

  return (
    <View
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
      style={[
        styles.thumb,
        { backgroundColor: colors.muted, borderRadius: radii.sm, borderColor: colors.border },
      ]}
    >
      {usable ? (
        <Image
          source={{ uri: article.image_url as string }}
          style={styles.fill}
          contentFit="cover"
          transition={IMAGE_FADE_MS}
          cachePolicy="memory-disk"
          // The headline beside it carries the meaning, so the image is not an
          // accessibility element and gets no invented description.
          accessible={false}
          onError={() => setFailed(true)}
        />
      ) : (
        <Plate article={article} />
      )}
    </View>
  );
}

function Plate({ article }: { article: ArticleCard }): ReactElement {
  const { colors, fonts, fontSizes } = useTheme();

  const tint = directionTint(article.impact_direction, colors.bull, colors.bear, colors.flat);
  const symbol = article.symbols.length > 0 ? article.symbols[0].symbol : null;
  const label = symbol ?? (CATEGORY_LABELS[article.category] ?? article.category).toUpperCase();

  return (
    <View style={[styles.fill, styles.plate]}>
      <Text
        numberOfLines={2}
        adjustsFontSizeToFit
        style={{
          color: tint,
          fontFamily: fonts.mono,
          fontSize: symbol === null ? fontSizes.xs : fontSizes.sm,
          fontWeight: '700',
          letterSpacing: 0.4,
          textAlign: 'center',
        }}
      >
        {label}
      </Text>
    </View>
  );
}

/**
 * The token a direction paints with. 'mixed' takes the neutral tone here rather
 * than the split treatment the full card uses, because a 72 point square has no
 * room to show two colours without reading as a rendering fault.
 */
function directionTint(
  direction: ImpactDirection,
  bull: string,
  bear: string,
  flat: string,
): string {
  if (direction === 'bullish') {
    return bull;
  }
  if (direction === 'bearish') {
    return bear;
  }
  return flat;
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'flex-start',
  },
  thumb: {
    width: THUMB_SIZE,
    height: THUMB_SIZE,
    overflow: 'hidden',
    borderWidth: StyleSheet.hairlineWidth,
  },
  fill: {
    width: '100%',
    height: '100%',
  },
  plate: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: space.xs,
  },
  body: {
    flex: 1,
  },
  meta: {
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
  },
});
