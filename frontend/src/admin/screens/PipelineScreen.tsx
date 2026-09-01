/**
 * Pipeline control: the schedule, the nine-query set and the manual triggers,
 * contract section 9 and section 6.4.
 *
 * Two independent drafts live here, one for the five schedule settings and one
 * for the query set, each with its own Save. They are separate because they are
 * separate endpoints (PATCH /api/admin/pipeline and PUT
 * /api/admin/pipeline/queries) and because a half-finished prompt edit must not
 * ride along with a change to the ingest interval.
 *
 * Neither save is optimistic. The API answers with the settings it actually
 * stored, and a schedule that shows a value the server rejected would be worse
 * than a moment of waiting: the whole point of this screen is to know what the
 * pipeline is really doing. The drafts are re-seeded from every response, so a
 * clamp on the server is visible immediately.
 *
 * Fetch now spends real money. It states the estimate, it is gated behind a
 * confirmation, and it is disabled with the server's reason attached when
 * ingestion is unavailable at all.
 */

import { useCallback, useEffect, useState } from 'react';
import { Image as ImageIcon, LoaderCircle, Play, RefreshCw } from 'lucide-react';

import type {
  PipelineSettings,
  PipelineSettingsPatch,
  PipelineState,
  QueryDef,
} from '@finbit/shared';
import { Button } from '../../components/ui/button';
import { toast } from '../../components/ui/sonner';
import { COST_PER_QUERY_USD, adminApi, describeAdminError, isAbortError } from '../api';
import { ConfirmAction } from '../components/ConfirmAction';
import { NumberField, SwitchField } from '../components/Field';
import { QueryEditor } from '../components/QueryEditor';
import { RunStrip } from '../components/RunStrip';
import { CardSkeleton, ErrorBlock, LoadingAnnouncement } from '../components/StateBlocks';
import { countdown, orUnknown } from '../components/time';

type LoadStatus = 'loading' | 'ready' | 'error';

/** Which long running control is currently in flight, so only it spins. */
type BusyAction = 'settings' | 'queries' | 'ingest' | 'rescore' | 'images' | null;

/** The five scalar settings this screen edits. query_set is not one of them. */
type ScheduleDraft = Omit<PipelineSettings, 'query_set'>;

function toDraft(settings: PipelineSettings): ScheduleDraft {
  return {
    ingest_enabled: settings.ingest_enabled,
    ingest_interval_minutes: settings.ingest_interval_minutes,
    ingest_queries_per_cycle: settings.ingest_queries_per_cycle,
    ingest_max_stories_per_query: settings.ingest_max_stories_per_query,
    rescore_interval_minutes: settings.rescore_interval_minutes,
  };
}

/** Only the keys that actually changed, so a PATCH says what it means. */
function changedKeys(draft: ScheduleDraft, saved: ScheduleDraft): PipelineSettingsPatch {
  const patch: PipelineSettingsPatch = {};
  if (draft.ingest_enabled !== saved.ingest_enabled) {
    patch.ingest_enabled = draft.ingest_enabled;
  }
  if (draft.ingest_interval_minutes !== saved.ingest_interval_minutes) {
    patch.ingest_interval_minutes = draft.ingest_interval_minutes;
  }
  if (draft.ingest_queries_per_cycle !== saved.ingest_queries_per_cycle) {
    patch.ingest_queries_per_cycle = draft.ingest_queries_per_cycle;
  }
  if (draft.ingest_max_stories_per_query !== saved.ingest_max_stories_per_query) {
    patch.ingest_max_stories_per_query = draft.ingest_max_stories_per_query;
  }
  if (draft.rescore_interval_minutes !== saved.rescore_interval_minutes) {
    patch.rescore_interval_minutes = draft.rescore_interval_minutes;
  }
  return patch;
}

function sameQueries(draft: QueryDef[], saved: QueryDef[]): boolean {
  if (draft.length !== saved.length) {
    return false;
  }
  return draft.every((query, index) => {
    const other = saved[index];
    return (
      query.key === other.key &&
      query.label === other.label &&
      query.prompt === other.prompt &&
      query.enabled === other.enabled &&
      query.category_hint === other.category_hint
    );
  });
}

