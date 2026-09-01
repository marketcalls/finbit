/**
 * The two pieces the Settings screen is built from: a titled group and a row
 * inside it.
 *
 * Settings is the one screen where the layout is the information. A reader
 * scanning it should be able to tell at a glance which lines are choices, which
 * are facts, and which belong together, so the grouping is a component rather
 * than repeated markup that slowly drifts apart.
 *
 * Two rules are enforced here rather than left to the screen:
 *
 *   - A row with no onPress renders as a View, never a Pressable. A read-only
 *     fact that looks and announces like a button is a small lie that costs a
 *     screen reader user a tap to discover.
 *   - A row that is one of several options announces as a radio with its checked
 *     state, so the theme picker is navigable without seeing the check mark.
 *
 * The hairline between rows is drawn by the section, not by the row, because
 * only the section knows which row is last and a trailing hairline sitting on
 * the group's own border is the classic settings-screen blemish.
 */

import { Children, Fragment, type ReactElement, type ReactNode } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import Svg, { Path } from 'react-native-svg';

import { MIN_TOUCH_TARGET, useTheme } from '@/src/theme';

/** Rows are taller than the minimum target so a two-line row still breathes. */
const ROW_MIN_HEIGHT = 52;

export interface SettingsSectionProps {
  /** The group caption, set in small caps above the card. */
  title: string;
  /** A sentence under the card, for a caveat that is not part of any one row. */
  footer?: string;
  children: ReactNode;
}

export function SettingsSection({ title, footer, children }: SettingsSectionProps): ReactElement {
  const { colors, radii, space, fonts, fontSizes, lineHeights } = useTheme();

  // Children.toArray drops null and false, so a conditionally rendered row (the
  // development-only API row) leaves no hairline behind where it would have been.
  const rows = Children.toArray(children);

  return (
    <View style={{ marginTop: space.xl }}>
      <Text
        accessibilityRole="header"
        style={{
          color: colors.mutedFg,
          fontFamily: fonts.body,
          fontSize: fontSizes.xs,
          fontWeight: '600',
          letterSpacing: 0.8,
          marginBottom: space.sm,
          textTransform: 'uppercase',
        }}
      >
        {title}
      </Text>

      <View
        style={[
          styles.card,
          {
            backgroundColor: colors.card,
            borderColor: colors.border,
            borderRadius: radii.md,
          },
        ]}
      >
        {rows.map((row, index) => (
          <Fragment key={index}>
            {index === 0 ? null : (
              <View
                style={[
                  styles.hairline,
                  { backgroundColor: colors.border, marginLeft: space.lg },
                ]}
              />
            )}
            {row}
          </Fragment>
        ))}
      </View>

      {footer === undefined ? null : (
        <Text
          style={{
            color: colors.mutedFg,
            fontFamily: fonts.body,
            fontSize: fontSizes.sm,
            lineHeight: lineHeights.sm,
            marginTop: space.sm,
          }}
        >
          {footer}
        </Text>
      )}
    </View>
  );
}

export interface SettingsRowProps {
  label: string;
  /** The right-hand fact, for example an app version. */
  value?: string;
  /** A sentence under the label, for anything the label cannot say in a word. */
  description?: string;
  /** Makes the row a button. Leave it out for a read-only row. */
  onPress?: () => void;
  /**
   * Present makes the row one option of a group: it announces as a radio and
   * draws the check mark when true.
   */
  selected?: boolean;
  /** Sets the value in the mono face, for ids, URLs and anything copied. */
  monoValue?: boolean;
  /**
   * Lets the value be selected and copied by long press. Used for the support
   * values a user has to relay to someone else.
   */
  selectableValue?: boolean;
  /** Puts the value on its own line, for a value too long to sit beside the label. */
  stackValue?: boolean;
  testID?: string;
}

export function SettingsRow({
  label,
  value,
  description,
  onPress,
  selected,
  monoValue = false,
  selectableValue = false,
  stackValue = false,
  testID,
}: SettingsRowProps): ReactElement {
  const { colors, space, fonts, fontSizes, lineHeights } = useTheme();

  const valueText =
    value === undefined ? null : (
      <Text
        selectable={selectableValue}
        numberOfLines={stackValue ? 2 : 1}
        style={{
          color: colors.mutedFg,
          fontFamily: monoValue ? fonts.mono : fonts.body,
          fontSize: monoValue ? fontSizes.sm : fontSizes.md,
          marginTop: stackValue ? space.xs : 0,
          textAlign: stackValue ? 'left' : 'right',
        }}
      >
        {value}
      </Text>
    );

  const body = (
    <View style={styles.text}>
      <Text
        style={{
          color: colors.fg,
          fontFamily: fonts.body,
          fontSize: fontSizes.md,
        }}
      >
        {label}
      </Text>
      {description === undefined ? null : (
        <Text
          style={{
            color: colors.mutedFg,
            fontFamily: fonts.body,
            fontSize: fontSizes.sm,
            lineHeight: lineHeights.sm,
            marginTop: space.xs,
          }}
        >
          {description}
        </Text>
      )}
      {stackValue ? valueText : null}
    </View>
  );

  const trailing = (
    <>
      {stackValue ? null : valueText}
      {selected === true ? <CheckMark /> : null}
    </>
  );

  const content = (
    <View style={[styles.inner, { paddingHorizontal: space.lg, paddingVertical: space.md, columnGap: space.md }]}>
      {body}
      <View style={[styles.trailing, { columnGap: space.sm }]}>{trailing}</View>
    </View>
  );

  if (onPress === undefined) {
    return (
      <View testID={testID} style={styles.row}>
        {content}
      </View>
    );
  }

  return (
    <Pressable
      testID={testID}
      accessibilityRole={selected === undefined ? 'button' : 'radio'}
      accessibilityLabel={label}
      accessibilityState={selected === undefined ? undefined : { selected, checked: selected }}
      onPress={onPress}
      style={({ pressed }) => [styles.row, { backgroundColor: pressed ? colors.muted : colors.card }]}
    >
      {content}
    </Pressable>
  );
}

/** The tick beside the chosen option. Decorative: the radio state says it too. */
function CheckMark(): ReactElement {
  const { colors } = useTheme();

  return (
    <View accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
      <Svg width={20} height={20} viewBox="0 0 24 24" fill="none">
        <Path
          d="M5 12.5 L10 17.5 L19 6.5"
          stroke={colors.accent}
          strokeWidth={2.5}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </Svg>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    borderWidth: StyleSheet.hairlineWidth,
    overflow: 'hidden',
  },
  hairline: {
    height: StyleSheet.hairlineWidth,
  },
  row: {
    minHeight: Math.max(ROW_MIN_HEIGHT, MIN_TOUCH_TARGET),
  },
  inner: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    minHeight: Math.max(ROW_MIN_HEIGHT, MIN_TOUCH_TARGET),
  },
  text: {
    flex: 1,
  },
  trailing: {
    flexDirection: 'row',
    alignItems: 'center',
    flexShrink: 0,
    maxWidth: '45%',
  },
});
