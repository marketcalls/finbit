/**
 * The FinBit design tokens for the mobile app.
 *
 * This is the only file in the app that may contain a hex colour. Every screen
 * and component reads colours through useThemeColors(), so a palette change is
 * one edit here rather than a hunt through the tree, and a reviewer can check
 * the rule mechanically: a hex literal anywhere else is a bug.
 *
 * The palette is the phase 1 web palette (CONTRACT_MOBILE_ADMIN.md section 7,
 * originally frontend/src/index.css) copied value for value, so the same story
 * looks the same in a browser and on a phone.
 *
 * Type follows the same rule as the web app, serif headlines over a sans body,
 * but loads no font files: a custom face costs a download before first paint and
 * a splash the user stares at. The platform serif is good enough for this build.
 */

import { Platform } from 'react-native';

/** Which of the two palettes is showing. The preference that chose it is separate. */
export type ColorScheme = 'light' | 'dark';

/**
 * One palette. Names carry meaning rather than appearance, so a token reads the
 * same in both schemes: `bg` is always the page, `bull` is always up.
 */
export interface ColorTokens {
  /** The page behind everything. */
  bg: string;
  /** A card or sheet sitting on the page. */
  card: string;
  /** Primary text and icons. */
  fg: string;
  /** A quiet fill: chips, image placeholders, skeletons. */
  muted: string;
  /** Secondary text: timestamps, captions, source counts. */
  mutedFg: string;
  /** Hairlines and control outlines. */
  border: string;
  /** The one brand colour, used for the active state and primary actions. */
  accent: string;
  /** Text and icons drawn on top of accent. */
  onAccent: string;
  /** The breaking-news flag. Never used for anything else. */
  breaking: string;
  /** Text drawn on top of breaking. */
  onBreaking: string;
  /** Positive sentiment and a bullish impact direction. */
  bull: string;
  /** Negative sentiment and a bearish impact direction. */
  bear: string;
  /** Neutral sentiment and a neutral impact direction. */
  flat: string;
}

export const darkColors: ColorTokens = {
  bg: '#0F172A',
  card: '#111827',
  fg: '#F8FAFC',
  muted: '#1E293B',
  mutedFg: '#CBD5E1',
  border: '#334155',
  accent: '#1E40AF',
  onAccent: '#FFFFFF',
  breaking: '#DC2626',
  onBreaking: '#FFFFFF',
  bull: '#22C55E',
  bear: '#EF4444',
  flat: '#94A3B8',
};

export const lightColors: ColorTokens = {
  bg: '#FFFFFF',
  card: '#FFFFFF',
  fg: '#0F172A',
  muted: '#F1F5F9',
  mutedFg: '#475569',
  border: '#E2E8F0',
  accent: '#1D4ED8',
  onAccent: '#FFFFFF',
  breaking: '#DC2626',
  onBreaking: '#FFFFFF',
  bull: '#16A34A',
  bear: '#DC2626',
  flat: '#64748B',
};

export const palettes: Record<ColorScheme, ColorTokens> = {
  dark: darkColors,
  light: lightColors,
};

/**
 * Font families.
 *
 * 'System' is React Native's name for the platform UI face on iOS; Android wants
 * the family name itself. Web gets a full stack because a bare family name there
 * would fall back to Times.
 */
export const fonts = {
  headline: Platform.select({
    ios: 'Georgia',
    android: 'serif',
    default: 'Georgia, "Times New Roman", serif',
  }) as string,
  body: Platform.select({
    ios: 'System',
    android: 'sans-serif',
    default: 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
  }) as string,
  /** Tickers and scores, so digits line up in a column. */
  mono: Platform.select({
    ios: 'Menlo',
    android: 'monospace',
    default: 'ui-monospace, SFMono-Regular, Menlo, monospace',
  }) as string,
} as const;

/** Spacing scale in points. Four is the unit; nothing lands off the grid. */
export const space = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
} as const;

export const radii = {
  sm: 6,
  md: 10,
  lg: 16,
  /** Anything larger than the element, which rounds a chip into a pill. */
  pill: 999,
} as const;

export const fontSizes = {
  xs: 11,
  sm: 13,
  md: 15,
  lg: 17,
  xl: 21,
  xxl: 26,
} as const;

export const lineHeights = {
  xs: 16,
  sm: 18,
  md: 22,
  lg: 24,
  xl: 28,
  xxl: 32,
} as const;

/**
 * The minimum tappable square, in points. The web contract fixes this at 44 and
 * both platform guidelines agree, so controls that look smaller still need a
 * hitSlop or padding that reaches this.
 */
export const MIN_TOUCH_TARGET = 44;

/** Everything a screen needs, in one object, as handed out by useTheme(). */
export interface ThemeTokens {
  scheme: ColorScheme;
  colors: ColorTokens;
  fonts: typeof fonts;
  space: typeof space;
  radii: typeof radii;
  fontSizes: typeof fontSizes;
  lineHeights: typeof lineHeights;
}

export function themeTokens(scheme: ColorScheme): ThemeTokens {
  return {
    scheme,
    colors: palettes[scheme],
    fonts,
    space,
    radii,
    fontSizes,
    lineHeights,
  };
}
