/**
 * Edit one story's copy, contract section 6.5.
 *
 * The four editable fields are the four the API accepts as free text plus the
 * category. Everything else on an article is derived (the score, the symbols,
 * the sources, the dedupe key) and is fixed by the pipeline rather than by an
 * operator, so it is not offered here at all: a field that looks editable but
 * would be overwritten on the next rescore is worse than no field.
 *
 * Only changed fields are sent. PATCH takes any subset, so an edit that only
 * touched the headline should not also rewrite the summary and stamp
 * moderated_by on a field nobody looked at.
 *
 * why_it_matters is nullable in the schema, so an emptied box sends null rather
 * than an empty string. Those are different values and the card renders them
 * differently.
 */

import { useEffect, useState } from 'react';
import { LoaderCircle } from 'lucide-react';

import {
  CATEGORIES,
  type AdminArticle,
  type AdminArticlePatch,
  type Category,
} from '@finbit/shared';
import { Button } from '../../components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../../components/ui/dialog';
import { Label } from '../../components/ui/label';
import { Input } from '../../components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../../components/ui/select';
import { Textarea } from '../../components/ui/textarea';
import { wordCountLabel } from './words';

/** Storable categories only: 'all' is a feed filter, never a stored value. */
const STORABLE_CATEGORIES = CATEGORIES.filter((option) => option.key !== 'all');

interface Draft {
  headline: string;
  summary: string;
  whyItMatters: string;
  category: Category;
}

function toDraft(article: AdminArticle): Draft {
  return {
    headline: article.headline,
    summary: article.summary,
    whyItMatters: article.why_it_matters ?? '',
    category: article.category,
  };
}

function buildPatch(draft: Draft, article: AdminArticle): AdminArticlePatch {
  const patch: AdminArticlePatch = {};
  if (draft.headline !== article.headline) {
    patch.headline = draft.headline;
  }
  if (draft.summary !== article.summary) {
    patch.summary = draft.summary;
  }
  const nextWhy = draft.whyItMatters.trim() === '' ? null : draft.whyItMatters;
  if (nextWhy !== article.why_it_matters) {
    patch.why_it_matters = nextWhy;
  }
  if (draft.category !== article.category) {
    patch.category = draft.category;
  }
  return patch;
}

export interface ArticleEditDialogProps {
  /** The story being edited. Null closes the dialog. */
  article: AdminArticle | null;
  onOpenChange: (open: boolean) => void;
  /** Resolves true when the save landed, so the dialog knows to close. */
  onSave: (articleId: number, patch: AdminArticlePatch) => Promise<boolean>;
}

export function ArticleEditDialog({
  article,
  onOpenChange,
  onSave,
}: ArticleEditDialogProps): JSX.Element {
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setDraft(article === null ? null : toDraft(article));
    setSaving(false);
  }, [article]);

  const patch = article !== null && draft !== null ? buildPatch(draft, article) : {};
  const dirty = Object.keys(patch).length > 0;

  async function submit(): Promise<void> {
    if (article === null || !dirty) {
      return;
    }
    setSaving(true);
    const ok = await onSave(article.id, patch);
    setSaving(false);
    if (ok) {
      onOpenChange(false);
    }
  }

  return (
    <Dialog open={article !== null} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Edit story</DialogTitle>
          <DialogDescription>
            Changes are published immediately and are stamped with your username.
          </DialogDescription>
        </DialogHeader>

        {draft !== null ? (
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor="edit-headline">Headline</Label>
              <Input
                id="edit-headline"
                value={draft.headline}
                disabled={saving}
                onChange={(event) => {
                  setDraft({ ...draft, headline: event.target.value });
                }}
              />
            </div>

            <div className="flex flex-col gap-2">
              <Label htmlFor="edit-summary">Summary</Label>
              <Textarea
                id="edit-summary"
                rows={5}
                value={draft.summary}
                disabled={saving}
                aria-describedby="edit-summary-hint"
                onChange={(event) => {
                  setDraft({ ...draft, summary: event.target.value });
                }}
              />
              <p id="edit-summary-hint" className="text-xs text-muted-fg">
                {wordCountLabel(draft.summary)}. The house style is 50 to 80 words.
              </p>
            </div>

            <div className="flex flex-col gap-2">
              <Label htmlFor="edit-why">Why it matters</Label>
              <Textarea
                id="edit-why"
                rows={3}
                value={draft.whyItMatters}
                disabled={saving}
                aria-describedby="edit-why-hint"
                onChange={(event) => {
                  setDraft({ ...draft, whyItMatters: event.target.value });
                }}
              />
              <p id="edit-why-hint" className="text-xs text-muted-fg">
                One or two sentences on the read-through for Indian markets. Leave empty to clear it.
              </p>
            </div>

            <div className="flex flex-col gap-2">
              <Label htmlFor="edit-category">Category</Label>
              <Select
                value={draft.category}
                disabled={saving}
                onValueChange={(value) => {
                  setDraft({ ...draft, category: value as Category });
                }}
              >
                <SelectTrigger id="edit-category" className="w-full sm:w-56">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {STORABLE_CATEGORIES.map((option) => (
                    <SelectItem key={option.key} value={option.key}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        ) : null}

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            disabled={saving}
            onClick={() => {
              onOpenChange(false);
            }}
          >
            Cancel
          </Button>
          <Button
            type="button"
            disabled={!dirty || saving}
            onClick={() => {
              void submit();
            }}
          >
            {saving ? <LoaderCircle aria-hidden="true" className="animate-spin" /> : null}
            Save changes
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
