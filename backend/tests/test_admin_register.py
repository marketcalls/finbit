"""The one-time admin registration (CONTRACT_ADMIN_REGISTRATION.md section 5).

Exactly one admin account exists for the life of a deployment, and until it
exists anyone who can reach the port and read the server console owns the
instance. That makes this the highest value route in the API, so the tests here
are written against the three ways it could give the instance away rather than
against its happy path.

The first is a second account. Registration has to succeed once and never
again, including when two callers arrive at the same moment, so the race is
driven with real threads through repo.create_first_admin and the transaction is
left alone: a test that mocks the transaction away would pass against an
implementation that counts outside the write lock, which is the exact bug the
BEGIN IMMEDIATE is there to prevent.

The second is the route admitting it is there. Once the account exists this
path must be indistinguishable from one that was never mounted, so the closed
answer is compared byte for byte against a genuinely unknown path, and it is
compared again with both rate limit buckets drained: a 429 from a closed route
would say the route is real, which is why the budgets are spent inside the
handler rather than in a dependency.

The third is the token. A wrong token, an expired token and no token at all
have to be one answer with one body, and none of them may leave a row behind.
The expired case presents the exact string the live token carries, so the only
thing separating it from a success is the expiry.

Nothing here asserts on a clock. Where equal treatment matters it is checked by
comparing response bodies, because a timing assertion in a test suite is a
flake on a busy machine and proves nothing on a fast one.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import admin_cli, repo
from app.routers import admin_auth
from app.security import bootstrap, passwords, ratelimit, tokens, utc_now
from tests.conftest import (
    HEADER_TEST_UNSIGNED,
    SignedClient,
    audit_rows,
    drain_bucket,
)

STATUS = "/api/admin/auth/status"
REGISTER = "/api/admin/auth/register"
LOGIN = "/api/admin/auth/login"
REFRESH = "/api/admin/auth/refresh"
CHANGE_PASSWORD = "/api/admin/auth/change-password"
ME = "/api/admin/auth/me"

# A path under the same prefix that was never mounted. The closed registration
# route has to answer exactly what this answers.
UNKNOWN = "/api/admin/auth/no-such-route"

# The account name carries a digit on purpose. The policy checks the length,
# then a letter, then a digit, and only then whether the password equals the
# username, so a name without a digit could never reach that fourth rule and
# the test for it would be checking the third one instead.
USERNAME = "finbit-admin1"
PASSWORD = "finbit-desk-2026"
WRONG_PASSWORD = "finbit-desk-2025"
NEW_PASSWORD = "finbit-desk-2027"

RIVAL_USERNAME = "finbit-rival2"

WRONG_TOKEN = "not-the-token-this-api-printed"

# One case per rule in app/security/passwords.py, in the order the policy
# evaluates them. Each one breaks exactly the rule it is named for and passes
# every rule above it, so a failure names the rule that actually regressed.
POLICY_REJECTIONS: tuple[tuple[str, str, str], ...] = (
    ("too short", "finbit-2026", passwords.TOO_SHORT),
    ("no letter", "192837465012", passwords.NEEDS_LETTER),
    ("no digit", "finbit-desk-password", passwords.NEEDS_DIGIT),
    ("the username", USERNAME, passwords.SAME_AS_USERNAME),
    ("too common", "password1234", passwords.TOO_COMMON),
)
POLICY_IDS = [name for name, _password, _detail in POLICY_REJECTIONS]

# Section 3.2: three to thirty two characters, letters, digits, dots,
# underscores and hyphens only.
INVALID_USERNAMES: tuple[tuple[str, str], ...] = (
    ("too short", "ab"),
    ("too long", "f" * 33),
    ("a space", "finbit admin"),
)
USERNAME_IDS = [name for name, _value in INVALID_USERNAMES]


def unsigned() -> dict[str, str]:
    """Headers for an admin call: bearer only, never a device signature."""
    return {HEADER_TEST_UNSIGNED: "1"}


def live_token(client: TestClient) -> bootstrap.BootstrapToken:
    """The token the lifespan minted on this client's empty database."""
    token = bootstrap.current(client.app.state)
    assert token is not None, "startup did not mint a bootstrap token"
    return token


