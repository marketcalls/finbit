/**
 * The search field.
 *
 * This is a component rather than a bare TextInput inside the screen because two
 * details are easy to get wrong and invisible until someone uses the app with
 * one hand. The clear control has to be a real button with a label and a 44
 * point target, which is a dozen lines that would otherwise sit in the middle of
 * the screen's data flow; and clearing has to return focus to the field, or the
 * keyboard collapses, the list jumps, and starting a second query costs another
 * tap.
 *
 * The value prop updates on every keystroke. Only the request is debounced, not
 * the text: a field that lags behind the typing feels broken, and the screen is
 * the right place to decide when a query is worth sending.
 *
 * The platform's own clear affordance is drawn instead of used. iOS has
 * clearButtonMode and Android has nothing, so relying on it would give the two
 * platforms different controls and neither would carry a label.
 */

import { useRef, type ReactElement } from 'react';
import { Pressable, StyleSheet, TextInput, View } from 'react-native';
import Svg, { Circle, Line } from 'react-native-svg';

import { MIN_TOUCH_TARGET, useTheme } from '@/src/theme';

/** The glyph box. The button around it is what carries the touch target. */
const ICON_SIZE = 18;

/** The clear button's visible square. hitSlop takes the real target to 44. */
const CLEAR_SIZE = 32;
const CLEAR_SLOP = (MIN_TOUCH_TARGET - CLEAR_SIZE) / 2;

export interface SearchInputProps {
  value: string;
  onChangeText: (next: string) => void;
  /**
   * Fired by the keyboard's search key. The debounced result is usually already
   * on screen by then, so this is mostly a way to dismiss the keyboard.
   */
  onSubmit?: () => void;
  placeholder?: string;
  autoFocus?: boolean;
  testID?: string;
}

export function SearchInput({
  value,
  onChangeText,
  onSubmit,
  placeholder = 'Search news, symbols, topics…',
  autoFocus = false,
  testID,
}: SearchInputProps): ReactElement {
  const { colors, radii, space, fonts, fontSizes } = useTheme();
  const inputRef = useRef<TextInput>(null);

  const hasText = value !== '';

  return (
    <View
      testID={testID}
      style={[
        styles.field,
        {
          backgroundColor: colors.muted,
          borderColor: colors.border,
          borderRadius: radii.md,
          paddingLeft: space.md,
          paddingRight: hasText ? space.xs : space.md,
          columnGap: space.sm,
        },
      ]}
    >
      <View accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
        <Svg width={ICON_SIZE} height={ICON_SIZE} viewBox="0 0 24 24" fill="none">
          <Circle cx={11} cy={11} r={7} stroke={colors.mutedFg} strokeWidth={2} />
          <Line
            x1={16.2}
            y1={16.2}
            x2={21}
            y2={21}
            stroke={colors.mutedFg}
            strokeWidth={2}
            strokeLinecap="round"
          />
        </Svg>
      </View>

      <TextInput
        ref={inputRef}
        value={value}
        onChangeText={onChangeText}
        onSubmitEditing={onSubmit}
        placeholder={placeholder}
        placeholderTextColor={colors.mutedFg}
        selectionColor={colors.accent}
        accessibilityLabel="Search news"
        autoCapitalize="none"
        autoCorrect={false}
        autoFocus={autoFocus}
        spellCheck={false}
        returnKeyType="search"
        clearButtonMode="never"
        underlineColorAndroid="transparent"
        style={[
          styles.input,
          {
            color: colors.fg,
            fontFamily: fonts.body,
            fontSize: fontSizes.md,
          },
        ]}
      />

      {hasText ? (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Clear search"
          hitSlop={CLEAR_SLOP}
          onPress={() => {
            onChangeText('');
            // Keeps the keyboard up so the next query starts immediately.
            inputRef.current?.focus();
          }}
          style={({ pressed }) => [styles.clear, { opacity: pressed ? 0.6 : 1 }]}
        >
          <Svg width={22} height={22} viewBox="0 0 24 24" fill="none">
            <Circle cx={12} cy={12} r={11} fill={colors.border} />
            <Line
              x1={8.5}
              y1={8.5}
              x2={15.5}
              y2={15.5}
              stroke={colors.mutedFg}
              strokeWidth={2}
              strokeLinecap="round"
            />
            <Line
              x1={15.5}
              y1={8.5}
              x2={8.5}
              y2={15.5}
              stroke={colors.mutedFg}
              strokeWidth={2}
              strokeLinecap="round"
            />
          </Svg>
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  field: {
    flexDirection: 'row',
    alignItems: 'center',
    borderWidth: StyleSheet.hairlineWidth,
    minHeight: MIN_TOUCH_TARGET,
  },
  input: {
    flex: 1,
    // Android adds its own vertical padding, which would make the field taller
    // than the 44 point box the row is built around.
    paddingVertical: 0,
  },
  clear: {
    width: CLEAR_SIZE,
    height: CLEAR_SIZE,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
