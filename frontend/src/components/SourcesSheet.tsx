/**
 * The "Sources (n)" bottom sheet, MVP spec section 5 and contract section 11.
 *
 * A summary must never become an information dead end, so every original
 * publisher stays one tap away. This is a real modal dialog: focus moves inside
 * on open and returns to the trigger on close, Tab is trapped, Escape closes,
 * the backdrop closes, and page scrolling is locked while it is open. It is
 * rendered through a portal so a card with its own scroll container or stacking
 * context cannot clip it.
 */

import { useEffect, useId, useRef } from 'react';
import { createPortal } from 'react-dom';
import type { SourceRef } from '../api/types';
import { absoluteTime, relativeTime, sourceHost } from '../lib/format';
import { IconClose, IconExternal } from './Icons';

const FOCUSABLE_SELECTOR = 'a[href], button, input, select, textarea, [tabindex]';

function focusableInside(panel: HTMLElement): HTMLElement[] {
  return Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
    (element) => element.tabIndex >= 0 && !element.hasAttribute('disabled'),
  );
}

export interface SourcesSheetProps {
  open: boolean;
  onClose: () => void;
  headline: string;
  sources: SourceRef[];
}

export function SourcesSheet({ open, onClose, headline, sources }: SourcesSheetProps): JSX.Element {
  const panelRef = useRef<HTMLDivElement | null>(null);
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const headingId = useId();

  // Keep the latest onClose without re-running the open effect on every parent
  // render, which would otherwise steal focus back to the close button.
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!open) {
      return;
    }

    const previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const body = document.body;
    const previousOverflow = body.style.overflow;
    body.style.overflow = 'hidden';

    closeRef.current?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        // Stop here so a screen level key handler, such as the feed shortcuts,
        // does not also react to this key press.
        event.stopPropagation();
        onCloseRef.current();
        return;
      }

      if (event.key !== 'Tab') {
        return;
      }

      const panel = panelRef.current;
      if (!panel) {
        return;
      }

      const focusable = focusableInside(panel);
      if (focusable.length === 0) {
        event.preventDefault();
        panel.focus();
        return;
      }

      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;
      const inside = active instanceof HTMLElement && panel.contains(active);

      if (event.shiftKey) {
        if (!inside || active === first) {
          event.preventDefault();
          last.focus();
        }
        return;
      }

      if (!inside || active === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', onKeyDown, true);

    return () => {
      document.removeEventListener('keydown', onKeyDown, true);
      body.style.overflow = previousOverflow;
      if (previouslyFocused && document.contains(previouslyFocused)) {
        previouslyFocused.focus();
      }
    };
  }, [open]);

  if (!open) {
    return <></>;
  }

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center sm:p-4">
      {/*
        A real button rather than a div, per contract section 10. It is removed
        from the tab order and the accessibility tree because the close button
        in the header is the keyboard and screen reader path out of the sheet.
      */}
      <button
        type="button"
        tabIndex={-1}
        aria-hidden="true"
        onClick={onClose}
        className="absolute inset-0 h-full w-full cursor-default bg-bg/80 backdrop-blur-sm"
      />

      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={headingId}
        tabIndex={-1}
        className="relative flex max-h-[85dvh] w-full max-w-[480px] flex-col rounded-t-2xl border border-border bg-card shadow-2xl sm:max-h-[80dvh] sm:rounded-2xl"
      >
        <div className="flex items-start gap-2 border-b border-border px-4 py-3">
          <div className="min-w-0 flex-1">
            <h2 id={headingId} className="font-headline text-lg font-semibold text-fg">
              Sources ({sources.length})
            </h2>
            <p className="mt-0.5 line-clamp-2 text-sm text-muted-fg">{headline}</p>
          </div>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label="Close the sources list"
            className="inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-md text-muted-fg transition-colors duration-150 hover:bg-muted hover:text-fg"
          >
            <IconClose className="h-5 w-5" />
          </button>
        </div>

        {sources.length === 0 ? (
          <p className="px-4 py-10 text-center text-sm text-muted-fg">
            No source links were returned for this story.
          </p>
        ) : (
          <ul className="flex-1 overflow-y-auto overscroll-contain p-2">
            {sources.map((source, index) => {
              const host = sourceHost(source.url);
              const publisher = source.publisher.trim() !== '' ? source.publisher : host;
              const when = relativeTime(source.published_at);
              const secondary = source.title && source.title.trim() !== '' ? source.title : host;

              return (
                <li key={`${source.url}-${index}`}>
                  <a
                    href={source.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex min-h-14 items-center gap-3 rounded-lg px-2 py-2 transition-colors duration-150 hover:bg-muted"
                  >
                    <span className="min-w-0 flex-1">
                      <span className="flex items-baseline gap-2">
                        <span className="min-w-0 truncate text-sm font-medium text-fg">
                          {publisher}
                        </span>
                        {when !== '' ? (
                          <time
                            dateTime={source.published_at ?? undefined}
                            title={absoluteTime(source.published_at)}
                            className="shrink-0 text-xs text-muted-fg tnum"
                          >
                            {when}
                          </time>
                        ) : null}
                      </span>
                      <span className="mt-0.5 block truncate text-xs text-muted-fg">{secondary}</span>
                    </span>
                    <IconExternal className="h-4 w-4 shrink-0 text-muted-fg" />
                    <span className="sr-only">Opens in a new tab</span>
                  </a>
                </li>
              );
            })}
          </ul>
        )}

        <div className="border-t border-border px-4 py-3 pb-safe">
          <p className="text-xs leading-relaxed text-muted-fg">
            Every summary is written from these sources. AI assessment, not investment advice.
          </p>
        </div>
      </div>
    </div>,
    document.body,
  );
}