def register(
    client: TestClient,
    *,
    username: str = USERNAME,
    password: str = PASSWORD,
    bootstrap_token: str | None = None,
) -> Any:
    """One registration attempt. Defaults to the live token and a valid pair."""
    presented = (
        live_token(client).value if bootstrap_token is None else bootstrap_token
    )
    return client.post(
        REGISTER,
        json={
            "username": username,
            "password": password,
            "bootstrap_token": presented,
        },
        headers=unsigned(),
    )


def unknown_route(client: TestClient) -> Any:
    """The same call against a path that does not exist, for the comparison."""
    return client.post(
        UNKNOWN,
        json={
            "username": USERNAME,
            "password": PASSWORD,
            "bootstrap_token": WRONG_TOKEN,
        },
        headers=unsigned(),
    )


def login(client: TestClient, username: str, password: str) -> Any:
    """One sign in attempt through the phase 2 route."""
    return client.post(
        LOGIN,
        json={"username": username, "password": password},
        headers=unsigned(),
    )


def refresh(client: TestClient, refresh_token: str) -> Any:
    """One admin refresh attempt."""
    return client.post(
        REFRESH, json={"refresh_token": refresh_token}, headers=unsigned()
    )


def failure(response: Any) -> tuple[int, str]:
    """The status and the contract code of a refused request."""
    body = response.json()
    assert set(body) == {"detail", "code"}, body
    return response.status_code, body["code"]


@dataclass(frozen=True)
class Session:
    """The signed in admin that registration hands back."""

    client: TestClient
    username: str
    access_token: str
    refresh_token: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}", **unsigned()}


@pytest.fixture()
def registered(api_client: TestClient) -> Session:
    """The one admin account, created the way an operator creates it."""
    response = register(api_client)
    assert response.status_code == 201, response.text
    body = response.json()
    return Session(
        client=api_client,
        username=body["username"],
        access_token=body["access_token"],
        refresh_token=body["refresh_token"],
    )


def change_password(session: Session, current: str, new: str) -> Any:
    """One password change attempt on a signed in session."""
    return session.client.post(
        CHANGE_PASSWORD,
        json={"current_password": current, "new_password": new},
        headers=session.headers,
    )


# ---------------------------------------------------------------------------
# Status (section 3.1)
# ---------------------------------------------------------------------------


def test_status_is_open_while_the_table_is_empty(api_client: TestClient) -> None:
    response = api_client.get(STATUS, headers=unsigned())
    assert response.status_code == 200
    assert response.json() == {"registration_open": True}


def test_status_closes_the_moment_an_account_exists(api_client: TestClient) -> None:
    """The login screen picks its face from this one boolean."""
    assert api_client.get(STATUS, headers=unsigned()).json()["registration_open"]

    admin_cli.create_admin(USERNAME, PASSWORD)

    response = api_client.get(STATUS, headers=unsigned())
    assert response.status_code == 200
    assert response.json() == {"registration_open": False}


def test_status_carries_one_field_and_never_the_token(
    api_client: TestClient,
) -> None:
    """A second field here would be a hint about an unclaimed instance."""
    token = live_token(api_client)
    response = api_client.get(STATUS, headers=unsigned())
    assert set(response.json()) == {"registration_open"}
    assert token.value not in response.text
    assert token.display not in response.text


def test_status_is_rate_limited_per_ip(api_client: TestClient) -> None:
    """Thirty a minute, so the screen cannot be used to poll for the moment
    an instance comes up unclaimed."""
    drain_bucket(admin_auth.SCOPE_ADMIN_AUTH_STATUS, "testclient")
    response = api_client.get(STATUS, headers=unsigned())
    assert failure(response) == (429, ratelimit.RATE_LIMITED_CODE)
    assert response.headers.get("Retry-After")


# ---------------------------------------------------------------------------
# Registration succeeds exactly once (section 3.2)
# ---------------------------------------------------------------------------


def test_registration_creates_the_account_and_returns_a_session(
    api_client: TestClient,
) -> None:
    """A valid password is accepted and the browser is signed in already."""
    response = register(api_client)
    assert response.status_code == 201, response.text

    body = response.json()
    assert set(body) == {"access_token", "refresh_token", "expires_in", "username"}
    assert body["username"] == USERNAME
    assert body["expires_in"] == tokens.ADMIN_ACCESS_TTL_SECONDS
    assert repo.admin_account_count() == 1
    assert repo.registration_open() is False


