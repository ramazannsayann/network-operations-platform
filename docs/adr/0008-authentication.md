# ADR-0008: Authentication, MFA, authorization and audit (M7)

- **Status:** Accepted
- **Date:** 2026-10-11
- **Deciders:** project team (4 members)

## Context

Proposal section 7.7 makes the platform's own protection a requirement: it holds the
credentials of the whole network (ADR-0004), so a stolen session is a stolen network.
It asks for JWT sessions, roles (Admin / Operator / Read-only) and an append-only audit
log of every write. ADR-0003 declared a bearer scheme on every endpoint but checked
nothing. Step 9 adds sign-in with passwords and TOTP, sessions, role-based authorization
on every route, the audit log, and the administration of users and credential profiles.

## Decision

### Accounts and bootstrap

- Local users (`users`): a lower-case unique username, display name, email, role
  (`admin`, `operator`, `viewer`), active flag. Users are deactivated, never deleted (the
  audit log keeps referring to them). The last active admin cannot be demoted or
  deactivated.
- **No default account exists.** The first admin is created on the server:
  `docker compose exec api netops users create-admin` asks for the username and the
  password (hidden, twice, never echoed). It refuses while an active admin exists, unless
  `--force` is given and confirmed. Further users are created by admins in the UI
  (Kullanıcılar) or with `netops users create`; their password is temporary and must be
  changed at the first sign-in.

### Passwords

- **argon2id** (argon2-cffi, its RFC 9106 "low memory" profile: t=3, m=64 MiB, p=4).
  A hash made with weaker parameters is replaced at the next successful sign-in.
- Policy in the spirit of NIST SP 800-63B, without composition rules: 12 to 256
  characters; not a common password from the bundled list
  (`backend/src/netops/auth/common_passwords.txt`), also after lower-casing, stripping
  digits and symbols from the ends, undoing look-alike characters (`P@ssw0rd2026!`) and
  repetition (`netopsnetops`); not a run of one or two characters or a keyboard/alphabet
  sequence; not containing the username or name. The bundled list is short (about 250
  entries written for the project: the top of published breach statistics plus Turkish
  and product-specific words); the length minimum already excludes most leaked passwords.
  A full breach corpus (e.g. an offline HIBP export) can replace the file later.
- Unknown users cost one argon2 computation too (against a dummy hash), and every login
  failure (unknown user, wrong password, locked, deactivated) gets the same 401 and
  message. The audit log records the real reason.

### Sign-in and sessions

```
POST /auth/login {username, password}
 ├─ failure ─────────────► 401, the same for every reason (audited with the reason)
 ├─ MFA off ─────────────► 200 {status: authenticated, access_token, requirements}
 │                          + Set-Cookie netops_refresh (HttpOnly, SameSite=Strict,
 │                            Path=/api/v1/auth, Secure over HTTPS)
 └─ MFA on ──────────────► 200 {status: mfa_required, mfa_challenge (JWT, 5 min)}
        POST /auth/mfa/verify {mfa_challenge, code | recovery_code}
          ─────────────────► 200 {access_token} + Set-Cookie netops_refresh
API calls:   Authorization: Bearer <access token, 15 min>
POST /auth/refresh (cookie) ─► new access token + a new refresh token (rotation);
                               an already used refresh token ends the whole session
POST /auth/logout ──────────► the session's refresh tokens revoked, cookie cleared
```

- **Access tokens** are JWTs (HS256) with `iss`, `aud`, `sub` (user), `sid` (session),
  `iat`, `exp`, `jti` and `typ` (an MFA challenge is not an access token and vice versa),
  signed with `AUTH_SIGNING_KEY` (one or more comma-separated keys of at least 32
  characters; the first signs, the `kid` header picks the verifying one, so keys rotate
  like `CREDENTIALS_KEY`). `make env` generates the key; the API refuses to start without
  one. The role is **not** in the token: every request loads the user and checks that
  the session is still active, so deactivation, logout, a revoked session and a role
  change take effect at once, not when the token expires.
