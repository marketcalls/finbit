/**
 * Inline SVG icon set, contract section 11. No icon library, no emoji.
 * Every icon is decorative: it renders aria-hidden and focusable="false", so
 * any icon-only control around it must carry its own aria-label.
 */

import type { ReactNode } from 'react';

export interface IconProps {
  className?: string;
}

const DEFAULT_SIZE = 'h-5 w-5';

function Icon({
  className,
  fill = 'none',
  children,
}: {
  className?: string;
  fill?: string;
  children: ReactNode;
}): JSX.Element {
  return (
    <svg
      className={className ?? DEFAULT_SIZE}
      viewBox="0 0 24 24"
      fill={fill}
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  );
}

/** Feed tab: a folded newspaper. */
export function IconFeed({ className }: IconProps): JSX.Element {
  return (
    <Icon className={className}>
      <path d="M16 20H6a2 2 0 0 1-2-2V5a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v13a2 2 0 0 0 4 0V9a1 1 0 0 0-1-1h-3" />
      <path d="M8 8h5" />
      <path d="M8 12h5" />
      <path d="M8 16h3" />
    </Icon>
  );
}

/** Search tab and the search input affordance. */
export function IconSearch({ className }: IconProps): JSX.Element {
  return (
    <Icon className={className}>
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.6-3.6" />
    </Icon>
  );
}

/** Not saved. */
export function IconBookmark({ className }: IconProps): JSX.Element {
  return (
    <Icon className={className}>
      <path d="M6 4.75A.75.75 0 0 1 6.75 4h10.5a.75.75 0 0 1 .75.75V20l-6-3.5L6 20V4.75Z" />
    </Icon>
  );
}

/** Saved. */
export function IconBookmarkFilled({ className }: IconProps): JSX.Element {
  return (
    <Icon className={className} fill="currentColor">
      <path d="M6 4.75A.75.75 0 0 1 6.75 4h10.5a.75.75 0 0 1 .75.75V20l-6-3.5L6 20V4.75Z" />
    </Icon>
  );
}

/** Header refresh action. */
export function IconRefresh({ className }: IconProps): JSX.Element {
  return (
    <Icon className={className}>
      <path d="M21 12a9 9 0 0 0-9-9 9 9 0 0 0-6.36 2.64L3 8" />
      <path d="M3 3v5h5" />
      <path d="M3 12a9 9 0 0 0 9 9 9 9 0 0 0 6.36-2.64L21 16" />
      <path d="M21 21v-5h-5" />
    </Icon>
  );
}

/** Dismiss a sheet or clear an input. */
export function IconClose({ className }: IconProps): JSX.Element {
  return (
    <Icon className={className}>
      <path d="m6 6 12 12" />
      <path d="M18 6 6 18" />
    </Icon>
  );
}

/** Link that opens the original publisher. */
export function IconExternal({ className }: IconProps): JSX.Element {
  return (
    <Icon className={className}>
      <path d="M14 4h6v6" />
      <path d="M20 4 11 13" />
      <path d="M18 13.5V18a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4.5" />
    </Icon>
  );
}

/** Light theme. */
export function IconSun({ className }: IconProps): JSX.Element {
  return (
    <Icon className={className}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2" />
      <path d="M12 20v2" />
      <path d="m4.93 4.93 1.41 1.41" />
      <path d="m17.66 17.66 1.41 1.41" />
      <path d="M2 12h2" />
      <path d="M20 12h2" />
      <path d="m4.93 19.07 1.41-1.41" />
      <path d="m17.66 6.34 1.41-1.41" />
    </Icon>
  );
}

/** Dark theme. */
export function IconMoon({ className }: IconProps): JSX.Element {
  return (
    <Icon className={className}>
      <path d="M20.5 14.3A8.5 8.5 0 0 1 9.7 3.5a8.5 8.5 0 1 0 10.8 10.8Z" />
    </Icon>
  );
}

/** Row affordance, for example a source link. */
export function IconChevronRight({ className }: IconProps): JSX.Element {
  return (
    <Icon className={className}>
      <path d="m9 5 7 7-7 7" />
    </Icon>
  );
}

/** Breaking news flag and error states. */
export function IconAlert({ className }: IconProps): JSX.Element {
  return (
    <Icon className={className}>
      <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z" />
      <path d="M12 9v4" />
      <path d="M12 17h.01" />
    </Icon>
  );
}

/** Bullish market impact. */
export function IconTrendUp({ className }: IconProps): JSX.Element {
  return (
    <Icon className={className}>
      <path d="M22 7 13.5 15.5 8.5 10.5 2 17" />
      <path d="M16 7h6v6" />
    </Icon>
  );
}

/** Bearish market impact. */
export function IconTrendDown({ className }: IconProps): JSX.Element {
  return (
    <Icon className={className}>
      <path d="M22 17 13.5 8.5 8.5 13.5 2 7" />
      <path d="M16 17h6v-6" />
    </Icon>
  );
}

/** Neutral market impact. */
export function IconTrendFlat({ className }: IconProps): JSX.Element {
  return (
    <Icon className={className}>
      <path d="M4 12h13" />
      <path d="m15 8 4 4-4 4" />
    </Icon>
  );
}
