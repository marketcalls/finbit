/**
 * The discovery query editor, contract section 9.
 *
 * Nine queries drive every story the pipeline ever finds, so this is the single
 * most consequential form in the console: a prompt edited badly changes what
 * the feed is about. The editor is therefore fully controlled and saves nothing
 * by itself. PipelineScreen owns the draft, the dirty state and the PUT, which
 * is also what lets a save be rolled back to the last confirmed server copy.
 *
 * key and category_hint are shown but not editable. The key is how the API
 * identifies a query and how the rotation set names it, and the hint feeds the
 * pipeline's category assignment, which belongs to the ingest code rather than
 * to an operator. Both are still sent back untouched, because PUT replaces the
 * whole set (section 6.4) and dropping a field would erase it.
 */

import type { QueryDef } from '@finbit/shared';
import { Badge } from '../../components/ui/badge';
import { SwitchField, TextAreaField, TextField } from './Field';

export interface QueryEditorProps {
  queries: QueryDef[];
  onChange: (next: QueryDef[]) => void;
  disabled?: boolean;
}

export function QueryEditor({ queries, onChange, disabled }: QueryEditorProps): JSX.Element {
  function update(key: string, patch: Partial<QueryDef>): void {
    onChange(queries.map((query) => (query.key === key ? { ...query, ...patch } : query)));
  }

  return (
    <ul className="flex flex-col gap-4">
      {queries.map((query) => (
        <li
          key={query.key}
          className="flex flex-col gap-4 rounded-xl border border-border bg-card p-5"
        >
          <div className="flex flex-wrap items-center gap-2">
            <code className="rounded bg-muted px-2 py-1 text-xs text-muted-fg">{query.key}</code>
            <Badge variant="outline">{query.category_hint}</Badge>
            {!query.enabled ? <Badge variant="flat">not in rotation</Badge> : null}
          </div>

          <SwitchField
            label="Enabled"
            description="Off means this query is skipped when the scheduler rotates through the set."
            checked={query.enabled}
            disabled={disabled}
            onCheckedChange={(next) => {
              update(query.key, { enabled: next });
            }}
          />

          <TextField
            label="Label"
            value={query.label}
            disabled={disabled}
            onChange={(next) => {
              update(query.key, { label: next });
            }}
            hint="Shown in run logs and in this console. It does not reach the model."
          />

          <TextAreaField
            label="Prompt"
            value={query.prompt}
            rows={3}
            disabled={disabled}
            onChange={(next) => {
              update(query.key, { prompt: next });
            }}
            hint="The search task sent to the Perplexity Agent API for this slot."
          />
        </li>
      ))}
    </ul>
  );
}
