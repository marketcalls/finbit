/**
 * Trending symbols and topics, shown while the search box is empty.
 *
 * An empty search screen with nothing but a caret is a dead end: the user has to
 * already know what to look for. These chips turn the blank state into the most
 * useful thing the API can offer, which is what the last 48 hours of news were
 * actually about (CONTRACT.md section 5, GET /api/trending).
 *
 * Symbols and topics are kept in separate groups rather than merged into one
 * cloud. A ticker and a subject read differently and search differently, so
 * mixing them makes the list look arbitrary. Symbols are set in the mono face
 * for the same reason the cards use it: tickers are identifiers, not prose.
 *
 * Chips are visually shorter than 44 points because a stack of 44 point pills
 * eats the screen. hitSlop makes the real target reach the minimum
 * (CONTRACT.md section 10).
 */

import { type ReactElement } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Skeleton } from '@/src/components/StateViews';
import { MIN_TOUCH_TARGET, useTheme } from '@/src/theme';

/** The API caps each list at 12; this is a defence, not a policy. */
const MAX_PER_GROUP = 12;

/** Visible chip height. The remainder of the touch target comes from hitSlop. */
const CHIP_HEIGHT = 34;
const CHIP_SLOP = (MIN_TOUCH_TARGET - CHIP_HEIGHT) / 2;

/** Placeholder chip widths, varied so the loading state does not look ruled. */
const SKELETON_WIDTHS = [72, 96, 64, 110, 84, 68] as const;

export interface TrendingChipsProps {
  /** Ticker strings, for example RELIANCE or NIFTY. */
  symbols: string[];
  /** Subject strings, for example "RBI Policy". */
  topics: string[];
  /** Called with the exact chip text, which becomes the query. */
  onSelect: (term: string) => void;
  /** Renders placeholder chips instead of real ones. */
  loading?: boolean;
}

export function TrendingChips({
  symbols,
  topics,
  onSelect,
  loading = false,
}: TrendingChipsProps): ReactElement | null {
  const { space } = useTheme();

  if (loading) {
    return (
      <View style={{ rowGap: space.lg }}>
        <SkeletonGroup caption="Trending symbols" />
        <SkeletonGroup caption="Trending topics" />
      </View>
    );
  }

  const visibleSymbols = symbols.slice(0, MAX_PER_GROUP);
  const visibleTopics = topics.slice(0, MAX_PER_GROUP);

  if (visibleSymbols.length === 0 && visibleTopics.length === 0) {
    return null;
  }

  return (
    <View style={{ rowGap: space.lg }}>
      {visibleSymbols.length > 0 ? (
        <Group caption="Trending symbols" terms={visibleSymbols} mono onSelect={onSelect} />
      ) : null}
      {visibleTopics.length > 0 ? (
        <Group caption="Trending topics" terms={visibleTopics} onSelect={onSelect} />
      ) : null}
    </View>
  );
}

function Group({
  caption,
  terms,
  mono = false,
  onSelect,
}: {
  caption: string;
  terms: string[];
  mono?: boolean;
  onSelect: (term: string) => void;
}): ReactElement {
  const { space } = useTheme();

  return (
    <View>
      <Caption text={caption} />
      <View style={[styles.wrap, { columnGap: space.sm, rowGap: space.sm, marginTop: space.sm }]}>
        {terms.map((term) => (
          <Chip key={term} term={term} mono={mono} onSelect={onSelect} />
        ))}
      </View>
    </View>
  );
}

function Chip({
  term,
  mono,
  onSelect,
}: {
  term: string;
  mono: boolean;
  onSelect: (term: string) => void;
}): ReactElement {
  const { colors, radii, space, fonts, fontSizes } = useTheme();

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`Search ${term}`}
      hitSlop={CHIP_SLOP}
      onPress={() => onSelect(term)}
      style={({ pressed }) => [
        styles.chip,
        {
          backgroundColor: pressed ? colors.border : colors.muted,
          borderColor: colors.border,
          borderRadius: radii.pill,
          paddingHorizontal: space.md,
        },
      ]}
    >
      <Text
        numberOfLines={1}
        style={{
          color: colors.fg,
          fontFamily: mono ? fonts.mono : fonts.body,
          fontSize: fontSizes.sm,
          fontWeight: mono ? '600' : '500',
        }}
      >
        {term}
      </Text>
    </Pressable>
  );
}

function Caption({ text }: { text: string }): ReactElement {
  const { colors, fonts, fontSizes } = useTheme();

  return (
    <Text
      accessibilityRole="header"
      style={{
        color: colors.mutedFg,
        fontFamily: fonts.body,
        fontSize: fontSizes.xs,
        fontWeight: '600',
        letterSpacing: 0.8,
        textTransform: 'uppercase',
      }}
    >
      {text}
    </Text>
  );
}

function SkeletonGroup({ caption }: { caption: string }): ReactElement {
  const { space, radii } = useTheme();

  return (
    <View>
      <Caption text={caption} />
      <View style={[styles.wrap, { columnGap: space.sm, rowGap: space.sm, marginTop: space.sm }]}>
        {SKELETON_WIDTHS.map((width, index) => (
          <Skeleton
            key={`${width}-${index}`}
            width={width}
            height={CHIP_HEIGHT}
            radius={radii.pill}
          />
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    flexDirection: 'row',
    flexWrap: 'wrap',
  },
  chip: {
    height: CHIP_HEIGHT,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: StyleSheet.hairlineWidth,
  },
});
