/**
 * The admin landing screen: is the API up, is there content, and did the last
 * ingest work.
 *
 * Two calls feed it, and they are separate on purpose. GET /api/admin/pipeline
 * is the authority for the schedule, for whether ingestion can run at all and
 * for the recent run history, and a failure there is a real error. GET
 * /api/health is a best effort: phase 2 moves the public routes behind the
 * device handshake, which the admin console does not perform, so a refusal
 * there is an expected outcome and is reported as "not available" instead of
 * breaking the screen. The last ingest falls back to the run history when
 * health cannot be read, so the card is never blank.
 *
 * There is no cost chart here. Contract section 6.4 puts a cost and analytics
 * screen out of scope, and the run strip already carries the per-run spend.
 */

import { useCallback, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { Activity, ArrowRight, Clock, Database } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

import type {
  HealthResponse,
  IngestRun,
  PipelineState,
} from '@finbit/shared';
import { Badge } from '../../components/ui/badge';
import type { BadgeProps } from '../../components/ui/badge';
import { absoluteTime, relativeTime } from '../../lib/format';
import { adminApi, describeAdminError, isAbortError } from '../api';
import { ADMIN_NAV, adminRouteHash } from '../AdminShell';
import type { AdminRoute } from '../AdminShell';
import { RunStrip } from '../components/RunStrip';
import { CardSkeleton, ErrorBlock, LoadingAnnouncement } from '../components/StateBlocks';
import { countdown, orUnknown } from '../components/time';

type LoadStatus = 'loading' | 'ready' | 'error';

function ingestStatusVariant(status: string | null): BadgeProps['variant'] {
  if (status === 'ok') {
    return 'bull';
  }
  if (status === 'error') {
    return 'bear';
  }
  return 'flat';
}

/** One headline number with a short caption under it. */
function StatCard({
  icon: Icon,
  title,
  value,
  children,
}: {
  icon: LucideIcon;
  title: string;
  value: string;
  children?: ReactNode;
}): JSX.Element {
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-border bg-card p-5">
      <div className="flex items-center gap-2 text-muted-fg">
        <Icon aria-hidden="true" className="size-4" />
        <h2 className="text-sm font-medium">{title}</h2>
      </div>
      <p className="font-headline text-2xl font-semibold tabular-nums text-fg">{value}</p>
      {children}
    </div>
  );
}

export interface DashboardScreenProps {
  onNavigate: (route: AdminRoute) => void;
}

