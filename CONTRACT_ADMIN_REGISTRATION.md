# FinBit Contract, phase 3: one-time admin registration

Addendum to `CONTRACT_MOBILE_ADMIN.md`. Read that file first; everything in it
still holds except where this file overrides it.

**This file is for the phase 3 build only.** The phase 2 agents did not see it.
Assume phase 2 shipped admin accounts that can only be created by the CLI, and that
`frontend/src/admin/AdminLogin.tsx` currently renders a sign-in form and nothing
else.

Writing style, unchanged: no emoji, no em dashes, no en dashes.

---

## 1. The rule

**There is exactly one admin account, for the life of the deployment.**

It is created once, through the browser, on first run. After that the registration
route does not exist. There is no invite flow, no second admin, no pending queue,
no user management screen and no roles. Anyone who needs access shares that one
account, or recovers it with the CLI.

This is deliberately narrow. Do not build a `users` screen. Do not add a `role`
column. Do not add an endpoint that creates a second admin.

---

## 2. Bootstrap token

While `admin_users` is empty, the API prints a one-time token at startup:

```
============================================================
  FinBit: no admin account exists.
  Open the web app at /#/admin and create it.
  Bootstrap token: 7Kq2-9fPx-Lm4w-Rt8v
  Valid for 30 minutes. Printed once per start.
============================================================
```

Rules:

- Generated with `secrets.token_urlsafe(18)`, then grouped into four dash-separated
  chunks purely for readability. Compare after stripping dashes and whitespace and
  lowercasing nothing: the comparison is on the normalized string, constant time
  via `hmac.compare_digest`.
- Held **in memory only**, on `app.state`. Never written to the database, never to
  a file, never returned by any endpoint.
- Expires 30 minutes after startup. An expired token fails exactly like a wrong one.
- Regenerated on every process start, but **only while no admin exists**. Once the
  account is created, startup prints nothing and generates nothing.
- Under `uvicorn --reload` this reprints on every code change. That is expected and
  harmless; note it in the docs so it does not look like a bug.
- The token is the only thing standing between a reachable port and someone else
  claiming the instance. Say that in `SECURITY.md`.

---

## 3. API changes

### 3.1 New: `GET /api/admin/auth/status`

Public, no auth, rate limited per IP at 30 per minute.

```json
{ "registration_open": true }
```

`registration_open` is true only when `admin_users` is empty. It reveals nothing
else: no username, no token, no hint about whether a token is currently valid.
The login screen uses it to decide which form to render.

### 3.2 New: `POST /api/admin/auth/register`

Works **only** while `admin_users` is empty.

```json
request  { "username": "…", "password": "…", "bootstrap_token": "7Kq2-9fPx-Lm4w-Rt8v" }
response 201 { "access_token": "…", "refresh_token": "…", "expires_in": 1800, "username": "…" }
```

Behavior:

- When an admin already exists, return **404** with
  `{"detail": "Not found", "code": "not_found"}`. Not 403. Do not confirm that the
  route exists once it is closed.
- Wrong or expired bootstrap token: 401 `{"code": "invalid_bootstrap_token"}`.
- Rate limit: 5 attempts per IP per hour, sharing the `ratelimit.py` token bucket.
  Exceeding it returns 429 `{"code": "rate_limited"}`.
- Username: 3 to 32 characters, `[A-Za-z0-9._-]` only, stored as given, compared
  case-insensitively.
- Password policy, enforced server-side and mirrored in the UI:
  minimum 12 characters, at least one letter and one digit, not equal to the
  username, and not in a small hardcoded denylist of obvious passwords. Return
  422 with a `code` of `weak_password` and a `detail` naming the specific rule that
  failed. It is the user's own new password, so being specific here is helpful, not
  a leak.
- **Race safety.** Two simultaneous registrations must not both succeed. Open the
  write with `BEGIN IMMEDIATE`, re-check `SELECT COUNT(*) FROM admin_users` inside
  the transaction, and only then insert. The loser gets the same 404 as any late
  caller.
