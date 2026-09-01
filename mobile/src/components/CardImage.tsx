/**
 * The lead image on a story card (CONTRACT.md section 14.5).
 *
 * Three rules drive everything here, and they are all about the image never
 * being allowed to disturb the card around it:
 *
 * 1. Space is reserved before the pixels arrive. The banner is a fixed 16:9 box
 *    and the thumbnail a fixed square, so a full-screen pager, where every item
 *    must be exactly one viewport tall, never reflows when a late image decodes.
 * 2. The image is decorative in the accessibility sense. The headline sits
 *    directly beside it and carries the meaning, so the whole box is hidden from
 *    assistive technology. Inventing descriptive alt text for a picture nobody
 *    here has seen would be a guess, and repeating the headline would make a
 *    screen reader say it twice.
 * 3. A missing or broken image degrades into a typographic plate, never into a
 *    hole or a broken-image glyph: the muted token, the category label and up to
 *    two tickers, tinted by the impact direction token.
 *
 * Images are hotlinked from the publisher CDN, so failures are normal traffic
 * rather than exceptions: an expired URL, a hotlink block, a dropped connection.
 * The failure is tracked against the URL that failed, so a recycled row that now
 * shows a different story starts clean without an effect and without a flash of
 * the previous image.
 *
 * The box is never a link and never a button. The card's own controls stay the
 * only interactive elements.
 */

import { Image } from 'expo-image';
import { useState, type ReactElement } from 'react';
import { StyleSheet, Text, View, type StyleProp, type ViewStyle } from 'react-native';
import { useReducedMotion } from 'react-native-reanimated';

import { CATEGORIES, type ImpactDirection } from '@/src/lib/types';
import { useTheme, type ColorTokens } from '@/src/theme';

/** The fallback plate shows at most two tickers before it turns into a wall. */
const MAX_FALLBACK_SYMBOLS = 2;

/** Contract section 14.5: the banner is a 16:9 box, the thumbnail a 72 pt square. */
const BANNER_ASPECT = 16 / 9;
const THUMB_SIZE = 72;

/** Cross fade when the bitmap lands, in milliseconds. Opacity only. */
const FADE_MS = 200;

/** How strongly the direction rule reads under the plate. */
const RULE_HEIGHT = 3;
const RULE_WIDTH = 40;

/**
 * The display label for a category key.
 *
 * It lives here rather than in NewsCard because the fallback plate is the first
 * thing that needs it, and NewsCard already imports this file. The article
 * screen imports it from here too, so the mapping exists once.
 */
export function categoryLabel(category: string): string {
  const known = CATEGORIES.find((entry) => entry.key === category);
  if (known) {
    return known.label;
  }
  const trimmed = category.trim();
  return trimmed === '' ? 'Markets' : trimmed.toUpperCase();
}

/**
 * Semantic mapping from CONTRACT.md section 10. 'mixed' never gets a hue of its
 * own: it falls back to the foreground and the rule below splits instead.
 */
function directionColor(colors: ColorTokens, direction: ImpactDirection): string {
  if (direction === 'bullish') {
    return colors.bull;
  }
  if (direction === 'bearish') {
    return colors.bear;
  }
  return direction === 'mixed' ? colors.fg : colors.flat;
}

/**
 * Only an absolute http or https URL is usable. The backend already filters
 * these, so this is a cheap guard against a bad row rather than a policy.
 */
function usableSource(src: string | null | undefined): string | null {
  if (typeof src !== 'string') {
    return null;
  }
  const trimmed = src.trim();
  const lower = trimmed.toLowerCase();
  if (!lower.startsWith('http://') && !lower.startsWith('https://')) {
    return null;
  }
  return trimmed;
}

/** First occurrences only, blanks dropped, capped. */
function fallbackSymbols(symbols: string[]): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const raw of symbols) {
    const symbol = typeof raw === 'string' ? raw.trim() : '';
    if (symbol === '' || seen.has(symbol)) {
      continue;
    }
    seen.add(symbol);
    out.push(symbol);
    if (out.length === MAX_FALLBACK_SYMBOLS) {
      break;
    }
  }
  return out;
}

/**
 * A short rule under the plate carrying the direction as colour. 'mixed' is a
 * split bull and bear rule, matching the split chip in ImpactBadge, so no fourth
 * hue is invented. Colour is never the only carrier: the card states the
 * direction in words a few lines below.
 */