export function DashboardScreen({ onNavigate }: DashboardScreenProps): JSX.Element {
  const [pipeline, setPipeline] = useState<PipelineState | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [status, setStatus] = useState<LoadStatus>('loading');
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setStatus('loading');
    setError(null);

    // Health is allowed to fail; the pipeline call is the one that matters.
    adminApi
      .health(controller.signal)
      .then((response) => {
        setHealth(response);
      })
      .catch(() => {
        setHealth(null);
      });

    adminApi
      .getPipeline(controller.signal)
      .then((response) => {
        setPipeline(response);
        setStatus('ready');
      })
      .catch((cause: unknown) => {
        if (isAbortError(cause)) {
          return;
        }
        setError(describeAdminError(cause));
        setStatus('error');
      });

    return () => {
      controller.abort();
    };
  }, [reloadToken]);

  const retry = useCallback(() => {
    setReloadToken((token) => token + 1);
  }, []);

  if (status === 'loading') {
    return (
      <div className="flex flex-col gap-6">
        <h1 className="font-headline text-2xl font-semibold">Dashboard</h1>
        <LoadingAnnouncement>Loading the admin dashboard.</LoadingAnnouncement>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <CardSkeleton lines={2} />
          <CardSkeleton lines={2} />
          <CardSkeleton lines={2} />
        </div>
        <CardSkeleton lines={4} />
      </div>
    );
  }

  if (status === 'error' || pipeline === null) {
    return (
      <div className="flex flex-col gap-6">
        <h1 className="font-headline text-2xl font-semibold">Dashboard</h1>
        <ErrorBlock
          title="Could not load the dashboard"
          message={error ?? 'The pipeline state did not load.'}
          onRetry={retry}
        />
      </div>
    );
  }

  const runs: IngestRun[] = pipeline.recent_runs ?? [];
  const lastRun = runs.length > 0 ? runs[0] : null;
  const lastIngestAt = health?.last_ingest_at ?? lastRun?.started_at ?? null;
  const lastIngestStatus = health?.last_ingest_status ?? lastRun?.status ?? null;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-headline text-2xl font-semibold">Dashboard</h1>
        <button
          type="button"
          onClick={retry}
          className="min-h-11 rounded-md px-3 text-sm font-medium text-muted-fg transition-colors duration-150 hover:bg-muted hover:text-fg"
        >
          Refresh
        </button>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <StatCard
          icon={Activity}
          title="API"
          value={health !== null ? health.status : 'not available'}
        >
          <p className="text-xs text-muted-fg">
            {health !== null
              ? 'GET /api/health answered for this admin token.'
              : 'Health is behind the device handshake, which the console does not perform. The pipeline state below is still live.'}
          </p>
        </StatCard>

        <StatCard
          icon={Database}
          title="Articles"
          value={health !== null ? String(health.articles) : 'unknown'}
        >
          <p className="text-xs text-muted-fg">
            {health !== null && health.articles === 0
              ? 'The database is empty. Fetch a cycle from the Pipeline screen to fill it.'
              : 'Stories currently stored, hidden ones included.'}
          </p>
        </StatCard>

        <StatCard
          icon={Clock}
          title="Last ingest"
          value={orUnknown(relativeTime(lastIngestAt))}
        >
          <div className="flex items-center gap-2">
            <Badge variant={ingestStatusVariant(lastIngestStatus)}>
              {lastIngestStatus ?? 'never run'}
            </Badge>
            {lastIngestAt !== null ? (
              <span className="text-xs text-muted-fg">{absoluteTime(lastIngestAt)}</span>
            ) : null}
          </div>
        </StatCard>
      </div>

      <section
        aria-labelledby="dashboard-ingestion"
        className="rounded-xl border border-border bg-card p-5"
      >
        <h2 id="dashboard-ingestion" className="text-sm font-semibold text-fg">
          Ingestion
        </h2>
        <dl className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <dt className="text-xs text-muted-fg">Available</dt>
            <dd className="mt-1">
              <Badge variant={pipeline.ingest_available ? 'bull' : 'bear'}>
                {pipeline.ingest_available ? 'yes' : 'no'}
              </Badge>
            </dd>
          </div>
          <div>
            <dt className="text-xs text-muted-fg">Scheduler</dt>
            <dd className="mt-1">
              <Badge variant={pipeline.scheduler.running ? 'bull' : 'flat'}>
                {pipeline.scheduler.running ? 'running' : 'stopped'}
              </Badge>
            </dd>
          </div>
          <div>
            <dt className="text-xs text-muted-fg">Next ingest</dt>
            <dd className="mt-1 text-sm text-fg" title={absoluteTime(pipeline.scheduler.next_ingest_at)}>
              {orUnknown(countdown(pipeline.scheduler.next_ingest_at))}
            </dd>
          </div>
          <div>
            <dt className="text-xs text-muted-fg">Next rescore</dt>
            <dd
              className="mt-1 text-sm text-fg"
              title={absoluteTime(pipeline.scheduler.next_rescore_at)}
            >
              {orUnknown(countdown(pipeline.scheduler.next_rescore_at))}
            </dd>
          </div>
        </dl>
        {!pipeline.ingest_available ? (
          <p className="mt-4 text-sm text-bear">
            {pipeline.reason ?? 'Ingestion is unavailable and the API gave no reason.'}
          </p>
        ) : null}
      </section>

      <section aria-labelledby="dashboard-runs" className="flex flex-col gap-3">
        <h2 id="dashboard-runs" className="text-sm font-semibold text-fg">
          Recent runs
        </h2>
        <RunStrip runs={runs} />
      </section>

      <section aria-labelledby="dashboard-links" className="flex flex-col gap-3">
        <h2 id="dashboard-links" className="text-sm font-semibold text-fg">
          Go to
        </h2>
        <div className="grid gap-4 sm:grid-cols-3">
          {ADMIN_NAV.filter((item) => item.key !== 'dashboard').map((item) => {
            const Icon = item.icon;
            return (
              <a
                key={item.key}
                href={adminRouteHash(item.key)}
                onClick={(event) => {
                  if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) {
                    return;
                  }
                  event.preventDefault();
                  onNavigate(item.key);
                }}
                className="flex flex-col gap-2 rounded-xl border border-border bg-card p-5 transition-colors duration-150 hover:bg-muted"
              >
                <span className="flex items-center gap-2 text-sm font-semibold text-fg">
                  <Icon aria-hidden="true" className="size-4" />
                  {item.label}
                  <ArrowRight aria-hidden="true" className="ml-auto size-4 text-muted-fg" />
                </span>
                <span className="text-xs text-muted-fg">{item.blurb}</span>
              </a>
            );
          })}
        </div>
      </section>
    </div>
  );
}
