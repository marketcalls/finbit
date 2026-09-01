/**
 * The gluestack-ui v1 config, rebuilt on the FinBit palette.
 *
 * The stock config ships a full Tailwind-style rainbow, and every component that
 * comes out of the library reaches into it by token name ($primary500,
 * $backgroundDark900, $error600 and so on). Restyling components one at a time
 * would leave a stray hue in whichever one nobody looked at, so instead every
 * numbered colour family is regenerated from the tokens in tokens.ts. A gluestack
 * component then renders in FinBit colours by default and a screen never has to
 * pass a colour prop to make a library primitive fit.
 *
 * The ramps are interpolated between existing tokens rather than typed out, so
 * this file introduces no colour of its own: the ends of every ramp are values
 * from tokens.ts, which stays the single source of the palette.
 *
 * Light and dark both live in this one config, because gluestack switches modes
 * through the *Light and *Dark token families rather than by swapping configs.
 * The provider is given the active mode through its colorMode prop, which is what
 * app/_layout.tsx does with the value from useTheme().
 */

import { config as baseConfig } from '@gluestack-ui/config';

import { darkColors, fonts, lightColors } from './tokens';

/** The step names gluestack uses for every colour family, lightest first. */
const STEPS = [0, 50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950] as const;

/**
 * Where a ramp's own colour sits, as an index into STEPS. Index 6 is step 500,
 * which is the resting background of a gluestack Button, so a default button
 * comes out exactly the accent rather than a shade near it.
 */
const ACCENT_STEP_INDEX = 6;

function channel(hex: string, offset: number): number {
  return parseInt(hex.slice(offset, offset + 2), 16);
}

function toHex(value: number): string {
  const clamped = Math.max(0, Math.min(255, Math.round(value)));
  return clamped.toString(16).padStart(2, '0').toUpperCase();
}

/** Linear blend in sRGB. Good enough for a token ramp, and dependency free. */
function mix(from: string, to: string, amount: number): string {
  const r = channel(from, 1) + (channel(to, 1) - channel(from, 1)) * amount;
  const g = channel(from, 3) + (channel(to, 3) - channel(from, 3)) * amount;
  const b = channel(from, 5) + (channel(to, 5) - channel(from, 5)) * amount;
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`;
}

/** A twelve step ramp from one token to another, keyed by gluestack step name. */
function ramp(from: string, to: string): Record<number, string> {
  const out: Record<number, string> = {};
  STEPS.forEach((step, index) => {
    out[step] = mix(from, to, index / (STEPS.length - 1));
  });
  return out;
}

/**
 * A ramp that passes through a colour at a chosen step, so the accent lands
 * exactly on $primary600 instead of somewhere near it.
 */
function rampThrough(from: string, via: string, to: string, viaIndex: number): Record<number, string> {
  const out: Record<number, string> = {};
  STEPS.forEach((step, index) => {
    out[step] =
      index <= viaIndex
        ? mix(from, via, viaIndex === 0 ? 1 : index / viaIndex)
        : mix(via, to, (index - viaIndex) / (STEPS.length - 1 - viaIndex));
  });
  return out;
}

// Light families run from the page colour down to the text colour; dark families
// run the same direction, from the dark scheme's text colour down to its page,
// which is why $textDark0 is bright and $backgroundDark900 is nearly the page.
const lightRamp = ramp(lightColors.bg, lightColors.fg);
const darkRamp = ramp(darkColors.fg, darkColors.bg);
const accentRamp = rampThrough(
  lightColors.onAccent,
  darkColors.accent,
  darkColors.bg,
  ACCENT_STEP_INDEX,
);
const bullRamp = rampThrough(lightColors.onAccent, darkColors.bull, darkColors.bg, ACCENT_STEP_INDEX);
const bearRamp = rampThrough(lightColors.onAccent, darkColors.bear, darkColors.bg, ACCENT_STEP_INDEX);

/** Families that carry hue in the stock theme and would otherwise leak through. */
const NEUTRAL_FAMILIES = [
  'secondary',
  'tertiary',
  'warning',
  'info',
  'rose',
  'pink',
  'fuchsia',
  'purple',
  'violet',
  'indigo',
  'blue',
  'lightBlue',
  'darkBlue',
  'cyan',
  'teal',
  'lime',
  'yellow',
  'amber',
  'orange',
  'warmGray',
  'trueGray',
  'coolGray',
  'blueGray',
];

const FAMILY_RAMPS: Record<string, Record<number, string>> = {
  primary: accentRamp,
  success: bullRamp,
  emerald: bullRamp,
  green: bullRamp,
  error: bearRamp,
  red: bearRamp,
  backgroundLight: lightRamp,
  textLight: lightRamp,
  borderLight: lightRamp,
  backgroundDark: darkRamp,
  textDark: darkRamp,
  borderDark: darkRamp,
};

for (const family of NEUTRAL_FAMILIES) {
  FAMILY_RAMPS[family] = lightRamp;
}

const FAMILY_PATTERN = new RegExp(`^(${Object.keys(FAMILY_RAMPS).join('|')})(\\d+)$`);

function finbitColors(source: Record<string, string>): Record<string, string> {
  const result: Record<string, string> = { ...source };

  for (const token of Object.keys(source)) {
    const match = FAMILY_PATTERN.exec(token);
    if (!match) {
      continue;
    }
    const replacement = FAMILY_RAMPS[match[1] as string]?.[Number(match[2])];
    if (replacement !== undefined) {
      result[token] = replacement;
    }
  }

  result.white = lightColors.bg;
  result.black = darkColors.bg;
  return result;
}

/**
 * The config handed to GluestackUIProvider. Typed loosely on purpose: the stock
 * config is a deep `as const` object and re-deriving its literal type after
 * rewriting every colour buys nothing, since the provider takes it as `any`.
 */
export const finbitGluestackConfig = {
  ...baseConfig,
  tokens: {
    ...baseConfig.tokens,
    colors: finbitColors(baseConfig.tokens.colors as unknown as Record<string, string>),
    fonts: {
      heading: fonts.headline,
      body: fonts.body,
      mono: fonts.mono,
    },
  },
};
