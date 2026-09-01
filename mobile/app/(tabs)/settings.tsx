/**
 * Settings.
 *
 * FinBit has no account, so this screen is not a profile. It holds the one real
 * preference the app has, plus the two facts a user needs when something goes
 * wrong and they have to describe their install to someone else.
 *
 * The device id is shown as a fragment, never in full. It is the credential the
 * API keys bookmarks on (CONTRACT_MOBILE_ADMIN.md section 3.3), and a full id in
 * a screenshot or a support thread is a handle on someone's saved stories. The
 * fragment is enough to match a row in the devices table and useless on its own.
 *
 * The API base URL is a development-only row. In a release build the address is
 * fixed and showing it teaches the user nothing, while in development it is the
 * first thing to check when the app cannot reach the backend on a new network
 * (CONTRACT_MOBILE_ADMIN.md sections 8.1 and 8.2).
 *
 * There is no admin control, no login and no account section here, and none may
 * be added: the admin surface is the web app.
 */

import Constants from 'expo-constants';
import { type ReactElement } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { API_BASE_URL } from '@/src/api/client';
import { Screen } from '@/src/components/Screen';
import { SettingsRow, SettingsSection } from '@/src/components/SettingsRow';
import { shortDeviceId } from '@/src/lib/format';
import { useDeviceAuth } from '@/src/store/DeviceAuthProvider';
import { useTheme, type ThemePreference } from '@/src/theme';

/** How much of the device id is shown. Enough to match a row, not to use one. */
const DEVICE_ID_CHARS = 8;

/** The three values useTheme().preference accepts, in the order they read. */
const THEME_OPTIONS: ReadonlyArray<{ value: ThemePreference; label: string }> = [
  { value: 'system', label: 'System' },
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
];

/**
 * CONTRACT_MOBILE_ADMIN.md section 8.1 requires this sentence, word for word.
 * The impact and sentiment fields are model output, and a trader reading them
 * has to know that before acting on one.
 */
const AI_DISCLAIMER = 'Impact and sentiment are AI assessments, not investment advice.';

export default function SettingsScreen(): ReactElement {
  const { colors, radii, space, fonts, fontSizes, lineHeights, preference, setPreference } =
    useTheme();
  const { deviceId } = useDeviceAuth();

  const version = Constants.expoConfig?.version ?? null;

  return (
    <Screen scroll padded>
      <Text
        accessibilityRole="header"
        style={{
          color: colors.fg,
          fontFamily: fonts.headline,
          fontSize: fontSizes.xxl,
          lineHeight: lineHeights.xxl,
          marginTop: space.sm,
        }}
      >
        Settings
      </Text>

      <SettingsSection
        title="Appearance"
        footer="System follows your phone, so the app changes with it at sunset."
      >
        {THEME_OPTIONS.map((option) => (
          <SettingsRow
            key={option.value}
            label={option.label}
            selected={preference === option.value}
            onPress={() => setPreference(option.value)}
            testID={`theme-${option.value}`}
          />
        ))}
      </SettingsSection>

      <SettingsSection
        title="Support"
        footer="FinBit has no accounts. Your saved stories belong to this device, so there is nothing to sign in to and nothing to sign out of."
      >
        <SettingsRow
          label="Device"
          description="Quote this if you ever need to ask about your saved stories."
          value={deviceId === null ? 'Not registered' : shortDeviceId(deviceId, DEVICE_ID_CHARS)}
          monoValue
          selectableValue
          testID="device-id"
        />
      </SettingsSection>

      {__DEV__ ? (
        <SettingsSection
          title="Development"
          footer="Shown in development builds only. Set EXPO_PUBLIC_API_URL to override it."
        >
          <SettingsRow
            label="API base URL"
            value={API_BASE_URL}
            monoValue
            selectableValue
            stackValue
            testID="api-base-url"
          />
        </SettingsSection>
      ) : null}

      <SettingsSection title="About">
        <SettingsRow label="FinBit" value={version ?? 'Development build'} />
        <SettingsRow
          label="News"
          description="Stories are grouped from several publishers, so one card can carry more than one source."
        />
      </SettingsSection>

      <View
        style={[
          styles.disclaimer,
          {
            backgroundColor: colors.muted,
            borderColor: colors.border,
            borderRadius: radii.md,
            marginTop: space.lg,
            padding: space.lg,
          },
        ]}
      >
        <Text
          style={{
            color: colors.mutedFg,
            fontFamily: fonts.body,
            fontSize: fontSizes.sm,
            lineHeight: lineHeights.sm,
          }}
        >
          {AI_DISCLAIMER}
        </Text>
      </View>

      <View style={{ height: space.xxl }} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  disclaimer: {
    borderWidth: StyleSheet.hairlineWidth,
  },
});
