/**
 * shadcn/ui toaster, backed by sonner, on the FinBit palette.
 *
 * Contract section 9 wants a toast on every admin mutation, success or failure.
 * Sonner renders into a live region and stacks toasts itself, which is a lot of
 * behaviour not worth rebuilding.
 *
 * shadcn ships this file wired to next-themes. FinBit has no next-themes, so it
 * reads the app's own theme store instead and hands sonner light or dark. The
 * colours are passed as sonner's CSS custom properties rather than class names
 * so they follow a theme switch without a remount.
 *
 * A closeButton is on by default: an auto-dismissing error message that someone
 * looked away from is a message that was never delivered.
 */

import type * as React from 'react';
import { Toaster as SonnerToaster, toast } from 'sonner';
import type { ToasterProps } from 'sonner';

import { useTheme } from '../../lib/useTheme';

function Toaster({ closeButton = true, richColors = true, ...props }: ToasterProps) {
  const { theme } = useTheme();

  return (
    <SonnerToaster
      theme={theme}
      className="toaster group"
      closeButton={closeButton}
      richColors={richColors}
      style={
        {
          '--normal-bg': 'var(--card)',
          '--normal-text': 'var(--fg)',
          '--normal-border': 'var(--border)',
          '--success-bg': 'var(--card)',
          '--success-text': 'var(--bull)',
          '--success-border': 'var(--border)',
          '--error-bg': 'var(--card)',
          '--error-text': 'var(--bear)',
          '--error-border': 'var(--border)',
          '--warning-bg': 'var(--card)',
          '--warning-text': 'var(--flat)',
          '--warning-border': 'var(--border)',
          '--info-bg': 'var(--card)',
          '--info-text': 'var(--muted-fg)',
          '--info-border': 'var(--border)',
        } as React.CSSProperties
      }
      {...props}
    />
  );
}

export { Toaster, toast };
