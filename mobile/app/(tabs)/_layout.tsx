/**
 * The bottom tab bar: Feed, Search, Saved, Settings.
 *
 * Four destinations, always visible, no hamburger and no drawer. The app has
 * exactly four places to be and a tab bar says so at a glance, which is the
 * whole reason a native newsreader feels different from the same feed in a
 * browser.
 *
 * The icons are inline react-native-svg paths rather than an icon font or an
 * icon package. CONTRACT.md section 10 rules out an icon dependency, and four
 * glyphs are not worth one: a font would add a download, a flash of missing
 * glyphs on first paint, and a second place where a colour could come from.
 * Each glyph fills when its tab is active, so the selected tab is carried by
 * shape as well as by colour.
 *
 * Safe area handling belongs to the navigator. React Navigation already lifts
 * the bar above the home indicator, and adding a second inset here would leave a
 * dead band under the icons on a phone with a gesture bar.
 *
 * There is no header. Each screen draws its own chrome, because the feed's is a
 * filter strip rather than a title.
 */

import { Tabs } from 'expo-router';
import { type ReactElement } from 'react';
import { StyleSheet } from 'react-native';
import Svg, { Circle, Path } from 'react-native-svg';

import { useTheme } from '@/src/theme';

const STROKE = 1.9;

interface GlyphProps {
  color: string;
  size: number;
  focused: boolean;
}

/**
 * Stacked story lines, the shape of the card list the tab leads to. When the tab
 * is active the plate fills and the lines are knocked out in the bar's own
 * colour, so the glyph stays legible instead of collapsing into a solid block.
 */
function FeedGlyph({ color, size, focused, knockout }: GlyphProps & { knockout: string }): ReactElement {
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24" fill="none">
      <Path
        d="M4 4h16a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z"
        stroke={color}
        strokeWidth={STROKE}
        strokeLinejoin="round"
        fill={focused ? color : 'none'}
      />
      <Path
        d="M7 9h10M7 13h10M7 17h6"
        stroke={focused ? knockout : color}
        strokeWidth={STROKE}
        strokeLinecap="round"
      />
    </Svg>
  );
}

function SearchGlyph({ color, size, focused }: GlyphProps): ReactElement {
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24" fill="none">
      <Circle
        cx={11}
        cy={11}
        r={7}
        stroke={color}
        strokeWidth={STROKE}
        fill={focused ? color : 'none'}
      />
      <Path d="M16.5 16.5L21 21" stroke={color} strokeWidth={STROKE} strokeLinecap="round" />
    </Svg>
  );
}

function SavedGlyph({ color, size, focused }: GlyphProps): ReactElement {
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24" fill="none">
      <Path
        d="M6 4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v17l-6-4l-6 4V4z"
        stroke={color}
        strokeWidth={STROKE}
        strokeLinejoin="round"
        fill={focused ? color : 'none'}
      />
    </Svg>
  );
}

/** Sliders rather than a cog: this screen is preferences, not machinery. */
function SettingsGlyph({ color, size, focused }: GlyphProps): ReactElement {
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24" fill="none">
      <Path
        d="M4 8h5M15 8h5M4 16h3M13 16h7"
        stroke={color}
        strokeWidth={STROKE}
        strokeLinecap="round"
      />
      <Circle
        cx={12}
        cy={8}
        r={2.6}
        stroke={color}
        strokeWidth={STROKE}
        fill={focused ? color : 'none'}
      />
      <Circle
        cx={10}
        cy={16}
        r={2.6}
        stroke={color}
        strokeWidth={STROKE}
        fill={focused ? color : 'none'}
      />
    </Svg>
  );
}

export default function TabsLayout(): ReactElement {
  const { colors, fonts, fontSizes } = useTheme();

  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: colors.accent,
        tabBarInactiveTintColor: colors.mutedFg,
        tabBarStyle: {
          backgroundColor: colors.card,
          borderTopColor: colors.border,
          borderTopWidth: StyleSheet.hairlineWidth,
        },
        tabBarLabelStyle: {
          fontFamily: fonts.body,
          fontSize: fontSizes.xs,
          fontWeight: '600',
        },
        // The search screen owns a text field, and a bar floating on the
        // keyboard would sit on top of the results it is meant to sit under.
        tabBarHideOnKeyboard: true,
        sceneStyle: { backgroundColor: colors.bg },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: 'Feed',
          tabBarAccessibilityLabel: 'Feed, the latest stories',
          tabBarIcon: (props) => <FeedGlyph {...props} knockout={colors.card} />,
        }}
      />
      <Tabs.Screen
        name="search"
        options={{
          title: 'Search',
          tabBarAccessibilityLabel: 'Search stories',
          tabBarIcon: (props) => <SearchGlyph {...props} />,
        }}
      />
      <Tabs.Screen
        name="saved"
        options={{
          title: 'Saved',
          tabBarAccessibilityLabel: 'Saved stories',
          tabBarIcon: (props) => <SavedGlyph {...props} />,
        }}
      />
      <Tabs.Screen
        name="settings"
        options={{
          title: 'Settings',
          tabBarAccessibilityLabel: 'Settings',
          tabBarIcon: (props) => <SettingsGlyph {...props} />,
        }}
      />
    </Tabs>
  );
}