def test_the_second_registration_answers_as_an_unknown_route(
    api_client: TestClient,
) -> None:
    """Byte for byte, so a closed route cannot be told from an unmounted one.

    The second attempt presents the token that worked a moment ago, which is
    the strongest form of the check: the row count runs before the token is
    read, so even the caller who created the account cannot use it again.
    """
    claimed = live_token(api_client).value
    assert register(api_client, bootstrap_token=claimed).status_code == 201

    closed = register(
        api_client, username=RIVAL_USERNAME, bootstrap_token=claimed
    )
    unknown = unknown_route(api_client)

    assert closed.status_code == unknown.status_code == 404
    assert closed.content == unknown.content
    assert closed.json() == {
        "detail": admin_auth.NOT_FOUND_DETAIL,
        "code": admin_auth.CODE_NOT_FOUND,
    }
    assert repo.admin_account_count() == 1


def test_a_closed_route_is_not_rate_limited(api_client: TestClient) -> None:
    """Both budgets are spent inside the handler, after the row count.

    A dependency level 429 would answer a drained bucket differently from an
    unknown path, and that difference is all an attacker needs to learn the
    route exists.
    """
    admin_cli.create_admin(USERNAME, PASSWORD)
    drain_bucket(ratelimit.SCOPE_IP, "testclient")
    drain_bucket(admin_auth.SCOPE_ADMIN_REGISTER, "testclient")

    closed = register(api_client, bootstrap_token=WRONG_TOKEN)
    unknown = unknown_route(api_client)

    assert closed.status_code == unknown.status_code == 404
    assert closed.content == unknown.content


def test_registration_drops_the_bootstrap_token(api_client: TestClient) -> None:
    """It cannot mint a second account inside its own thirty minute window."""
    assert live_token(api_client) is not None
    assert register(api_client).status_code == 201
    assert bootstrap.current(api_client.app.state) is None


def test_registration_writes_an_admin_register_audit_row(
    api_client: TestClient,
) -> None:
    assert audit_rows(admin_auth.ACTION_REGISTER) == []
    assert register(api_client).status_code == 201

    rows = audit_rows(admin_auth.ACTION_REGISTER)
    assert len(rows) == 1
    assert rows[0]["actor"] == USERNAME
    assert rows[0]["target"] == USERNAME
    assert rows[0]["ip"] == "testclient"
    assert rows[0]["at"].endswith("Z")


def test_the_registered_tokens_open_a_protected_admin_route(
    registered: Session,
) -> None:
    """Section 3.2 returns a session so the browser goes straight in."""
    response = registered.client.get(ME, headers=registered.headers)
    assert response.status_code == 200
    assert response.json()["username"] == USERNAME


def test_the_registered_refresh_token_rotates_once(registered: Session) -> None:
    rotated = refresh(registered.client, registered.refresh_token)
    assert rotated.status_code == 200
    assert rotated.json()["refresh_token"] != registered.refresh_token

    reused = refresh(registered.client, registered.refresh_token)
    assert failure(reused) == (401, tokens.INVALID_REFRESH_CODE)


def test_registration_never_echoes_the_password_or_the_token(
    api_client: TestClient,
) -> None:
    token = live_token(api_client)
    response = register(api_client)
    assert response.status_code == 201

    for text in (response.text, str(audit_rows())):
        assert PASSWORD not in text
        assert token.value not in text
        assert token.display not in text
        assert "argon2" not in text


def test_the_username_is_stored_lowercased_and_signs_in_either_way(
    api_client: TestClient,
) -> None:
    """Phase 2 lowercases before it looks a row up, so a mixed case row would
    be an account that could never sign in. The returned value is the name."""
    response = register(api_client, username="FinBit-Admin1")
    assert response.status_code == 201
    assert response.json()["username"] == USERNAME

    assert login(api_client, "FINBIT-ADMIN1", PASSWORD).status_code == 200
    assert login(api_client, USERNAME, PASSWORD).status_code == 200


# ---------------------------------------------------------------------------
# The bootstrap token (section 2)
# ---------------------------------------------------------------------------


