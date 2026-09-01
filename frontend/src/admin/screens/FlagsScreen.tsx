/**
 * Feature flags: categories, market filters, default sort, maintenance mode and
 * the minimum mobile version, contract section 6.6 and section 9.
 *
 * PUT /api/admin/flags replaces the whole document rather than patching it, so
 * the draft is built from every key the API sent and every key is sent back.
 * That is also why the 'all' pseudo-category, if the server ever includes it,
 * is carried through the draft without a switch of its own: it is a feed filter
 * the apps synthesise, not something an operator turns off, but silently
 * dropping it from the payload would delete it.
 *
 * Saving while maintenance mode is on asks for confirmation. The flag takes the
 * mobile app and the public web feed down (every device-authenticated content
 * route answers 503, section 6.2), so a save made while it is on, or a save
 * that turns it on, deserves a deliberate second press.
 */

import { useCallback, useEffect, useState } from 'react';
import { LoaderCircle } from 'lucide-react';

import type {
  AdminFlagsResponse,
  FlagsPayload,
  SortMode,
} from '@finbit/shared';
import { Button } from '../../components/ui/button';
import { Label } from '../../components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../../components/ui/select';
import { toast } from '../../components/ui/sonner';
import { relativeTime } from '../../lib/format';
import { adminApi, describeAdminError, isAbortError } from '../api';
import { ConfirmAction } from '../components/ConfirmAction';
import { SwitchField, TextAreaField, TextField } from '../components/Field';
import { useMaintenance } from '../components/maintenance';
import { CardSkeleton, ErrorBlock, LoadingAnnouncement } from '../components/StateBlocks';

type LoadStatus = 'loading' | 'ready' | 'error';

interface FlagsDraft {
  categories: Record<string, boolean>;
  marketFilters: Record<string, boolean>;
  defaultSort: SortMode;
  maintenanceMode: boolean;
  maintenanceMessage: string;
  minMobileVersion: string;
}

function toDraft(flags: AdminFlagsResponse): FlagsDraft {
  const categories: Record<string, boolean> = {};
  for (const entry of flags.categories) {
    categories[entry.key] = entry.enabled;
  }
  const marketFilters: Record<string, boolean> = {};
  for (const entry of flags.market_filters) {
    marketFilters[entry.key] = entry.enabled;
  }
  return {
    categories,
    marketFilters,
    defaultSort: flags.default_sort,
    maintenanceMode: flags.maintenance_mode,
    maintenanceMessage: flags.maintenance_message ?? '',
    minMobileVersion: flags.min_mobile_version ?? '',
  };
}

/** Empty text means "no value", which the API models as null, not "". */
function orNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === '' ? null : trimmed;
}

function toPayload(draft: FlagsDraft): FlagsPayload {
  return {
    categories: draft.categories,
    market_filters: draft.marketFilters,
    default_sort: draft.defaultSort,
    maintenance_mode: draft.maintenanceMode,
    maintenance_message: orNull(draft.maintenanceMessage),
    min_mobile_version: orNull(draft.minMobileVersion),
  };
}

function samePayload(a: FlagsPayload, b: FlagsPayload): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

