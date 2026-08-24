/**
 * Display formatting helpers. The API always sends ISO 8601 UTC timestamps with
 * a trailing Z, contract section 3, and the frontend does all humanising.
 */

const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'] as const;
const MONTHS = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
] as const;

const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;
const WEEK_MS = 7 * DAY_MS;

function pad2(value: number): string {
  return value < 10 ? `0${value}` : String(value);
}

function clock(date: Date): string {
  return `${pad2(date.getHours())}:${pad2(date.getMinutes())}`;
}

/**
 * Parses an API timestamp into a Date in the browser's local timezone.
 * A timestamp with no timezone marker is read as UTC, which is what the API sends.
 * Returns null when the value is missing or unparsable.
 */
export function parseTimestamp(value: string | null | undefined): Date | null {
  if (!value) {
    return null;
  }
  const trimmed = value.trim();
  if (trimmed === '') {
    return null;
  }
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(trimmed);
  const normalised = hasZone ? trimmed : `${trimmed.replace(' ', 'T')}Z`;
  const date = new Date(normalised);
  return Number.isNaN(date.getTime()) ? null : date;
}

/**
 * Short relative age, for example "just now", "8 min ago", "2 h ago",
 * "Mon 14:05" within the last week, then "14 Aug" or "14 Aug 2025".
 * Future timestamps, which can happen when a publisher clock runs fast, are
 * clamped to "just now". Returns an empty string for an unusable value.
 */
export function relativeTime(value: string | null | undefined, now: Date = new Date()): string {
  const date = parseTimestamp(value);
  if (!date) {
    return '';
  }

  const elapsed = Math.max(0, now.getTime() - date.getTime());

  if (elapsed < MINUTE_MS) {
    return 'just now';
  }
  if (elapsed < HOUR_MS) {
    return `${Math.floor(elapsed / MINUTE_MS)} min ago`;
  }
  if (elapsed < DAY_MS) {
    return `${Math.floor(elapsed / HOUR_MS)} h ago`;
  }
  if (elapsed < WEEK_MS) {
    return `${WEEKDAYS[date.getDay()]} ${clock(date)}`;
  }
  if (date.getFullYear() === now.getFullYear()) {
    return `${date.getDate()} ${MONTHS[date.getMonth()]}`;
  }
  return `${date.getDate()} ${MONTHS[date.getMonth()]} ${date.getFullYear()}`;
}

/**
 * Full local timestamp for tooltips and title attributes, for example
 * "Mon, 24 Aug 2026 at 14:32". Returns an empty string for an unusable value.
 */
export function absoluteTime(value: string | null | undefined): string {
  const date = parseTimestamp(value);
  if (!date) {
    return '';
  }
  const day = `${WEEKDAYS[date.getDay()]}, ${date.getDate()} ${MONTHS[date.getMonth()]} ${date.getFullYear()}`;
  return `${day} at ${clock(date)}`;
}

/**
 * Publisher hostname for a source URL, lowercase and without a www prefix,
 * for example "reuters.com". Falls back to the trimmed input when the URL
 * cannot be parsed.
 */
export function sourceHost(url: string | null | undefined): string {
  if (!url) {
    return '';
  }
  const trimmed = url.trim();
  if (trimmed === '') {
    return '';
  }
  try {
    const parsed = new URL(trimmed);
    return parsed.hostname.toLowerCase().replace(/^www\./, '');
  } catch {
    return trimmed.replace(/^https?:\/\//i, '').replace(/^www\./i, '').split('/')[0].toLowerCase();
  }
}

/**
 * Compact number for counts and scores: 940, 1.2K, 34K, 5.6M, 2.1B.
 * Negative values keep their sign.
 */
export function compactNumber(value: number): string {
  if (!Number.isFinite(value)) {
    return '0';
  }
  const sign = value < 0 ? '-' : '';
  const abs = Math.abs(value);

  if (abs < 1000) {
    return `${sign}${Math.round(abs)}`;
  }

  const units: Array<{ limit: number; suffix: string }> = [
    { limit: 1_000_000_000, suffix: 'B' },
    { limit: 1_000_000, suffix: 'M' },
    { limit: 1000, suffix: 'K' },
  ];

  for (const unit of units) {
    if (abs >= unit.limit) {
      const scaled = abs / unit.limit;
      const text = scaled < 10 ? scaled.toFixed(1).replace(/\.0$/, '') : String(Math.round(scaled));
      return `${sign}${text}${unit.suffix}`;
    }
  }

  return `${sign}${Math.round(abs)}`;
}
