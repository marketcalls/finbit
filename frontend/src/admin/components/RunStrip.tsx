/**
 * The last few ingest runs, as a compact strip.
 *
 * Contract section 9 asks for the last five runs with status, time and counts.
 * It is a strip rather than a table because it is a glance, not a record: the
 * question it answers is "did the last cycle work and what did it cost", and a
 * full table would imply an analytics screen this build deliberately does not
 * ship (section 6.4).
 *
 * Cost is printed to three decimals because a single run costs a few thousandths
 * of a dollar, and rounding it to two would show every successful run as 0.01.
 */

import type { IngestRun } from '@finbit/shared';
import { Badge } from '../../components/ui/badge';
import type { BadgeProps } from '../../components/ui/badge';
import { absoluteTime, relativeTime } from '../../lib/format';
import { EmptyBlock } from './StateBlocks';

function statusVariant(status: IngestRun['status']): BadgeProps['variant'] {
  if (status === 'ok') {
    return 'bull';
  }
  if (status === 'error') {
    return 'bear';
  }
  return 'flat';
}

function formatCost(costUsd: number): string {
  return `${costUsd.toFixed(3)} USD`;
}

export interface RunStripProps {
  runs: IngestRun[];
  /** Shown when there is no history yet, instead of an empty box. */
  emptyBody?: string;
}

export function RunStrip({ runs, emptyBody }: RunStripProps): JSX.Element {
  if (runs.length === 0) {
    return (
      <EmptyBlock
        title="No ingest runs yet"
        body={
          emptyBody ??
          'Nothing has been fetched on this database. Run a cycle from the actions above, or seed it from the command line.'
        }
      />
    );
  }

  return (
    <ul className="flex flex-col divide-y divide-border rounded-xl border border-border bg-card">
      {runs.map((run) => (
        <li key={run.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3">
          <Badge variant={statusVariant(run.status)}>{run.status}</Badge>
          <span className="text-sm text-fg" title={absoluteTime(run.started_at)}>
            {relativeTime(run.started_at)}
          </span>
          <span className="text-sm text-muted-fg tabular-nums">
            {run.queries_run} queries, {run.stories_seen} seen, {run.stories_new} new,{' '}
            {run.stories_merged} merged
          </span>
          <span className="ml-auto text-sm text-muted-fg tabular-nums">
            {formatCost(run.cost_usd)}
          </span>
          {run.error !== null && run.error !== '' ? (
            <p className="w-full text-xs text-bear">{run.error}</p>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