def test_a_wrong_bootstrap_token_creates_nothing(api_client: TestClient) -> None:
    response = register(api_client, bootstrap_token=WRONG_TOKEN)
    assert failure(response) == (401, admin_auth.CODE_INVALID_BOOTSTRAP_TOKEN)
    assert repo.admin_account_count() == 0
    assert repo.registration_open() is True
    assert api_client.get(STATUS, headers=unsigned()).json()["registration_open"]


def test_an_expired_token_is_indistinguishable_from_a_wrong_one(
    api_client: TestClient,
) -> None:
    """The presented string is the live one, so only the expiry differs."""
    live = live_token(api_client)
    wrong = register(api_client, bootstrap_token=WRONG_TOKEN)

    lapsed = utc_now() - timedelta(seconds=bootstrap.TOKEN_TTL_SECONDS + 60)
    bootstrap.store(
        api_client.app.state,
        bootstrap.BootstrapToken(
            value=live.value,
            issued_at=lapsed,
            expires_at=lapsed + timedelta(seconds=bootstrap.TOKEN_TTL_SECONDS),
        ),
    )
    expired = register(api_client, bootstrap_token=live.value)

    assert expired.status_code == wrong.status_code == 401
    assert expired.content == wrong.content
    assert expired.json()["code"] == admin_auth.CODE_INVALID_BOOTSTRAP_TOKEN
    assert repo.admin_account_count() == 0


def test_no_token_at_all_is_refused_the_same_way(api_client: TestClient) -> None:
    """A process that never minted one must not answer differently."""
    wrong = register(api_client, bootstrap_token=WRONG_TOKEN)

    bootstrap.clear(api_client.app.state)
    absent = register(api_client, bootstrap_token=WRONG_TOKEN)

    assert absent.status_code == wrong.status_code == 401
    assert absent.content == wrong.content
    assert repo.admin_account_count() == 0


@pytest.mark.parametrize(
    "shape",
    ["value", "display", "padded"],
)
def test_the_token_is_accepted_however_it_was_pasted(
    api_client: TestClient, shape: str
) -> None:
    """The dashes are for reading it off a console, so they carry no meaning."""
    live = live_token(api_client)
    presented = {
        "value": live.value,
        "display": live.display,
        "padded": f"  {live.display}\n",
    }[shape]

    assert register(api_client, bootstrap_token=presented).status_code == 201
    assert repo.admin_account_count() == 1


def test_no_token_is_minted_once_an_account_exists(api_client: TestClient) -> None:
    """Section 2: a deployment that has its account prints nothing on start."""
    from app import main

    admin_cli.create_admin(USERNAME, PASSWORD)
    assert main.issue_bootstrap_token(api_client.app) is None
    assert bootstrap.current(api_client.app.state) is None


# ---------------------------------------------------------------------------
# The password policy (section 3.2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("password", "detail"),
    [(password, detail) for _name, password, detail in POLICY_REJECTIONS],
    ids=POLICY_IDS,
)
def test_registration_refuses_a_password_that_breaks_a_rule(
    api_client: TestClient, password: str, detail: str
) -> None:
    """Each case is its own test because the route allows five tries an hour."""
    response = register(api_client, password=password)
    assert failure(response) == (422, admin_auth.CODE_WEAK_PASSWORD)
    assert response.json()["detail"] == detail
    assert repo.admin_account_count() == 0


@pytest.mark.parametrize(
    "username",
    [value for _name, value in INVALID_USERNAMES],
    ids=USERNAME_IDS,
)
def test_registration_refuses_an_invalid_username(
    api_client: TestClient, username: str
) -> None:
    response = register(api_client, username=username)
    assert failure(response) == (422, admin_auth.CODE_INVALID_USERNAME)
    assert response.json()["detail"] == admin_auth.INVALID_USERNAME_DETAIL
    assert repo.admin_account_count() == 0


def test_a_bad_token_is_reported_before_the_username_and_the_password(
    api_client: TestClient,
) -> None:
    """A caller without the token never learns a username or password rule."""
    response = api_client.post(
        REGISTER,
        json={
            "username": "no",
            "password": "short",
            "bootstrap_token": WRONG_TOKEN,
        },
        headers=unsigned(),
    )
    assert failure(response) == (401, admin_auth.CODE_INVALID_BOOTSTRAP_TOKEN)


