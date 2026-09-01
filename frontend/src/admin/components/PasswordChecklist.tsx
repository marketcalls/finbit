/**
 * The live password rule checklist, registration contract sections 3.2 and 4.
 *
 * The rules below are a copy of the server's policy, and a copy can drift. That
 * is safe only because this list is advisory and never blocks a submission: the
 * API decides, and when it disagrees the screen shows the API's own sentence.
 * A checklist that could refuse a password the server would have accepted would
 * lock an operator out of their own instance over a rule this file got wrong,
 * which is a far worse failure than a tick appearing one keystroke early.
 *
 * The denylist is deliberately short. It exists to catch "password1234" while
 * someone is still typing, not to be the authority on obvious passwords, which
 * stays on the server where it can be extended without a rebuild.
 */

import { Check, Circle } from 'lucide-react';

import { cn } from '../../lib/utils';

/** Minimum length the API enforces. */
export const PASSWORD_MIN_LENGTH = 12;

/** Longest username the API accepts. */
const USERNAME_MAX_LENGTH = 32;

/** Characters the API forbids in a username: anything outside [A-Za-z0-9._-]. */
const FORBIDDEN_USERNAME_CHARACTER = /[^A-Za-z0-9._-]/;

/**
 * True when a username cannot become valid by typing more of it.
 *
 * Deliberately not "is this username valid". A field marked red because the
 * second of three characters has not been typed yet teaches people to ignore
 * the mark, so only a forbidden character or an over-long name is flagged; the
 * minimum length is left to the API, which is the authority anyway.
 */
export function usernameHasProblem(username: string): boolean {
  return username.length > USERNAME_MAX_LENGTH || FORBIDDEN_USERNAME_CHARACTER.test(username);
}

/** The plain hint under a username field, kept in one place for both forms. */
export const USERNAME_RULE_HINT =
  '3 to 32 characters. Letters, digits, dot, underscore and hyphen only.';

const OBVIOUS_PASSWORDS: ReadonlySet<string> = new Set([
  '123456789012',
  '1234567890ab',
  '1q2w3e4r5t6y',
  'abcd12345678',
  'administrator1',
  'admin1234567',
  'changeme1234',
  'finbit123456',
  'iloveyou1234',
  'letmein12345',
  'password1234',
  'passw0rd1234',
  'qwerty123456',
  'qwertyuiop12',
  'welcome12345',
]);

export interface PasswordRule {
  key: string;
  label: string;
  met: boolean;
}

/**
 * Score a candidate password against the mirrored policy.
 *
 * The username is compared case-insensitively because the API compares
 * usernames that way, so "Admin" and "admin" are the same account and the same
 * forbidden password.
 */
export function passwordRules(password: string, username: string): PasswordRule[] {
  const typed = password !== '';
  const normalizedUser = username.trim().toLowerCase();
  const normalizedPassword = password.trim().toLowerCase();

  return [
    {
      key: 'length',
      label: `At least ${PASSWORD_MIN_LENGTH} characters`,
      met: password.length >= PASSWORD_MIN_LENGTH,
    },
    {
      key: 'letter',
      label: 'Contains a letter',
      met: /[A-Za-z]/.test(password),
    },
    {
      key: 'digit',
      label: 'Contains a digit',
      met: /[0-9]/.test(password),
    },
    {
      key: 'distinct',
      label: 'Different from the username',
      met: typed && (normalizedUser === '' || normalizedPassword !== normalizedUser),
    },
    {
      key: 'not-obvious',
      label: 'Not a common password such as password1234',
      met: typed && !OBVIOUS_PASSWORDS.has(normalizedPassword),
    },
  ];
}

/** True when every mirrored rule is met. Advisory: never gate a submit on it. */
export function allRulesMet(rules: readonly PasswordRule[]): boolean {
  return rules.every((rule) => rule.met);
}

export interface PasswordChecklistProps {
  rules: readonly PasswordRule[];
  /** Referenced by the password input's aria-describedby. */
  id?: string;
  className?: string;
}

/**
 * The checklist itself.
 *
 * State is carried by the icon and by a visually hidden word, never by colour
 * alone, so it reads the same to someone who cannot tell the green tick from
 * the grey dot. It is not a live region: it changes on every keystroke, and
 * announcing five rules per character typed would make the field unusable with
 * a screen reader. The input's description points at it instead, so it is read
 * on focus and can be reread on demand.
 */
export function PasswordChecklist({ rules, id, className }: PasswordChecklistProps): JSX.Element {
  return (
    <ul id={id} className={cn('flex flex-col gap-1', className)}>
      {rules.map((rule) => (
        <li
          key={rule.key}
          className={cn(
            'flex items-center gap-2 text-xs transition-colors duration-150',
            rule.met ? 'text-bull' : 'text-muted-fg',
          )}
        >
          {rule.met ? (
            <Check aria-hidden="true" className="size-3.5 shrink-0" />
          ) : (
            <Circle aria-hidden="true" className="size-3.5 shrink-0" />
          )}
          <span>{rule.label}</span>
          <span className="sr-only">{rule.met ? ', met' : ', not met yet'}</span>
        </li>
      ))}
    </ul>
  );
}