export function FlagsScreen(): JSX.Element {
  const maintenance = useMaintenance();

  const [flags, setFlags] = useState<AdminFlagsResponse | null>(null);
  const [draft, setDraft] = useState<FlagsDraft | null>(null);
  const [status, setStatus] = useState<LoadStatus>('loading');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setStatus('loading');
    setError(null);

    adminApi
      .getFlags(controller.signal)
      .then((response) => {
        setFlags(response);
        setDraft(toDraft(response));
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

  if (draft === null || flags === null) {
    return (
      <div className="flex flex-col gap-6">
        <h1 className="font-headline text-2xl font-semibold">Flags</h1>
        {status === 'error' ? (
          <ErrorBlock
            title="Could not load the flags"
            message={error ?? 'The feature flags did not load.'}
            onRetry={reload}
          />
        ) : (
          <>
            <LoadingAnnouncement>Loading the feature flags.</LoadingAnnouncement>
            <CardSkeleton lines={6} />
            <CardSkeleton lines={4} />
          </>
        )}
      </div>
    );
  }

  const savedPayload = toPayload(toDraft(flags));
  const nextPayload = toPayload(draft);
  const dirty = !samePayload(nextPayload, savedPayload);
  // Confirmation is needed both for turning it on and for saving anything
  // while it is already on, because either way the apps stay dark afterwards.
  const maintenanceInvolved = draft.maintenanceMode || flags.maintenance_mode;

  async function save(): Promise<void> {
    setSaving(true);
    try {
      const updated = await adminApi.putFlags(nextPayload);
      setFlags(updated);
      setDraft(toDraft(updated));
      maintenance.apply(updated.maintenance_mode, updated.maintenance_message);
      toast.success('Flags saved');
    } catch (cause) {
      toast.error(describeAdminError(cause));
    } finally {
      setSaving(false);
    }
  }

  function requestSave(): void {
    if (maintenanceInvolved) {
      setConfirming(true);
      return;
    }
    void save();
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-headline text-2xl font-semibold">Flags</h1>
        <div className="flex items-center gap-2">
          {dirty ? (
            <span className="text-xs text-muted-fg" aria-live="polite">
              Unsaved changes
            </span>
          ) : null}
          <Button
            type="button"
            variant="ghost"
            disabled={!dirty || saving}
            onClick={() => {
              setDraft(toDraft(flags));
            }}
          >
            Discard
          </Button>
          <Button type="button" disabled={!dirty || saving} onClick={requestSave}>
            {saving ? <LoaderCircle aria-hidden="true" className="animate-spin" /> : null}
            Save flags
          </Button>
        </div>
      </div>

      {status === 'error' ? (
        <ErrorBlock
          title="Could not refresh the flags"
          message={error ?? 'The feature flags did not reload.'}
          onRetry={reload}
        />
      ) : null}

      {/* -- categories ---------------------------------------------------- */}
      <section
        aria-labelledby="flags-categories"
        className="flex flex-col gap-1 rounded-xl border border-border bg-card p-5"
      >
        <h2 id="flags-categories" className="text-sm font-semibold text-fg">
          Categories
        </h2>
        <p className="mb-2 text-xs text-muted-fg">
          A category that is off disappears from the tab strip in both apps. Stories already filed
          under it stay in the database and keep appearing under All.
        </p>
        {flags.categories
          .filter((entry) => entry.key !== 'all')
          .map((entry) => (
            <SwitchField
              key={entry.key}
              label={entry.label}
              checked={draft.categories[entry.key] ?? entry.enabled}
              disabled={saving}
              meta={entry.updated_at !== null ? relativeTime(entry.updated_at) : undefined}
              onCheckedChange={(next) => {
                setDraft({
                  ...draft,
                  categories: { ...draft.categories, [entry.key]: next },
                });
              }}
            />
          ))}
      </section>

      {/* -- market filters ------------------------------------------------ */}
      <section
        aria-labelledby="flags-markets"
        className="flex flex-col gap-1 rounded-xl border border-border bg-card p-5"
      >
        <h2 id="flags-markets" className="text-sm font-semibold text-fg">
          Market filters
        </h2>
        <p className="mb-2 text-xs text-muted-fg">
          The quick chips under the category tabs, which filter by symbol rather than by category.
        </p>
        {flags.market_filters.map((entry) => (
          <SwitchField
            key={entry.key}
            label={entry.label}
            checked={draft.marketFilters[entry.key] ?? entry.enabled}
            disabled={saving}
            meta={entry.updated_at !== null ? relativeTime(entry.updated_at) : undefined}
            onCheckedChange={(next) => {
              setDraft({
                ...draft,
                marketFilters: { ...draft.marketFilters, [entry.key]: next },
              });
            }}
          />
        ))}
      </section>

      {/* -- feed behaviour ------------------------------------------------ */}
      <section
        aria-labelledby="flags-feed"
        className="flex flex-col gap-4 rounded-xl border border-border bg-card p-5"
      >
        <h2 id="flags-feed" className="text-sm font-semibold text-fg">
          Feed behaviour
        </h2>

        <div className="flex flex-col gap-2">
          <Label htmlFor="flags-sort">Default sort</Label>
          <Select
            value={draft.defaultSort}
            disabled={saving}
            onValueChange={(value) => {
              setDraft({ ...draft, defaultSort: value as SortMode });
            }}
          >
            <SelectTrigger id="flags-sort" className="w-full sm:w-56">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="top">Top, by importance score</SelectItem>
              <SelectItem value="latest">Latest, strictly chronological</SelectItem>
            </SelectContent>
          </Select>
          <p className="text-xs text-muted-fg">
            What a fresh install opens on. A reader who changes the sort keeps their choice.
          </p>
        </div>

        <TextField
          label="Minimum mobile version"
          value={draft.minMobileVersion}
          disabled={saving}
          placeholder="1.2.0"
          hint="A semver string the mobile app compares against its own build. Leave empty for no minimum."
          onChange={(next) => {
            setDraft({ ...draft, minMobileVersion: next });
          }}
        />
      </section>

      {/* -- maintenance --------------------------------------------------- */}
      <section
        aria-labelledby="flags-maintenance"
        className="flex flex-col gap-4 rounded-xl border border-border bg-card p-5"
      >
        <div>
          <h2 id="flags-maintenance" className="text-sm font-semibold text-fg">
            Maintenance mode
          </h2>
          <p className="mt-1 text-xs text-muted-fg">
            While this is on, every content route answers 503 and both apps show the message below
            instead of the feed. GET /api/config keeps answering, which is how they know to.
          </p>
        </div>

        <SwitchField
          label="Maintenance mode"
          description="Takes the mobile app and the public web feed out of service."
          checked={draft.maintenanceMode}
          disabled={saving}
          onCheckedChange={(next) => {
            setDraft({ ...draft, maintenanceMode: next });
          }}
        />

        <TextAreaField
          label="Maintenance message"
          value={draft.maintenanceMessage}
          rows={3}
          disabled={saving}
          placeholder="FinBit is briefly offline for maintenance. Please check back shortly."
          hint="Shown to every reader. Say what is happening and roughly when it ends."
          onChange={(next) => {
            setDraft({ ...draft, maintenanceMessage: next });
          }}
        />
      </section>

      <ConfirmAction
        open={confirming}
        onOpenChange={setConfirming}
        title={draft.maintenanceMode ? 'Save with maintenance mode on?' : 'Turn maintenance off?'}
        confirmLabel={draft.maintenanceMode ? 'Save and keep it on' : 'Save and go live'}
        destructive={draft.maintenanceMode}
        description={
          draft.maintenanceMode ? (
            <>
              <p>
                Saving this leaves maintenance mode on. Every reader on mobile and on the web will
                see the maintenance message instead of the feed until it is turned off.
              </p>
              <p className="mt-2">
                Message:{' '}
                {orNull(draft.maintenanceMessage) ??
                  'none set, so the apps will show their own fallback copy.'}
              </p>
            </>
          ) : (
            <p>
              This turns maintenance mode off and puts the feed back in front of every reader
              immediately.
            </p>
          )
        }
        onConfirm={() => {
          void save();
        }}
      />
    </div>
  );
}