def test_the_username_is_reported_before_the_password(
    api_client: TestClient,
) -> None:
    response = register(api_client, username="no", password="short")
    assert failure(response) == (422, admin_auth.CODE_INVALID_USERNAME)


def test_registration_is_rate_limited_per_ip(api_client: TestClient) -> None:
    """Five an hour, so the token cannot be guessed at wire speed."""
    drain_bucket(admin_auth.SCOPE_ADMIN_REGISTER, "testclient")
    response = register(api_client)
    assert failure(response) == (429, ratelimit.RATE_LIMITED_CODE)
    assert response.headers.get("Retry-After")
    assert repo.admin_account_count() == 0


# ---------------------------------------------------------------------------
# The race (section 3.2)
# ---------------------------------------------------------------------------


def test_two_simultaneous_registrations_create_one_account() -> None:
    """Real threads, real transaction, two different names.

    The two names matter. If both callers asked for the same one, the UNIQUE
    constraint on username would refuse the second insert and the test would
    pass against an implementation that never re-counted inside the write
    transaction at all. With different names the only thing that can turn the
    loser back is the count taken while it holds the write lock.
    """
    password_hash = passwords.hash_password(PASSWORD)
    barrier = threading.Barrier(2)
    guard = threading.Lock()
    outcomes: list[bool] = []
    failures: list[BaseException] = []

    def attempt(username: str) -> None:
        try:
            barrier.wait(timeout=10)
            created = repo.create_first_admin(username, password_hash)
        except BaseException as exc:  # noqa: BLE001 - reported, not swallowed
            with guard:
                failures.append(exc)
            return
        with guard:
            outcomes.append(created)

    threads = [
        threading.Thread(target=attempt, args=(name,), name=f"register-{name}")
        for name in (USERNAME, RIVAL_USERNAME)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not [thread for thread in threads if thread.is_alive()]
    assert failures == [], failures
    assert sorted(outcomes) == [False, True]
    assert repo.admin_account_count() == 1

    rows = admin_cli.list_admins()
    assert len(rows) == 1
    assert rows[0].username in {USERNAME, RIVAL_USERNAME}


def test_a_row_that_appears_after_the_check_still_refuses_the_insert() -> None:
    """The deterministic half of the race: the guard is inside the write.

    An early exit that passed a moment ago is exactly the state the losing
    caller is in, and this is the call that has to notice.
    """
    assert repo.registration_open() is True
    admin_cli.create_admin(USERNAME, PASSWORD)

    created = repo.create_first_admin(
        RIVAL_USERNAME, passwords.hash_password(PASSWORD)
    )
    assert created is False
    assert repo.admin_account_count() == 1
    assert admin_cli.admin_exists(RIVAL_USERNAME) is False


def test_losing_the_race_answers_the_closed_route_404(
    api_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The loser gets the late caller's answer, never a 500.

    registration_open is forced true while a row exists, which is the state a
    caller is in when it passes the early exit a moment before someone else
    commits the account.
    """
    admin_cli.create_admin(USERNAME, PASSWORD)
    monkeypatch.setattr(repo, "registration_open", lambda: True)

    lost = register(api_client, username=RIVAL_USERNAME)
    unknown = unknown_route(api_client)

    assert lost.status_code == unknown.status_code == 404
    assert lost.content == unknown.content
    assert repo.admin_account_count() == 1


# ---------------------------------------------------------------------------
# Changing the password (section 3.3)
# ---------------------------------------------------------------------------


def test_change_password_refuses_a_wrong_current_password(
    api_client: TestClient, registered: Session
) -> None:
    """The same body the login route uses, so an access token is no oracle."""
    refused = change_password(registered, WRONG_PASSWORD, NEW_PASSWORD)
    assert failure(refused) == (401, admin_auth.CODE_INVALID_CREDENTIALS)
    assert refused.json() == login(api_client, USERNAME, WRONG_PASSWORD).json()

    # Nothing changed, so the account still opens with the password it had.
    assert login(api_client, USERNAME, PASSWORD).status_code == 200


def test_change_password_needs_an_admin_bearer(api_client: TestClient) -> None:
    response = api_client.post(
        CHANGE_PASSWORD,
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=unsigned(),
    )
    assert response.status_code == 401
    assert response.json()["code"] == "invalid_token"


def test_change_password_applies_the_same_policy(registered: Session) -> None:
    """Every rule, in one test: this route has no budget of its own."""
    for name, password, detail in POLICY_REJECTIONS:
        response = change_password(registered, PASSWORD, password)
        assert failure(response) == (422, admin_auth.CODE_WEAK_PASSWORD), name
        assert response.json()["detail"] == detail, name


def test_change_password_ends_every_admin_session(
    api_client: TestClient, registered: Session
) -> None:
    """Including the caller's own, which is the point of changing it."""
    second = login(api_client, USERNAME, PASSWORD)
    assert second.status_code == 200
    other_refresh = second.json()["refresh_token"]

    changed = change_password(registered, PASSWORD, NEW_PASSWORD)
    assert changed.status_code == 204
    assert changed.content == b""

    for spent in (registered.refresh_token, other_refresh):
        assert failure(refresh(api_client, spent)) == (
            401,
            tokens.INVALID_REFRESH_CODE,
        )

    assert login(api_client, USERNAME, PASSWORD).status_code == 401
    assert login(api_client, USERNAME, NEW_PASSWORD).status_code == 200


def test_change_password_writes_an_audit_row(registered: Session) -> None:
    assert audit_rows(admin_auth.ACTION_CHANGE_PASSWORD) == []
    assert change_password(registered, PASSWORD, NEW_PASSWORD).status_code == 204

    rows = audit_rows(admin_auth.ACTION_CHANGE_PASSWORD)
    assert len(rows) == 1
    assert rows[0]["actor"] == USERNAME
    assert rows[0]["ip"] == "testclient"


def test_change_password_never_echoes_a_password(registered: Session) -> None:
    refused = change_password(registered, WRONG_PASSWORD, NEW_PASSWORD)
    accepted = change_password(registered, PASSWORD, NEW_PASSWORD)

    for text in (refused.text, accepted.text, str(audit_rows())):
        assert PASSWORD not in text
        assert NEW_PASSWORD not in text
        assert WRONG_PASSWORD not in text


# ---------------------------------------------------------------------------
# The CLI (section 3.4)
# ---------------------------------------------------------------------------


def test_the_cli_refuses_to_create_a_second_admin(
    api_client: TestClient,
    registered: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """And refuses before it prompts, so the answer cannot depend on the name."""

    def never_prompt(_prompt: str = "") -> str:
        raise AssertionError("the CLI prompted before checking for an account")

    monkeypatch.setattr(admin_cli.getpass, "getpass", never_prompt)

    assert admin_cli.main(["create-admin", "--username", RIVAL_USERNAME]) == 1
    assert admin_cli.ADMIN_EXISTS_MESSAGE in capsys.readouterr().err
    assert admin_cli.admin_count() == 1
    assert admin_cli.admin_exists(RIVAL_USERNAME) is False


def test_the_cli_reset_password_is_still_the_recovery_path(
    api_client: TestClient,
    registered: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Once registration has closed this is the only way back in."""
    answers = iter([NEW_PASSWORD, NEW_PASSWORD])
    monkeypatch.setattr(
        admin_cli.getpass, "getpass", lambda _prompt="": next(answers)
    )

    assert admin_cli.main(["reset-password", "--username", USERNAME]) == 0
    assert login(api_client, USERNAME, NEW_PASSWORD).status_code == 200
    assert login(api_client, USERNAME, PASSWORD).status_code == 401


# ---------------------------------------------------------------------------
# The shared 404 body (section 3.2)
# ---------------------------------------------------------------------------


def test_a_route_that_owns_its_404_keeps_its_body(signed: SignedClient) -> None:
    """Only the unrouted 404 is reshaped.

    The handler that makes a closed registration route look unmounted sees
    every 404 in the application, so a route answering about a row it could not
    find has to come through it untouched.
    """
    response = signed.get("/api/articles/999999")
    assert response.status_code == 404
    assert response.json()["detail"] == "Article not found"
    assert response.json() != {
        "detail": admin_auth.NOT_FOUND_DETAIL,
        "code": admin_auth.CODE_NOT_FOUND,
    }