- **Refresh tokens** are random strings stored as sha256 (`refresh_tokens`). All tokens
  descending from one sign-in form a family, the session. Each use rotates the token; a
  rotated token presented again means it was copied, so the family is revoked and the
  reuse audited. A token lives 12 hours unless used (`AUTH_REFRESH_TOKEN_HOURS`), a
  session at most 7 days (`AUTH_SESSION_MAX_DAYS`). Users see and end their own sessions
  (Profilim).
- The **browser** keeps the access token in memory only (never in storage, a cookie or
  a URL) and refreshes it a minute before it expires; a reload starts from the refresh
  cookie. Refreshes are serialized across tabs with the Web Locks API: two tabs rotating
  the same token at once would look like theft and end the session. A 401 on any other
  call sends the user to the sign-in page.
- The cookie's `Secure` flag follows the request scheme (`AUTH_COOKIE_SECURE=auto`); in
  production the platform runs behind HTTPS (proposal 7.7: the institution's internal
  CA), where it is set. `SameSite=Strict` and the path scope keep the cookie away from
  cross-site requests and from every endpoint but the auth ones.

### MFA (TOTP, RFC 6238)

- SHA-1, 6 digits, 30-second steps (what every authenticator app supports); a code is
  accepted for the current step and one either side, and only for a step later than the
  last one used (`users.mfa_last_used_step`), so an observed code cannot be replayed.
- The secret is stored Fernet-encrypted with `CREDENTIALS_KEY`. Enrollment returns it as
  text, as an `otpauth://` URI and as a QR code drawn on the server (segno), so no third
  party sees it. MFA is on only after a first code confirms the secret; then ten
  single-use recovery codes (about 50 bits each, stored as sha256) are shown once.
- Policy: `AUTH_MFA_REQUIRED_ROLES` (default `admin,operator`); viewers may opt in. A
  session of a user who must enroll (or change a temporary password) can only use its
  own account (`profile:self`) until it has; the UI sends it to the setup page. Users
  turn MFA off with their password and a code (where their role requires MFA, this means
  setting it up again at once, e.g. on a new phone); admins reset it (lost phone), which
  also ends the user's sessions. Both are audited.

### Brute force

- Per account: from 5 consecutive failures (passwords and MFA codes alike) the account is
  locked for 60 s, doubling with every further failure up to an hour; each lock is
  audited. With MFA on, a correct password alone does not reset the counter, so knowing
  the password buys no unlimited code guessing. Admins can unlock.
- Per client address: 30 attempts per 5 minutes on login and on MFA verification
  (separately), in Redis (`AUTH_RATE_LIMIT_*`); then 429 with `Retry-After`, audited. If
  Redis is down the limiter lets requests through (logged) and the lockout remains.
- nginx now forwards only the client's own address in `X-Forwarded-For` (it appended a
  client-supplied header before), which the rate limit and the audit log rely on.
  uvicorn trusts proxy headers from any peer; the API port is published on 127.0.0.1
  only, so only the host could forge them.

### Authorization (RBAC)

Permissions and their roles live in one module (`netops.auth.rbac`):

| Permission | viewer | operator | admin |
| --- | :-: | :-: | :-: |
| `devices:read`, `topology:read`, `discovery:read`, `configs:read`, `events:read`, `metrics:read`, `alarms:read`, `diagnosis:read`, `locations:read`, `jobs:read` | ✓ | ✓ | ✓ |
| `profile:self` (own account, password, MFA, sessions, logout) | ✓ | ✓ | ✓ |
| `discovery:run`, `devices:refresh`, `configs:backup`, `topology:layout:write`, `alarms:ack` | | ✓ | ✓ |
| `credentials:read` (profile names, to choose them for a discovery) | | ✓ | ✓ |
| `credentials:manage`, `users:manage`, `audit:read`, `locations:manage` | | | ✓ |

