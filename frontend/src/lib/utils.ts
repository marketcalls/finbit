/**
 * The class name helper every shadcn primitive is written against.
 *
 * clsx flattens conditional class expressions; tailwind-merge then drops the
 * losers when two utilities target the same CSS property, so a caller can pass
 * className="px-6" to a component whose base string already says "px-4" and get
 * px-6 rather than a coin toss on source order.
 */

import { clsx } from 'clsx';
import type { ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
