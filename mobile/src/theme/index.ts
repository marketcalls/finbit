/**
 * The theme barrel, so a screen imports one path instead of three.
 *
 * Everything the app needs to draw itself lives behind '@/src/theme': the raw
 * tokens, the gluestack config that app/_layout.tsx installs, and the hooks that
 * read the active scheme.
 */

export * from './tokens';
export { finbitGluestackConfig } from './config';
export { ThemeProvider, useTheme, useThemeColors, THEME_STORAGE_KEY } from './useTheme';
export type { ThemePreference, ThemeState } from './useTheme';
