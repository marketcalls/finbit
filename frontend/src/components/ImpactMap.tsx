/**
 * The potential-impact table from the MVP spec: a small two-column list of a
 * symbol or sector and the direction FinBit expects for it.
 *
 * Same rule as the Market Impact badge, contract section 10: direction is
 * carried by an icon and a written label, colour only reinforces it, and
 * "mixed" is a split bull/bear pair rather than a new hue. These are AI
 * assessments, never a trading signal, so the block says so.
 */

import type { ImpactEntry, ImpactEntryDirection } from '../api/types';
import { IconTrendDown, IconTrendFlat, IconTrendUp } from './Icons';

type IconComponent = (props: { className?: string }) => JSX.Element;

const DIRECTION_LABELS: Record<ImpactEntryDirection, string> = {
  positive: 'Positive',
  negative: 'Negative',
  neutral: 'Neutral',
  mixed: 'Mixed',
};

const DIRECTION_ICONS: Record<Exclude<ImpactEntryDirection, 'mixed'>, { icon: string; Icon: IconComponent }> = {
  positive: { icon: 'text-bull', Icon: IconTrendUp },
  negative: { icon: 'text-bear', Icon: IconTrendDown },
  neutral: { icon: 'text-flat', Icon: IconTrendFlat },
};

function DirectionMark({ direction }: { direction: ImpactEntryDirection }): JSX.Element {
  if (direction === 'mixed') {
    return (
      <span aria-hidden="true" className="inline-flex overflow-hidden rounded-full">
        <span className="inline-flex items-center bg-bull/20 px-1 py-0.5 text-bull">
          <IconTrendUp className="h-3 w-3" />
        </span>
        <span className="inline-flex items-center bg-bear/20 px-1 py-0.5 text-bear">
          <IconTrendDown className="h-3 w-3" />
        </span>
      </span>
    );
  }

  // Fall back to neutral if the API ever sends a direction outside the vocabulary.
  const { Icon, icon } = DIRECTION_ICONS[direction] ?? DIRECTION_ICONS.neutral;
  return <Icon className={`h-4 w-4 ${icon}`} />;
}

export interface ImpactMapProps {
  entries: ImpactEntry[];
}

export function ImpactMap({ entries }: ImpactMapProps): JSX.Element {
  // Merged clusters can repeat a name, so keep the first reading for each.
  const rows: ImpactEntry[] = [];
  const seen = new Set<string>();
  for (const entry of entries) {
    if (!entry || typeof entry.name !== 'string' || entry.name.trim() === '') {
      continue;
    }
    const key = entry.name.trim().toLowerCase();
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    rows.push(entry);
  }

  if (rows.length === 0) {
    return <></>;
  }

  return (
    <div className="rounded-lg border border-border bg-muted/60 px-3 py-2.5">
      <p className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-fg">
        Potential impact
      </p>

      <dl aria-label="Potential impact by symbol or sector" className="mt-1.5">
        {rows.map((entry, index) => (
          <div
            key={entry.name}
            className={`flex items-center justify-between gap-3 py-1.5 ${
              index === 0 ? '' : 'border-t border-border'
            }`}
          >
            <dt className="min-w-0 truncate text-sm text-fg">{entry.name}</dt>
            <dd className="flex shrink-0 items-center gap-1.5 text-sm text-fg">
              <DirectionMark direction={entry.direction} />
              <span>{DIRECTION_LABELS[entry.direction] ?? DIRECTION_LABELS.neutral}</span>
            </dd>
          </div>
        ))}
      </dl>

      <p className="mt-2 text-[11px] text-muted-fg">AI assessment, not investment advice.</p>
    </div>
  );
}
