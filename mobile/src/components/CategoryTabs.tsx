/**
 * The horizontal category strip above the feed.
 *
 * The list comes from /api/config through ConfigProvider rather than from a
 * local constant, because an admin can switch a category off (contract section
 * 6.6) and a hardcoded strip would keep offering a tab that now returns nothing.
 * The 'all' pseudo-category is already first in that list.
 *
 * Two details that only matter on a phone:
 *
 *   - The strip scrolls itself to the active tab. With ten categories, tapping
 *     "Commodities" and then rotating or returning to the tab would otherwise
 *     leave the selection off screen with no way to tell what is active.
 *   - A pill is 36 pt tall, which is smaller than the 44 pt minimum in
 *     CONTRACT.md section 10, so each carries hitSlop that brings the real
 *     target back to 44. Stacking full-height pills above a full-screen card
 *     would cost the card a tenth of its viewport.
 *
 * Roles are tablist and tab, so a screen reader announces "tab, 3 of 10,
 * selected" instead of reading ten unrelated buttons.
 */

import { useCallback, useRef, type ReactElement } from 'react';
import {
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
  type LayoutChangeEvent,
  type StyleProp,
  type ViewStyle,
} from 'react-native';

import { type ConfigCategory, type FeedCategory } from '@/src/lib/types';
import { MIN_TOUCH_TARGET, useTheme } from '@/src/theme';

const PILL_HEIGHT = 36;

/** Half of what each side must gain to reach the minimum tappable square. */
const SLOP = Math.round((MIN_TOUCH_TARGET - PILL_HEIGHT) / 2);

export interface CategoryTabsProps {
  /** Enabled categories, 'all' first, exactly as ConfigProvider hands them over. */
  categories: ConfigCategory[];
  value: FeedCategory;
  onChange: (next: FeedCategory) => void;
  style?: StyleProp<ViewStyle>;
}

export function CategoryTabs({
  categories,
  value,
  onChange,
  style,
}: CategoryTabsProps): ReactElement | null {
  const { colors, radii, space, fonts, fontSizes } = useTheme();

  const scroller = useRef<ScrollView | null>(null);
  // Where each pill starts, filled in as the strip lays out. A ref rather than
  // state: these values are only read when a tab is chosen, and storing them in
  // state would re-render the strip once per pill on first paint.
  const offsets = useRef<Record<string, number>>({});

  const remember = useCallback((key: string, event: LayoutChangeEvent) => {
    offsets.current[key] = event.nativeEvent.layout.x;
  }, []);

  const select = useCallback(
    (next: FeedCategory) => {
      const x = offsets.current[next];
      if (x !== undefined) {
        // Leaves a gutter to the left so the chosen pill does not sit flush
        // against the edge and look clipped.
        scroller.current?.scrollTo({ x: Math.max(0, x - space.lg), animated: true });
      }
      if (next !== value) {
        onChange(next);
      }
    },
    [onChange, space.lg, value],
  );

  if (categories.length === 0) {
    return null;
  }

  return (
    <View style={style}>
      <ScrollView
        ref={scroller}
        horizontal
        showsHorizontalScrollIndicator={false}
        accessibilityRole="tablist"
        contentContainerStyle={[
          styles.strip,
          { paddingHorizontal: space.lg, columnGap: space.sm },
        ]}
      >
        {categories.map((category) => {
          const selected = category.key === value;

          return (
            <Pressable
              key={category.key}
              accessibilityRole="tab"
              accessibilityState={{ selected }}
              accessibilityLabel={`${category.label} stories`}
              hitSlop={{ top: SLOP, bottom: SLOP }}
              onLayout={(event) => remember(category.key, event)}
              onPress={() => select(category.key)}
              style={({ pressed }) => [
                styles.pill,
                {
                  borderRadius: radii.pill,
                  paddingHorizontal: space.lg,
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
                {category.label}
              </Text>
            </Pressable>
          );
        })}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  strip: {
    alignItems: 'center',
  },
  pill: {
    height: PILL_HEIGHT,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: StyleSheet.hairlineWidth,
  },
});
