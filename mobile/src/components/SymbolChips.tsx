/**
 * The ticker chips on a story card.
 *
 * Symbols arrive already canonicalised by the pipeline (CONTRACT.md section 4),
 * so a chip is a plain uppercase token: RELIANCE, NIFTY, USDINR. They are set in
 * the mono face because a column of tickers with mixed digit widths reads as
 * ragged, and mono is the one place in this app where that matters.
 *
 * A chip is interactive only when the caller passes onSelect. Without a handler
 * it renders as text, not as a button that does nothing, so a screen reader is
 * never told about a control that is not there.
 *
 * On touch targets: a 32 pt chip in a row of chips is the platform norm, and
 * stacking six 44 pt pills would push the card's own content off screen. The
 * chips therefore carry hitSlop that brings the real target to the 44 pt
 * minimum in CONTRACT.md section 10 while the drawn pill stays compact.
 */

import { type ReactElement } from 'react';
import {
  Pressable,
  StyleSheet,
  Text,
  View,
  type StyleProp,
  type TextStyle,
  type ViewStyle,
} from 'react-native';

import { MIN_TOUCH_TARGET, useTheme } from '@/src/theme';
import { type SymbolTag } from '@/src/lib/types';

const CHIP_HEIGHT = { md: 32, sm: 26 } as const;

/** Half of what each side must gain to reach the minimum tappable square. */
function slopFor(height: number): number {
  return Math.max(0, Math.round((MIN_TOUCH_TARGET - height) / 2));
}

export interface SymbolChipsProps {
  symbols: SymbolTag[];
  /** Filters the feed by the chosen ticker. Omit for a read-only row. */
  onSelect?: (symbol: string) => void;
  /** Chips beyond this are summed into a trailing "+n" chip. Default 6. */
  max?: number;
  /** 'sm' is for a compact search or saved row. */
  size?: 'md' | 'sm';
  style?: StyleProp<ViewStyle>;
}

export function SymbolChips({
  symbols,
  onSelect,
  max = 6,
  size = 'md',
  style,
}: SymbolChipsProps): ReactElement | null {
  const { colors, radii, space, fonts, fontSizes } = useTheme();

  if (symbols.length === 0) {
    return null;
  }

  const shown = symbols.slice(0, Math.max(1, max));
  const overflow = symbols.length - shown.length;
  const height = CHIP_HEIGHT[size];
  const slop = slopFor(height);

  const chip: ViewStyle = {
    height,
    borderRadius: radii.pill,
    paddingHorizontal: space.md,
    backgroundColor: colors.muted,
    borderColor: colors.border,
  };

  const label: TextStyle = {
    color: colors.fg,
    fontFamily: fonts.mono,
    fontSize: size === 'md' ? fontSizes.sm : fontSizes.xs,
    fontWeight: '600',
  };

  return (
    <View style={[styles.row, { columnGap: space.sm, rowGap: space.sm }, style]}>
      {shown.map((tag) =>
        onSelect ? (
          <Pressable
            key={`${tag.symbol}-${tag.exchange}`}
            accessibilityRole="button"
            accessibilityLabel={`Filter the feed by ${tag.symbol}`}
            hitSlop={{ top: slop, bottom: slop, left: space.xs, right: space.xs }}
            onPress={() => onSelect(tag.symbol)}
            style={({ pressed }) => [styles.chip, chip, pressed ? styles.pressed : null]}
          >
            <Text style={label}>{tag.symbol}</Text>
          </Pressable>
        ) : (
          <View key={`${tag.symbol}-${tag.exchange}`} style={[styles.chip, chip]}>
            <Text style={label}>{tag.symbol}</Text>
          </View>
        ),
      )}

      {overflow > 0 ? (
        <View style={[styles.chip, chip, { backgroundColor: 'transparent' }]}>
          <Text style={[label, { color: colors.mutedFg }]}>{`+${overflow}`}</Text>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    alignItems: 'center',
  },
  chip: {
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: StyleSheet.hairlineWidth,
  },
  pressed: {
    opacity: 0.7,
  },
});
