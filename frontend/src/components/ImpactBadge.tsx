/**
 * The Market Impact chip, contract sections 10 and 11.
 *
 * Direction is carried by an icon and a written label, never by colour alone,
 * and "mixed" renders as a split bull/bear chip rather than a new hue. The
 * words sit on the high contrast foreground token while the bull, bear and flat
 * tokens colour the icon, the border and the tint, which keeps the text above
 * 4.5:1 in both themes.
 *
 * The badge renders the chip alone. The "Market Impact" label belongs to the
 * impact section around it, which NewsCard supplies as a section label and a
 * heading, so putting it here as well would say it twice.
 */

import type { Impact, ImpactDirection } from '../api/types';
import { IconTrendDown, IconTrendFlat, IconTrendUp } from './Icons';

type IconComponent = (props: { className?: string }) => JSX.Element;

const IMPACT_LABELS: Record<Impact, string> = {
  high: 'High',
  medium: 'Medium',
  low: 'Low',
};

const DIRECTION_LABELS: Record<ImpactDirection, string> = {
  bullish: 'Bullish',
  bearish: 'Bearish',
  neutral: 'Neutral',
  mixed: 'Mixed',
};

interface DirectionTone {
  chip: string;
  icon: string;
  Icon: IconComponent;
}

const DIRECTION_TONES: Record<Exclude<ImpactDirection, 'mixed'>, DirectionTone> = {
  bullish: { chip: 'border-bull/40 bg-bull/10', icon: 'text-bull', Icon: IconTrendUp },
  bearish: { chip: 'border-bear/40 bg-bear/10', icon: 'text-bear', Icon: IconTrendDown },
  neutral: { chip: 'border-flat/40 bg-flat/10', icon: 'text-flat', Icon: IconTrendFlat },
};

const CHIP_BASE =
  'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium text-fg';

export interface ImpactBadgeProps {
  impact: Impact;
  direction: ImpactDirection;
  className?: string;
}

export function ImpactBadge({ impact, direction, className }: ImpactBadgeProps): JSX.Element {
  // Fall back inside the vocabulary if the API ever sends a value outside it.
  const impactLabel = IMPACT_LABELS[impact] ?? IMPACT_LABELS.low;
  const directionLabel = DIRECTION_LABELS[direction] ?? DIRECTION_LABELS.neutral;

  const extra = className ? ` ${className}` : '';

  if (direction === 'mixed') {
    return (
      <span className={`${CHIP_BASE} border-border bg-muted${extra}`}>
        {/* A split chip: bull on one half, bear on the other, no new hue. */}
        <span aria-hidden="true" className="inline-flex overflow-hidden rounded-full">
          <span className="inline-flex items-center bg-bull/20 px-1 py-0.5 text-bull">
            <IconTrendUp className="h-3 w-3" />
          </span>
          <span className="inline-flex items-center bg-bear/20 px-1 py-0.5 text-bear">
            <IconTrendDown className="h-3 w-3" />
          </span>
        </span>
        <span>{directionLabel}</span>
        <span aria-hidden="true" className="text-muted-fg">
          &middot;
        </span>
        <span>{impactLabel}</span>
      </span>
    );
  }

  const tone = DIRECTION_TONES[direction] ?? DIRECTION_TONES.neutral;
  const { Icon } = tone;

  return (
    <span className={`${CHIP_BASE} ${tone.chip}${extra}`}>
      <Icon className={`h-3.5 w-3.5 ${tone.icon}`} />
      <span>{directionLabel}</span>
      <span aria-hidden="true" className="text-muted-fg">
        &middot;
      </span>
      <span>{impactLabel}</span>
    </span>
  );
}