- On success: invalidate the in-memory bootstrap token immediately, write an
  `audit_log` row with action `admin.register`, and return a signed-in session so
  the browser does not have to log in again.
- Never log the password, the token or the returned tokens. Log only
  `admin account created: <username>`.

### 3.3 New: `POST /api/admin/auth/change-password`

Requires `CurrentAdmin`.

```json
request  { "current_password": "…", "new_password": "…" }
response 204
```

Verifies the current password, applies the same policy to the new one, rehashes,
revokes every existing admin refresh token so other sessions are signed out, and
writes an `audit_log` row with action `admin.change_password`.

### 3.4 Changed: `app/admin_cli.py`

- `create-admin` must now **refuse** when an admin already exists, printing
  "An admin account already exists. Use reset-password instead." and exiting 1.
- `reset-password` stays, unchanged. It is the only recovery path once registration
  has closed, so the docs must point at it.
- `list-admins` stays.

### 3.5 Unchanged

`ADMIN_BOOTSTRAP_USERNAME` and `ADMIN_BOOTSTRAP_PASSWORD` keep working exactly as
phase 2 built them. When both are set and no admin exists, startup creates that
account, and then registration is closed on the first request because the table is
no longer empty. In that case the bootstrap token is never printed.

---

## 4. Web changes

`frontend/src/admin/AdminLogin.tsx` becomes a gate with two faces, chosen by
`GET /api/admin/auth/status` on mount. Show a skeleton while that call is in
flight; never flash the wrong form.

**Registration face** (`registration_open: true`), headed "Create the admin
account":

- Fields: username, password, confirm password, bootstrap token.
- Under the token field, the helper text: "Printed in the API server console when
  it started."
- Live password rule checklist that ticks off as the rules are met. It is advisory;
  the server is the authority.
- A short line stating this is a one-time setup and that no further accounts can be
  created afterwards.
- On success, store the returned session and go straight to the dashboard. Do not
  bounce through the login form.

**Login face** (`registration_open: false`): the sign-in form phase 2 already built,
unchanged.

Also add:

- An account section in `AdminShell` with the signed-in username and a
  "Change password" dialog wired to `POST /api/admin/auth/change-password`. On
  success, sign out and show the login form with a note that other sessions ended.
- If `register` returns 404 because someone else won the race, swap to the login
  face and show "An admin account already exists. Sign in instead."

Use only the shadcn primitives phase 2 installed under
`frontend/src/components/ui/`. Do not add packages.

---

## 5. Tests

Extend `backend/tests/test_admin.py`, or add `backend/tests/test_admin_register.py`.

- `status` reports true on an empty table and false once an admin exists.
- Registration succeeds exactly once. The second attempt returns 404, with the same
  body as any unknown route.
- A wrong bootstrap token returns 401 and does not create an account.
- An expired bootstrap token returns 401.
- Every password policy rule is rejected with `weak_password`, and a valid password
  is accepted.
- Concurrent registration: simulate two calls inside the same transaction window and
  assert exactly one account exists afterwards.
- After registration the returned tokens work against a protected admin route.
- `change-password` rejects a wrong current password, enforces the policy, and
  revokes existing refresh tokens.
- `create-admin` in the CLI refuses when an account exists.
- The `audit_log` gained an `admin.register` row.

---

## 6. Docs

`README.md`: replace the "create the first admin with the CLI" step with the
first-run browser flow. Give the startup banner, say where the token appears, and
note that `--reload` reprints it on every save while no admin exists. Keep the CLI
documented as the recovery path for a forgotten password.

`SECURITY.md`: add a bootstrap section covering the one-account rule, the token's
in-memory lifetime, the 404-not-403 choice and why, the race-safety guarantee, the
rate limit, and this warning: **create the admin account before exposing the API on
a tunnel or a forwarded port.** Until it exists, anyone who can reach the port and
read the token owns the console.