function DirectionRule({ direction }: { direction: ImpactDirection }): ReactElement {
  const { colors, radii, space } = useTheme();

  const base: ViewStyle = {
    height: RULE_HEIGHT,
    width: RULE_WIDTH,
    borderRadius: radii.pill,
    marginTop: space.md,
    overflow: 'hidden',
  };

  if (direction === 'mixed') {
    return (
      <View style={[base, styles.row]}>
        <View style={[styles.fill, { backgroundColor: colors.bull }]} />
        <View style={[styles.fill, { backgroundColor: colors.bear }]} />
      </View>
    );
  }

  return <View style={[base, { backgroundColor: directionColor(colors, direction) }]} />;
}

export interface CardImageProps {
  /** ArticleCard.image_url. Null means no source page carried one. */
  src: string | null;
  /** ArticleCard.category, shown on the fallback plate. */
  category: string;
  /** ArticleCard.symbols reduced to plain tickers. At most two are shown. */
  symbols: string[];
  /** ArticleCard.impact_direction, which tints the fallback plate. */
  direction: ImpactDirection;
  /** 'banner' is the 16:9 lead image, 'thumb' the 72 pt square for a row. */
  variant?: 'banner' | 'thumb';
  /**
   * Caps the banner height. A full-screen card on a tall phone would otherwise
   * hand a third of the viewport to a stock photograph.
   */
  maxHeight?: number;
  style?: StyleProp<ViewStyle>;
}

export function CardImage({
  src,
  category,
  symbols,
  direction,
  variant = 'banner',
  maxHeight,
  style,
}: CardImageProps): ReactElement {
  const { colors, radii, fonts, fontSizes, space } = useTheme();
  const reduceMotion = useReducedMotion();

  // Keyed by the URL it describes rather than a bare boolean, so a recycled row
  // resets during render with no effect and no flash of the previous story.
  const [failedSrc, setFailedSrc] = useState<string | null>(null);

  const url = usableSource(src);
  const broken = url === null || failedSrc === url;
  const thumb = variant === 'thumb';

  const box: ViewStyle = thumb
    ? { width: THUMB_SIZE, height: THUMB_SIZE, borderRadius: radii.md }
    : { width: '100%', aspectRatio: BANNER_ASPECT, borderRadius: radii.lg, maxHeight };

  const shown = broken ? fallbackSymbols(symbols) : [];
  const tint = directionColor(colors, direction);
  const label = categoryLabel(category);

  return (
    <View
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
      style={[
        styles.box,
        box,
        { backgroundColor: colors.muted, borderColor: colors.border },
        style,
      ]}
    >
      {broken ? (
        <View style={[styles.plate, { paddingHorizontal: thumb ? space.xs : space.lg }]}>
          <Text
            numberOfLines={1}
            style={{
              color: colors.mutedFg,
              fontFamily: fonts.body,
              fontSize: thumb ? fontSizes.xs : fontSizes.sm,
              fontWeight: '700',
              letterSpacing: 1,
              textTransform: 'uppercase',
            }}
          >
            {label}
          </Text>

          {shown.length > 0 ? (
            <View style={{ marginTop: thumb ? 0 : space.sm }}>
              {shown.map((symbol) => (
                <Text
                  key={symbol}
                  numberOfLines={1}
                  style={{
                    color: tint,
                    fontFamily: fonts.mono,
                    fontSize: thumb ? fontSizes.xs : fontSizes.xxl,
                    fontWeight: '700',
                    textAlign: 'center',
                  }}
                >
                  {symbol}
                </Text>
              ))}
            </View>
          ) : null}

          {thumb ? null : <DirectionRule direction={direction} />}
        </View>
      ) : (
        /*
          The muted box behind this image is the placeholder, which is why there
          is no spinner: a tinted rectangle is far quieter than a spinner firing
          on every card of a scroll feed. recyclingKey tells expo-image to blank
          the view when a row is reused, so a recycled card never shows the
          previous story's picture for a frame.
        */
        <Image
          source={{ uri: url }}
          style={styles.image}
          contentFit="cover"
          transition={reduceMotion ? 0 : FADE_MS}
          cachePolicy="memory-disk"
          recyclingKey={url}
          onError={() => setFailedSrc(url)}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  box: {
    overflow: 'hidden',
    borderWidth: StyleSheet.hairlineWidth,
    flexShrink: 0,
  },
  image: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
  },
  plate: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  row: {
    flexDirection: 'row',
  },
  fill: {
    flex: 1,
  },
});
