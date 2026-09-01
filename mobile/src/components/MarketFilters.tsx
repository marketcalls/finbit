/**
 * The market quick filters that sit under the category strip.
 *
 * These filter by symbol rather than by category (CONTRACT.md section 4), which
 * is a different question from "what kind of news is this": Nifty moves show up
 * under india, stocks and economy alike. Keeping them as a second, separate row
 * is what stops the category strip from turning into a bag of unrelated tokens.
 *
 * The row collapses because it is the less used of the two controls and a
 * full-screen card needs every point of height it can get. Collapsing it must
 * never hide state, though, so an active filter is promoted into the header as a
 * chip with its own clear button: the user can always see what the feed is
 * filtered by and undo it in one tap without expanding anything.
 *
 * The header also carries a symbol the six chips do not contain, which happens
 * when a ticker chip on a card is tapped. Rendering that symbol here rather than
 * inventing a second "active filter" bar keeps one place responsible for
 * answering "why am I not seeing everything".
 */

import { useCallback, useState, type ReactElement } from 'react';
import {
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
  type StyleProp,
  type ViewStyle,
} from 'react-native';
import Animated, { FadeInUp, FadeOutUp, useReducedMotion } from 'react-native-reanimated';
import Svg, { Path } from 'react-native-svg';

import { type ConfigMarketFilter } from '@/src/lib/types';
import { MIN_TOUCH_TARGET, useTheme } from '@/src/theme';

const CHIP_HEIGHT = 32;
const SLOP = Math.round((MIN_TOUCH_TARGET - CHIP_HEIGHT) / 2);

const REVEAL_MS = 160;

function Chevron({ color, open }: { color: string; open: boolean }): ReactElement {
  return (
    <Svg width={16} height={16} viewBox="0 0 24 24" fill="none">
      <Path
        d={open ? 'M6 15L12 9L18 15' : 'M6 9L12 15L18 9'}
        stroke={color}
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </Svg>
  );
}

function ClearGlyph({ color }: { color: string }): ReactElement {
  return (
    <Svg width={12} height={12} viewBox="0 0 24 24" fill="none">
      <Path d="M6 6L18 18M18 6L6 18" stroke={color} strokeWidth={2.5} strokeLinecap="round" />
    </Svg>
  );
}

export interface MarketFiltersProps {
  /** Enabled market filters, exactly as ConfigProvider hands them over. */
  filters: ConfigMarketFilter[];
  /** The active symbol, which may be a ticker that is not one of the chips. */
  value: string | null;
  /** Called with the new symbol, or null to clear the filter. */
  onChange: (next: string | null) => void;
  style?: StyleProp<ViewStyle>;
}

export function MarketFilters({
  filters,
  value,
  onChange,
  style,
}: MarketFiltersProps): ReactElement | null {
  const { colors, radii, space, fonts, fontSizes } = useTheme();
  const reduceMotion = useReducedMotion();
  const [open, setOpen] = useState(false);

  const toggle = useCallback((symbol: string) => {
    onChange(value === symbol ? null : symbol);
  }, [onChange, value]);

  if (filters.length === 0) {
    return null;
  }

  const known = filters.find((filter) => filter.key === value);
  const activeLabel = value === null ? null : (known?.label ?? value);

  const chipBase: ViewStyle = {
    height: CHIP_HEIGHT,
    borderRadius: radii.pill,
    paddingHorizontal: space.md,
    borderWidth: StyleSheet.hairlineWidth,
  };

  return (
    <View style={style}>
      <View style={[styles.header, { paddingHorizontal: space.lg, columnGap: space.sm }]}>
        <Pressable
          accessibilityRole="button"
          accessibilityState={{ expanded: open }}
          accessibilityLabel={open ? 'Hide the market filters' : 'Show the market filters'}
          onPress={() => setOpen((current) => !current)}
          hitSlop={{ top: space.xs, bottom: space.xs }}
          style={({ pressed }) => [
            styles.disclosure,
            { columnGap: space.xs, opacity: pressed ? 0.7 : 1 },
          ]}
        >
          <Text
            style={{
              color: colors.mutedFg,
              fontFamily: fonts.body,
              fontSize: fontSizes.xs,
              fontWeight: '700',
              letterSpacing: 1,
              textTransform: 'uppercase',
            }}
          >
            Markets
          </Text>
          <Chevron color={colors.mutedFg} open={open} />
        </Pressable>

        {activeLabel === null ? null : (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={`Clear the ${activeLabel} filter`}
            onPress={() => onChange(null)}
            hitSlop={{ top: SLOP, bottom: SLOP, left: space.xs, right: space.xs }}
            style={({ pressed }) => [
              styles.active,
              chipBase,
              {
                backgroundColor: colors.accent,
                borderColor: colors.accent,
                columnGap: space.xs,
                opacity: pressed ? 0.8 : 1,
              },
            ]}
          >
            <Text
              numberOfLines={1}
              style={{
                color: colors.onAccent,
                fontFamily: fonts.mono,
                fontSize: fontSizes.xs,
                fontWeight: '700',
              }}
            >
              {activeLabel}
            </Text>
            <ClearGlyph color={colors.onAccent} />
          </Pressable>
        )}
      </View>

      {open ? (
        <Animated.View
          entering={reduceMotion ? undefined : FadeInUp.duration(REVEAL_MS)}
          exiting={reduceMotion ? undefined : FadeOutUp.duration(REVEAL_MS)}
        >
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={[
              styles.strip,
              { paddingHorizontal: space.lg, columnGap: space.sm, paddingTop: space.sm },
            ]}
          >
            {filters.map((filter) => {
              const selected = filter.key === value;

              return (
                <Pressable
                  key={filter.key}
                  accessibilityRole="button"
                  accessibilityState={{ selected }}
                  accessibilityLabel={
                    selected ? `Clear the ${filter.label} filter` : `Show only ${filter.label} stories`
                  }
                  hitSlop={{ top: SLOP, bottom: SLOP }}
                  onPress={() => toggle(filter.key)}
                  style={({ pressed }) => [
                    styles.chip,
                    chipBase,
                    {
                      backgroundColor: selected ? colors.accent : colors.muted,
                      borderColor: selected ? colors.accent : colors.border,
                      opacity: pressed ? 0.75 : 1,
                    },
                  ]}
                >
                  <Text
                    numberOfLines={1}
                    style={{
                      color: selected ? colors.onAccent : colors.mutedFg,
                      fontFamily: fonts.body,
                      fontSize: fontSizes.sm,
                      fontWeight: selected ? '700' : '500',
                    }}
                  >
                    {filter.label}
                  </Text>
                </Pressable>
              );
            })}
          </ScrollView>
        </Animated.View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    minHeight: MIN_TOUCH_TARGET - 8,
  },
  disclosure: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  active: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  strip: {
    alignItems: 'center',
  },
  chip: {
    alignItems: 'center',
    justifyContent: 'center',
  },
});