- Every route declares exactly one permission with `guard(Permission.X)`: a dependency
  that authenticates the token, loads the user and session and checks the role, and an
  `x-required-permission` entry in the contract. The public routes are health, login,
  MFA verification and refresh. A test walks the route table and fails for any other
  route without a guard; a matrix test checks every role against every route (403 or
  not); a 403 for a route is audited (`access.denied`). Collecting `config` through
  `POST /devices/{id}/refresh` also needs `configs:backup`.
- The UI hides what a role cannot do (admin pages, refresh, backup, discovery, layout
  saving); the API enforces it regardless.

### Audit log

- `audit_log`: id (bigint identity), time, actor (user id; none for anonymous attempts
  and the server CLI), actor address, action, target type and id, outcome (`success`,
  `denied`, `failed`), details (JSON). **Append-only in the database:** triggers reject
  `UPDATE`, `DELETE` and `TRUNCATE` (a test proves all three fail). There is no foreign key
  to `users`, so not even `ON DELETE SET NULL` can change a row.
- Details never hold secrets: the writer refuses keys that name one (`password`, `secret`,
  `token`, `code`, `key`) and callers pass names, ids and counts. Entries of an action
  are written in the action's transaction; failures and denials in a transaction of
  their own, so they survive the failed request.
- Audited: sign-in success and failure (with the reason), MFA verification failures,
  lockouts, logout, refresh-token reuse, rate limiting, MFA enrollment, disable and admin
  reset, password changes, ended sessions, user creation, update (role changes with old
  and new role), deactivation, password reset and unlock, credential profile creation,
  update (changed field names only) and deletion, discovery start, device refresh,
  configuration backup, map layout saving, and every 403.
- Admins read it at `GET /api/v1/audit` and in the UI (Denetim kaydı), filtered by
  actor, action (prefixes like `auth.*`), target, outcome and time.
- **Retention** (not implemented): the application's database role owns the table and
  could disable the triggers, so they guard against mistakes and injected statements,
  not against the owner. A retention run is a separate maintenance procedure by a
  database administrator: in one transaction, `ALTER TABLE audit_log DISABLE TRIGGER
  audit_log_no_update_delete`, `DELETE FROM audit_log WHERE at < now() - interval '...'`,
  enable the trigger again, and insert an entry recording the purge; export the deleted
  rows first if they must be kept. Running the application under a role that does not
  own the table would close the gap.

### Credential profiles over the API

- Admins create, edit and delete profiles (`credentials:manage`). Secret fields
  (password, enable secret, SNMPv3 keys) are write-only: requests may carry them, no
  response does, not masked and not as a length; the detail only says whether an enable
  secret is stored. Changing a profile replaces a secret only when one is sent. A profile
  a device uses cannot be deleted. Operators list profile names (to choose them for a
  discovery run). `netops credentials add` uses the same audited code.

### The mock server

Prism answers `POST /auth/refresh` with the contract's example, so the UI under
`npm run dev:mock` opens signed in as the example operator. The smoke E2E test makes the
refresh fail in the browser to exercise the sign-in form and the MFA step.

## Not now

- **SSO and directories** (LDAP bind, SAML/OIDC with group-to-role mapping): future
  work; local accounts suffice for the pilot.
- **WebSocket authentication**: there is no WebSocket yet; `docs/api/websocket.md`
  already expects the access token in the first message.
- WebAuthn/passkeys, a full breach corpus for the password check, per-user map layouts,
  an approval permission for M5's change workflow.

## Consequences

- Every API call costs one indexed query for the user and session; in exchange,
  revocation is immediate.
- A stolen access token is usable for at most 15 minutes and only while its session
  lives; a stolen refresh token is detected at its next use (by either party).
- Losing `AUTH_SIGNING_KEY` signs everyone out (no data is lost); losing
  `CREDENTIALS_KEY` now also loses the TOTP secrets, so everyone enrolls again.
- The audit log grows without bound until a retention procedure is run.
