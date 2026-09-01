/**
 * The Market Impact chip (CONTRACT.md sections 10 and 11).
 *
 * Direction is carried by a glyph and a written word, never by colour alone, so
 * the chip still reads for a colour blind user and in a screen reader. The words
 * sit on the high contrast foreground token while bull, bear and flat colour the
 * glyph, the border and a low opacity wash behind the text, which keeps the label
 * above 4.5:1 in both themes.
 *
 * The wash is a solid token drawn at low opacity rather than an alpha colour,
 * because an alpha value would have to be written as a hex literal and
 * CONTRACT_MOBILE_ADMIN.md section 7 puts every hex in tokens.ts.
 *
 * 'mixed' renders as a split bull and bear chip rather than inventing a fourth
 * hue, matching the split rule on the fallback image plate.
 *
 * The badge draws the chip alone. The words "Market Impact" belong to the
 * section around it, which the card and the article screen both supply, so
 * repeating them here would say it twice.
 *
 * The glyphs are inline react-native-svg paths. The app ships no icon font and
 * no icon package (CONTRACT.md section 10), and a three-icon set is not worth a
 * dependency.
 */

import { type ReactElement } from 'react';
import { StyleSheet, Text, View, type StyleProp, type ViewStyle } from 'react-native';
import Svg, { Path } from 'react-native-svg';

import { type Impact, type ImpactDirection } from '@/src/lib/types';
import { useTheme, type ColorTokens } from '@/src/theme';

/** How strongly the tone washes the chip behind the text. */
const TINT_OPACITY = 0.14;

const GLYPH_SIZE = 15;
const SPLIT_GLYPH_SIZE = 13;

const IMPACT_LABELS: Record<Impact, string> = {
  high: 'High',
  medium: 'Medium',
  low: 'Low',
};

const DIRECTION_LABELS: Record<ImpactDirection, string> = {
  bullish: 'Bullish',
  bearish: 'Bearish',
  neutral: 'Neutral',
  mixed: 'Mixed',
};

type GlyphKind = 'up' | 'down' | 'flat';

/**
 * A trend arrow. One component with three path sets rather than three
 * components, because the frame, the stroke weight and the caps have to match
 * exactly or the chips look ragged next to each other in a list.
 */
function TrendGlyph({
  kind,
  color,
  size = GLYPH_SIZE,
}: {
  kind: GlyphKind;
  color: string;
  size?: number;
}): ReactElement {
  const line =
    kind === 'up' ? 'M3 17L9 11L13 15L21 7' : kind === 'down' ? 'M3 7L9 13L13 9L21 17' : 'M3 12H18';
  const head = kind === 'up' ? 'M15 7H21V13' : kind === 'down' ? 'M15 17H21V11' : 'M15 8L19 12L15 16';

  return (
    <Svg width={size} height={size} viewBox="0 0 24 24" fill="none">
      <Path
        d={line}
        stroke={color}
        strokeWidth={2.2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Path
        d={head}
        stroke={color}
        strokeWidth={2.2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </Svg>
  );
}

function glyphFor(direction: Exclude<ImpactDirection, 'mixed'>): GlyphKind {
  if (direction === 'bullish') {
    return 'up';
  }
  return direction === 'bearish' ? 'down' : 'flat';
}

function toneFor(colors: ColorTokens, direction: Exclude<ImpactDirection, 'mixed'>): string {
  if (direction === 'bullish') {
    return colors.bull;
  }
  return direction === 'bearish' ? colors.bear : colors.flat;
}

export interface ImpactBadgeProps {
  impact: Impact;
  direction: ImpactDirection;
  style?: StyleProp<ViewStyle>;
}

export function ImpactBadge({ impact, direction, style }: ImpactBadgeProps): ReactElement {
  const { colors, radii, space, fonts, fontSizes } = useTheme();

  // Fall back inside the vocabulary if the API ever sends a value outside it,
  // rather than rendering "undefined" onto a card.
  const impactLabel = IMPACT_LABELS[impact] ?? IMPACT_LABELS.low;
  const directionLabel = DIRECTION_LABELS[direction] ?? DIRECTION_LABELS.neutral;

  const chip: ViewStyle = {
    borderRadius: radii.pill,
    paddingHorizontal: space.md,
    paddingVertical: space.xs + 2,
    columnGap: space.xs + 2,
  };

  const labelStyle = {
    color: colors.fg,
    fontFamily: fonts.body,
    fontSize: fontSizes.sm,
    fontWeight: '600' as const,
  };

  const separator = (
    <Text style={{ color: colors.mutedFg, fontFamily: fonts.body, fontSize: fontSizes.sm }}>
      &middot;
    </Text>
  );

  if (direction === 'mixed') {
    return (
      <View
        accessible
        accessibilityLabel={`Market impact ${impactLabel}, direction mixed`}
        style={[styles.chip, chip, { borderColor: colors.border, backgroundColor: colors.muted }, style]}
      >
        {/* Bull on one half, bear on the other, so no new hue is introduced. */}
        <View style={[styles.split, { borderRadius: radii.pill }]}>
          <View style={[styles.splitHalf, { backgroundColor: colors.muted }]}>
            <TrendGlyph kind="up" color={colors.bull} size={SPLIT_GLYPH_SIZE} />
          </View>
          <View style={[styles.splitHalf, { backgroundColor: colors.muted }]}>
            <TrendGlyph kind="down" color={colors.bear} size={SPLIT_GLYPH_SIZE} />
          </View>
        </View>
        <Text style={labelStyle}>{directionLabel}</Text>
        {separator}
        <Text style={labelStyle}>{impactLabel}</Text>
      </View>
    );
  }

  const tone = toneFor(colors, direction);

  return (
    <View
      accessible
      accessibilityLabel={`Market impact ${impactLabel}, direction ${directionLabel.toLowerCase()}`}
      style={[styles.chip, chip, { borderColor: tone }, style]}
    >
      <View
        pointerEvents="none"
        style={[StyleSheet.absoluteFillObject, { backgroundColor: tone, opacity: TINT_OPACITY }]}
      />
      <TrendGlyph kind={glyphFor(direction)} color={tone} />
      <Text style={labelStyle}>{directionLabel}</Text>
      {separator}
      <Text style={labelStyle}>{impactLabel}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  chip: {
    flexDirection: 'row',
    alignItems: 'center',
    alignSelf: 'flex-start',
    borderWidth: StyleSheet.hairlineWidth,
    overflow: 'hidden',
  },
  split: {
    flexDirection: 'row',
    overflow: 'hidden',
  },
  splitHalf: {
    paddingHorizontal: 1,
  },
});
