/**
 * Display formatting. The API always sends ISO 8601 UTC with a trailing Z
 * (CONTRACT.md section 3) and the client does all the humanising.
 *
 * These are deliberately the same rules as frontend/src/lib/format.ts, so a
 * story that reads "8 min ago" in the browser reads "8 min ago" on the phone.
 * They are reimplemented rather than shared because @finbit/shared is the wire
 * contract and must stay free of anything presentational.
 *
 * Nothing here uses Intl or the URL constructor. Hermes ships a trimmed Intl and
 * React Native's URL is not the browser's, so a formatter built on either one
 * works in the simulator and then disagrees with itself on a real device.
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
 * Parses an API timestamp into a Date in the phone's timezone. A value with no
 * timezone marker is read as UTC, which is what the API sends. Returns null when
 * the value is missing or unparsable, so a bad row cannot render "Invalid Date".
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
 * A future timestamp, which happens when a publisher's clock runs fast, is
 * clamped to "just now" rather than shown as a negative age.
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
 * Full local timestamp for a detail row, for example
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
 * Publisher hostname for a source URL, lowercase and without a www prefix, for
 * example "reuters.com". Parsed with a regex because React Native's URL is a
 * partial polyfill. Falls back to the trimmed input when nothing matches.
 */
export function sourceHost(url: string | null | undefined): string {
  if (!url) {
    return '';
  }
  const trimmed = url.trim();
  if (trimmed === '') {
    return '';
  }
  const match = /^[a-z][a-z0-9+.-]*:\/\/(?:[^/@]*@)?([^/:?#]+)/i.exec(trimmed);
  const host = match ? match[1] : trimmed.split('/')[0];
  return (host ?? '').toLowerCase().replace(/^www\./, '');
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

/**
 * Words in a block of text. Summaries are written to a 50 to 80 word budget, so
 * the card can decide how much room to reserve before it measures anything.
 */
export function wordCount(text: string | null | undefined): number {
  if (!text) {
    return 0;
  }
  const words = text.trim().match(/\S+/g);
  return words === null ? 0 : words.length;
}

/**
 * Reading time in whole minutes, never less than one. Based on 200 words per
 * minute, the usual figure for news prose.
 */
export function readingMinutes(text: string | null | undefined): number {
  return Math.max(1, Math.round(wordCount(text) / 200));
}

/** "1 source" or "4 sources", so a card never prints "1 sources". */
export function sourceCountLabel(count: number): string {
  const safe = Number.isFinite(count) ? Math.max(0, Math.round(count)) : 0;
  return safe === 1 ? '1 source' : `${compactNumber(safe)} sources`;
}

/**
 * The last few characters of a device id, for the Settings support row. The full
 * id identifies a device to the API and there is no reason to put all of it on
 * screen where a screenshot can carry it away.
 */
export function shortDeviceId(deviceId: string | null | undefined, keep = 6): string {
  if (!deviceId) {
    return '';
  }
  const trimmed = deviceId.trim();
  return trimmed.length <= keep ? trimmed : `...${trimmed.slice(-keep)}`;
}
