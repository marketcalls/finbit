/**
 * The three form rows the admin screens build every settings panel out of.
 *
 * They exist to keep the label, the hint and the control wired together in one
 * place: every control gets a real id, every Label points at it, and every hint
 * is referenced by aria-describedby, so the accessible name and description are
 * correct without each screen remembering to do it.
 *
 * NumberField holds the typed text itself rather than reflecting the numeric
 * value straight back. A controlled number input that renders String(value) on
 * every keystroke cannot be cleared: deleting the last digit produces an empty
 * string, which parses to nothing, which snaps the field back to the old value
 * mid-edit. Keeping the text while the field has focus, and clamping on blur,
 * is what makes it behave like an ordinary input.
 */

import { useEffect, useId, useState } from 'react';
import type { ReactNode } from 'react';

import { Input } from '../../components/ui/input';
import { Label } from '../../components/ui/label';
import { Switch } from '../../components/ui/switch';
import { Textarea } from '../../components/ui/textarea';

function Hint({ id, children }: { id: string; children: ReactNode }): JSX.Element {
  return (
    <p id={id} className="text-xs text-muted-fg">
      {children}
    </p>
  );
}

export interface TextFieldProps {
  label: string;
  value: string;
  onChange: (next: string) => void;
  hint?: ReactNode;
  placeholder?: string;
  disabled?: boolean;
  type?: 'text' | 'password' | 'url';
  autoComplete?: string;
}

/** A single line of text. */
export function TextField({
  label,
  value,
  onChange,
  hint,
  placeholder,
  disabled,
  type = 'text',
  autoComplete,
}: TextFieldProps): JSX.Element {
  const id = useId();
  const hintId = `${id}-hint`;

  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type={type}
        value={value}
        placeholder={placeholder}
        disabled={disabled}
        autoComplete={autoComplete}
        aria-describedby={hint ? hintId : undefined}
        onChange={(event) => {
          onChange(event.target.value);
        }}
      />
      {hint ? <Hint id={hintId}>{hint}</Hint> : null}
    </div>
  );
}

export interface TextAreaFieldProps {
  label: string;
  value: string;
  onChange: (next: string) => void;
  hint?: ReactNode;
  placeholder?: string;
  disabled?: boolean;
  rows?: number;
}

/** A multi line field, for a prompt or a maintenance message. */
export function TextAreaField({
  label,
  value,
  onChange,
  hint,
  placeholder,
  disabled,
  rows = 3,
}: TextAreaFieldProps): JSX.Element {
  const id = useId();
  const hintId = `${id}-hint`;

  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor={id}>{label}</Label>
      <Textarea
        id={id}
        value={value}
        rows={rows}
        placeholder={placeholder}
        disabled={disabled}
        aria-describedby={hint ? hintId : undefined}
        onChange={(event) => {
          onChange(event.target.value);
        }}
      />
      {hint ? <Hint id={hintId}>{hint}</Hint> : null}
    </div>
  );
}

export interface NumberFieldProps {
  label: string;
  value: number;
  onChange: (next: number) => void;
  min: number;
  max: number;
  hint?: ReactNode;
  suffix?: string;
  disabled?: boolean;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, Math.round(value)));
}

/** A whole number inside a fixed range, clamped on blur. */
export function NumberField({
  label,
  value,
  onChange,
  min,
  max,
  hint,
  suffix,
  disabled,
}: NumberFieldProps): JSX.Element {
  const id = useId();
  const hintId = `${id}-hint`;
  const [text, setText] = useState<string>(() => String(value));
  const [editing, setEditing] = useState(false);

  // Follow the model while the field is idle, so a reset or a reload lands,
  // but never while it has focus, where it would overwrite what is being typed.
  useEffect(() => {
    if (!editing) {
      setText(String(value));
    }
  }, [value, editing]);

  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor={id}>{label}</Label>
      <div className="flex items-center gap-2">
        <Input
          id={id}
          type="number"
          inputMode="numeric"
          value={text}
          min={min}
          max={max}
          step={1}
          disabled={disabled}
          className="max-w-32 tabular-nums"
          aria-describedby={hint ? hintId : undefined}
          onFocus={() => {
            setEditing(true);
          }}
          onChange={(event) => {
            const raw = event.target.value;
            setText(raw);
            const parsed = Number(raw);
            if (raw !== '' && Number.isFinite(parsed)) {
              onChange(clamp(parsed, min, max));
            }
          }}
          onBlur={() => {
            setEditing(false);
            const parsed = Number(text);
            const next = text === '' || !Number.isFinite(parsed) ? value : clamp(parsed, min, max);
            setText(String(next));
            onChange(next);
          }}
        />
        {suffix ? <span className="text-sm text-muted-fg">{suffix}</span> : null}
      </div>
      {hint ? <Hint id={hintId}>{hint}</Hint> : null}
    </div>
  );
}

export interface SwitchFieldProps {
  label: string;
  checked: boolean;
  onCheckedChange: (next: boolean) => void;
  description?: ReactNode;
  /** Rendered on the right, for example the time a flag last changed. */
  meta?: ReactNode;
  disabled?: boolean;
}

/**
 * A labelled switch row.
 *
 * The label sits beside the switch rather than above it so the pair reads as
 * one control, and the whole row is the label target, which gives the 44 px
 * combined touch area the contract asks for even though the switch is 24 px.
 */
export function SwitchField({
  label,
  checked,
  onCheckedChange,
  description,
  meta,
  disabled,
}: SwitchFieldProps): JSX.Element {
  const id = useId();
  const hintId = `${id}-hint`;

  return (
    <div className="flex min-h-11 items-center justify-between gap-4 py-1">
      <div className="flex flex-col gap-0.5">
        <Label htmlFor={id} className="cursor-pointer text-sm">
          {label}
        </Label>
        {description ? <Hint id={hintId}>{description}</Hint> : null}
      </div>
      <div className="flex shrink-0 items-center gap-3">
        {meta ? <span className="text-xs text-muted-fg tabular-nums">{meta}</span> : null}
        <Switch
          id={id}
          checked={checked}
          disabled={disabled}
          aria-describedby={description ? hintId : undefined}
          onCheckedChange={onCheckedChange}
        />
      </div>
    </div>
  );
}
