/**
 * The root layout: every provider the app needs, in the one order that works.
 *
 * GestureHandlerRootView has to be the outermost view or a swipe handler
 * anywhere below it silently does nothing. ThemeProvider comes next because
 * gluestack needs the resolved colour mode as a prop, and the theme has to be
 * read before the first paint so the app never flashes the wrong palette.
 * DeviceAuthProvider gates everything after it: the config, bookmark and screen
 * layers all assume a signed request will work, and that is only true once the
 * device has registered.
 *
 * The maintenance gate sits above the navigator rather than inside each screen,
 * because CONTRACT_MOBILE_ADMIN.md section 8.1 requires the message on every
 * tab, and one gate cannot be forgotten in a new tab the way four copies can.
 */

import { GluestackUIProvider } from '@gluestack-ui/themed';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { type ReactElement, type ReactNode } from 'react';
import { StyleSheet, View } from 'react-native';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { EmptyState } from '@/src/components/StateViews';
import { BookmarksProvider } from '@/src/store/BookmarksProvider';
import { ConfigProvider, useConfig } from '@/src/store/ConfigProvider';
import { DeviceAuthProvider } from '@/src/store/DeviceAuthProvider';
import { ThemeProvider, finbitGluestackConfig, useTheme } from '@/src/theme';

function MaintenanceGate({ children }: { children: ReactNode }): ReactElement {
  const { colors } = useTheme();
  const { maintenance, maintenanceMessage, refresh } = useConfig();

  if (!maintenance) {
    return <>{children}</>;
  }

  return (
    <View style={[styles.fill, styles.centre, { backgroundColor: colors.bg }]}>
      <EmptyState
        title="FinBit is paused"
        body={maintenanceMessage ?? ''}
        action={{ label: 'Check again', onPress: () => void refresh() }}
      />
    </View>
  );
}

/** Everything that needs the resolved theme, which is everything visible. */
function ThemedApp(): ReactElement {
  const { scheme, colors } = useTheme();

  return (
    <GluestackUIProvider config={finbitGluestackConfig} colorMode={scheme}>
      <SafeAreaProvider>
        <StatusBar style={scheme === 'dark' ? 'light' : 'dark'} />
        <DeviceAuthProvider>
          <ConfigProvider>
            <BookmarksProvider>
              <MaintenanceGate>
                <Stack
                  screenOptions={{
                    headerShown: false,
                    contentStyle: { backgroundColor: colors.bg },
                  }}
                />
              </MaintenanceGate>
            </BookmarksProvider>
          </ConfigProvider>
        </DeviceAuthProvider>
      </SafeAreaProvider>
    </GluestackUIProvider>
  );
}

export default function RootLayout(): ReactElement {
  return (
    <GestureHandlerRootView style={styles.fill}>
      <ThemeProvider>
        <ThemedApp />
      </ThemeProvider>
    </GestureHandlerRootView>
  );
}

const styles = StyleSheet.create({
  fill: {
    flex: 1,
  },
  centre: {
    alignItems: 'center',
    justifyContent: 'center',
  },
});