/** Roughly what one manual cycle costs, so the spend is never a surprise. */
function estimateCost(queriesPerCycle: number): string {
  return (queriesPerCycle * COST_PER_QUERY_USD).toFixed(3);
}

export function PipelineScreen(): JSX.Element {
  const [pipeline, setPipeline] = useState<PipelineState | null>(null);
  const [savedQueries, setSavedQueries] = useState<QueryDef[]>([]);
  const [draft, setDraft] = useState<ScheduleDraft | null>(null);
  const [queryDraft, setQueryDraft] = useState<QueryDef[]>([]);
  const [status, setStatus] = useState<LoadStatus>('loading');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<BusyAction>(null);
  const [confirmFetch, setConfirmFetch] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setStatus('loading');
    setError(null);

    Promise.all([
      adminApi.getPipeline(controller.signal),
      adminApi.getQueries(controller.signal),
    ])
      .then(([state, queries]) => {
        setPipeline(state);
        setDraft(toDraft(state.settings));
        setSavedQueries(queries.queries);
        setQueryDraft(queries.queries.map((query) => ({ ...query })));
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

  const reload = useCallback(() => {
    setReloadToken((token) => token + 1);
  }, []);

  /** Adopt a fresh pipeline payload and re-seed the schedule draft from it. */
  const adopt = useCallback((state: PipelineState) => {
    setPipeline(state);
    setDraft(toDraft(state.settings));
  }, []);

  // Nothing loaded yet: the screen is either still fetching or has nothing to show.
  if (draft === null || pipeline === null) {
    return (
      <div className="flex flex-col gap-6">
        <h1 className="font-headline text-2xl font-semibold">Pipeline</h1>
        {status === 'error' ? (
          <ErrorBlock
            title="Could not load the pipeline"
            message={error ?? 'The pipeline state did not load.'}
            onRetry={reload}
          />
        ) : (
          <>
            <LoadingAnnouncement>Loading the pipeline settings.</LoadingAnnouncement>
            <CardSkeleton lines={5} />
            <CardSkeleton lines={3} />
            <CardSkeleton lines={4} />
          </>
        )}
      </div>
    );
  }

  const savedDraft = toDraft(pipeline.settings);
  const patch = changedKeys(draft, savedDraft);
  const settingsDirty = Object.keys(patch).length > 0;
  const queriesDirty = !sameQueries(queryDraft, savedQueries);
  const anyBusy = busy !== null;
  const perCycleCost = estimateCost(draft.ingest_queries_per_cycle);

  async function saveSettings(): Promise<void> {
    setBusy('settings');
    try {
      const next = await adminApi.patchPipeline(patch);
      adopt(next);
      toast.success('Pipeline settings saved');
    } catch (cause) {
      toast.error(describeAdminError(cause));
    } finally {
      setBusy(null);
    }
  }

  async function saveQueries(): Promise<void> {
    setBusy('queries');
    const attempted = queryDraft.map((query) => ({ ...query }));
    try {
      const next = await adminApi.putQueries(attempted);
      setSavedQueries(next.queries);
      setQueryDraft(next.queries.map((query) => ({ ...query })));
      toast.success('Query set saved');
    } catch (cause) {
      toast.error(describeAdminError(cause));
    } finally {
      setBusy(null);
    }
  }

  async function runIngest(): Promise<void> {
    setBusy('ingest');
    try {
      const started = await adminApi.triggerIngest({});
      toast.success(`Ingest run ${started.run_id} started`);
      reload();
    } catch (cause) {
      toast.error(describeAdminError(cause));
    } finally {
      setBusy(null);
    }
  }

  async function runRescore(): Promise<void> {
    setBusy('rescore');
    try {
      const result = await adminApi.rescoreAll();
      toast.success(`Rescored ${result.updated} articles`);
      reload();
    } catch (cause) {
      toast.error(describeAdminError(cause));
    } finally {
      setBusy(null);
    }
  }

  async function runImages(): Promise<void> {
    setBusy('images');
    try {
      await adminApi.refreshImages();
      toast.success('Image refresh started');
    } catch (cause) {
      toast.error(describeAdminError(cause));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-headline text-2xl font-semibold">Pipeline</h1>
        <p className="text-sm text-muted-fg">
          Next ingest {orUnknown(countdown(pipeline.scheduler.next_ingest_at))}, next rescore{' '}
          {orUnknown(countdown(pipeline.scheduler.next_rescore_at))}
        </p>
      </div>

      {/*
        A reload that failed while the screen already had data: keep the data on
        screen and say so, rather than throwing away a draft someone is editing.
      */}
      {status === 'error' ? (
        <ErrorBlock
          title="Could not refresh the pipeline"
          message={error ?? 'The pipeline state did not reload.'}
          onRetry={reload}
        />
      ) : null}

      {/* -- schedule ------------------------------------------------------ */}
      <section
        aria-labelledby="pipeline-schedule"
        className="flex flex-col gap-5 rounded-xl border border-border bg-card p-5"
      >
        <div>
          <h2 id="pipeline-schedule" className="text-sm font-semibold text-fg">
            Schedule
          </h2>
          <p className="mt-1 text-xs text-muted-fg">
            These override the values in .env at runtime, so a change takes effect without a
            restart.
          </p>
        </div>

        <SwitchField
          label="Ingestion enabled"
          description="Off stops the scheduler from starting new discovery cycles. Manual fetches below still work."
          checked={draft.ingest_enabled}
          disabled={anyBusy}
          onCheckedChange={(next) => {
            setDraft({ ...draft, ingest_enabled: next });
          }}
        />

        <div className="grid gap-5 sm:grid-cols-2">
          <NumberField
            label="Ingest interval"
            value={draft.ingest_interval_minutes}
            min={1}
            max={1440}
            suffix="minutes"
            disabled={anyBusy}
            hint="How often the scheduler starts a cycle."
            onChange={(next) => {
              setDraft({ ...draft, ingest_interval_minutes: next });
            }}
          />
          <NumberField
            label="Queries per cycle"
            value={draft.ingest_queries_per_cycle}
            min={1}
            max={9}
            suffix="queries"
            disabled={anyBusy}
            hint={`About ${perCycleCost} USD per cycle at the current setting.`}
            onChange={(next) => {
              setDraft({ ...draft, ingest_queries_per_cycle: next });
            }}
          />
          <NumberField
            label="Max stories per query"
            value={draft.ingest_max_stories_per_query}
            min={1}
            max={20}
            suffix="stories"
            disabled={anyBusy}
            hint="Caps how many stories one query may return."
            onChange={(next) => {
              setDraft({ ...draft, ingest_max_stories_per_query: next });
            }}
          />
          <NumberField
            label="Rescore interval"
            value={draft.rescore_interval_minutes}
            min={5}
            max={1440}
            suffix="minutes"
            disabled={anyBusy}
            hint="How often importance scores are recomputed so the feed decays."
            onChange={(next) => {
              setDraft({ ...draft, rescore_interval_minutes: next });
            }}
          />
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            disabled={!settingsDirty || anyBusy}
            onClick={() => {
              void saveSettings();
            }}
          >
            {busy === 'settings' ? (
              <LoaderCircle aria-hidden="true" className="animate-spin" />
            ) : null}
            Save schedule
          </Button>
          <Button
            type="button"
            variant="ghost"
            disabled={!settingsDirty || anyBusy}
            onClick={() => {
              setDraft(savedDraft);
            }}
          >
            Discard
          </Button>
          {settingsDirty ? (
            <span className="text-xs text-muted-fg" aria-live="polite">
              Unsaved changes
            </span>
          ) : null}
        </div>
      </section>

      {/* -- manual actions ------------------------------------------------ */}
      <section
        aria-labelledby="pipeline-actions"
        className="flex flex-col gap-4 rounded-xl border border-border bg-card p-5"
      >
        <h2 id="pipeline-actions" className="text-sm font-semibold text-fg">
          Actions
        </h2>

        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap items-center gap-3">
            <Button
              type="button"
              disabled={anyBusy || !pipeline.ingest_available}
              onClick={() => {
                setConfirmFetch(true);
              }}
            >
              {busy === 'ingest' ? (
                <LoaderCircle aria-hidden="true" className="animate-spin" />
              ) : (
                <Play aria-hidden="true" />
              )}
              Fetch now
            </Button>
            <span className="text-sm text-muted-fg">
              Spends about {perCycleCost} USD, {draft.ingest_queries_per_cycle} queries at about{' '}
              {COST_PER_QUERY_USD.toFixed(3)} USD each.
            </span>
          </div>
          {!pipeline.ingest_available ? (
            <p className="text-sm text-bear">
              {pipeline.reason ?? 'Ingestion is unavailable and the API gave no reason.'}
            </p>
          ) : null}

          <div className="flex flex-wrap items-center gap-3">
            <Button
              type="button"
              variant="outline"
              disabled={anyBusy}
              onClick={() => {
                void runRescore();
              }}
            >
              {busy === 'rescore' ? (
                <LoaderCircle aria-hidden="true" className="animate-spin" />
              ) : (
                <RefreshCw aria-hidden="true" />
              )}
              Rescore now
            </Button>
            <span className="text-sm text-muted-fg">
              Free. Recomputes every importance score so older stories decay.
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Button
              type="button"
              variant="outline"
              disabled={anyBusy}
              onClick={() => {
                void runImages();
              }}
            >
              {busy === 'images' ? (
                <LoaderCircle aria-hidden="true" className="animate-spin" />
              ) : (
                <ImageIcon aria-hidden="true" />
              )}
              Refresh images
            </Button>
            <span className="text-sm text-muted-fg">
              Free. Re-reads Open Graph tags from the source pages, no model call.
            </span>
          </div>
        </div>
      </section>

      {/* -- run history --------------------------------------------------- */}
      <section aria-labelledby="pipeline-runs" className="flex flex-col gap-3">
        <h2 id="pipeline-runs" className="text-sm font-semibold text-fg">
          Recent runs
        </h2>
        <RunStrip runs={pipeline.recent_runs} />
      </section>

      {/* -- query set ----------------------------------------------------- */}
      <section aria-labelledby="pipeline-queries" className="flex flex-col gap-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 id="pipeline-queries" className="text-sm font-semibold text-fg">
              Discovery queries
            </h2>
            <p className="mt-1 text-xs text-muted-fg">
              In rotation: {pipeline.settings.query_set.join(', ') || 'none'}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              disabled={!queriesDirty || anyBusy}
              onClick={() => {
                void saveQueries();
              }}
            >
              {busy === 'queries' ? (
                <LoaderCircle aria-hidden="true" className="animate-spin" />
              ) : null}
              Save queries
            </Button>
            <Button
              type="button"
              variant="ghost"
              disabled={!queriesDirty || anyBusy}
              onClick={() => {
                setQueryDraft(savedQueries.map((query) => ({ ...query })));
              }}
            >
              Discard
            </Button>
          </div>
        </div>

        <QueryEditor queries={queryDraft} onChange={setQueryDraft} disabled={anyBusy} />
      </section>

      <ConfirmAction
        open={confirmFetch}
        onOpenChange={setConfirmFetch}
        title="Fetch news now?"
        confirmLabel="Fetch now"
        description={
          <>
            <p>
              This runs one discovery cycle immediately: {draft.ingest_queries_per_cycle} queries
              against the Perplexity Agent API.
            </p>
            <p className="mt-2">
              Estimated cost about {perCycleCost} USD. The exact spend is recorded on the run and
              appears in the run strip when the cycle finishes.
            </p>
          </>
        }
        onConfirm={() => {
          void runIngest();
        }}
      />
    </div>
  );
}
