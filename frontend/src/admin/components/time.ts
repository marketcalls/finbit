/**
 * Forward-looking time formatting, which lib/format.ts deliberately does not do.
 *
 * relativeTime clamps a future timestamp to "just now", because a publisher
 * clock running fast should never make a story look like it arrives tomorrow.
 * The scheduler's next_ingest_at and next_rescore_at are genuinely in the
 * future, so they need their own formatter rather than a change to the shared
 * one that would loosen the rule the public feed relies on.
 */

import { parseTimestamp } from '../../lib/format';

const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;

/**
 * How long until a scheduled moment, for example "in 4 min" or "in 2 h".
 *
 * A time that has already passed reads "due now" rather than a negative
 * countdown: the scheduler tick that was going to run it is simply late.
 * Returns an empty string when there is no usable timestamp.
 */
export function countdown(value: string | null | undefined, now: Date = new Date()): string {
  const date = parseTimestamp(value);
  if (!date) {
    return '';
  }

  const remaining = date.getTime() - now.getTime();
  if (remaining <= 0) {
    return 'due now';
  }
  if (remaining < MINUTE_MS) {
    return 'in under a minute';
  }
  if (remaining < HOUR_MS) {
    return `in ${Math.round(remaining / MINUTE_MS)} min`;
  }
  if (remaining < DAY_MS) {
    return `in ${Math.round(remaining / HOUR_MS)} h`;
  }
  return `in ${Math.round(remaining / DAY_MS)} days`;
}

/** A definition list value, with a spelled out placeholder rather than a dash. */
export function orUnknown(value: string): string {
  return value === '' ? 'unknown' : value;
}
