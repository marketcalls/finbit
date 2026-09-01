/**
 * The themed page wrapper every screen sits inside.
 *
 * It exists so no screen has to remember two things that are easy to get wrong
 * and invisible until someone runs the app on the wrong device: the background
 * must come from the palette (a transparent root shows white behind a dark
 * theme during a navigation transition), and the safe area must be applied per
 * edge. Bottom is left alone by default, because a tab bar already owns that
 * inset and adding it twice leaves a dead band above the tabs.
 */

import { type ReactElement, type ReactNode } from 'react';
import {
  ScrollView,
  StyleSheet,
  View,
  type RefreshControlProps,
  type StyleProp,
  type ViewStyle,
} from 'react-native';
import { SafeAreaView, type Edge } from 'react-native-safe-area-context';

import { useTheme } from '@/src/theme';

export interface ScreenProps {
  children: ReactNode;
  /** Safe area edges to pad. Defaults to the top only. */
  edges?: readonly Edge[];
  /** Wraps the children in a ScrollView. Lists bring their own scrolling. */
  scroll?: boolean;
  /** Adds the standard horizontal gutter. */
  padded?: boolean;
  /** Centres the children on both axes, for a loading or empty page. */
  center?: boolean;
  /** 'bg' is the page, 'card' is a sheet-like screen such as an article. */
  background?: 'bg' | 'card';
  /** Pull to refresh, forwarded to the ScrollView when scroll is set. */
  refreshControl?: ReactElement<RefreshControlProps>;
  style?: StyleProp<ViewStyle>;
  contentContainerStyle?: StyleProp<ViewStyle>;
  testID?: string;
}

const DEFAULT_EDGES: readonly Edge[] = ['top'];

export function Screen({
  children,
  edges = DEFAULT_EDGES,
  scroll = false,
  padded = false,
  center = false,
  background = 'bg',
  refreshControl,
  style,
  contentContainerStyle,
  testID,
}: ScreenProps): ReactElement {
  const { colors, space } = useTheme();

  const surface = background === 'card' ? colors.card : colors.bg;
  const gutter = padded ? { paddingHorizontal: space.lg } : null;
  const centred = center
    ? { flexGrow: 1, alignItems: 'center' as const, justifyContent: 'center' as const }
    : null;

  return (
    <SafeAreaView
      edges={edges}
      style={[styles.root, { backgroundColor: surface }, style]}
      testID={testID}
    >
      {scroll ? (
        <ScrollView
          style={styles.fill}
          contentContainerStyle={[styles.content, gutter, centred, contentContainerStyle]}
          refreshControl={refreshControl}
          keyboardShouldPersistTaps="handled"
        >
          {children}
        </ScrollView>
      ) : (
        <View style={[styles.fill, gutter, center ? styles.centred : null, contentContainerStyle]}>
          {children}
        </View>
      )}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
  },
  fill: {
    flex: 1,
  },
  content: {
    flexGrow: 1,
  },
  centred: {
    alignItems: 'center',
    justifyContent: 'center',
  },
});
