# ExamScan staff authentication

ExamScan's operator interface requires a registered staff account. Accounts,
password hashes, and revocable browser sessions are stored in the same MySQL
database as scan-session metadata. The Raspberry Pi's low-level hardware API is
not part of this authentication boundary and must remain on its private network.

## User flow

1. A staff member opens `/login` and enters their UCT ID.
2. **Email me a password** requests a random password for a matching active
   account. The response is deliberately identical for unknown, disabled, and
   registered IDs.
3. The emailed password is valid for 30 minutes before its first use.
4. A successful sign-in activates that password. It then remains valid until a
   later replacement is successfully used.
5. The browser receives an HttpOnly session cookie and the application keeps a
   CSRF token in memory. Closing the browser drops the cookie; an open session
   expires after eight hours without activity.

Requesting another password does not immediately invalidate the current one.
The replacement is stored as a pending Argon2id hash, so an unsolicited reset
email cannot lock a staff member out. When the replacement is used, all older
sessions are revoked.

## Roles

- `operator`: can use the scanner, sessions, review tools, downloads, and debug
  interface.
- `admin`: has all operator access and can open `/admin/users` to add, edit,
  activate/deactivate, and send passwords to staff.

The final active administrator cannot be deactivated or changed to an operator.
Deactivating any account revokes its sessions and pending password.

## Architecture and security decisions

- UCT IDs are trimmed and converted to uppercase before lookup.
- Passwords contain 16 random bytes encoded with `secrets.token_urlsafe`, which
  normally produces 22 printable characters.
- Argon2id uses a 64 MiB memory cost, three iterations, four lanes, a 32-byte
  hash, and a 16-byte random salt. The encoded hash includes its salt and
  parameters; plaintext passwords are never stored or logged.
- Five consecutive failures lock an account for 15 minutes. A password email
  can be requested once per account every five minutes, but does not shorten an
  active lockout.
- Session and CSRF values contain 32 random bytes. Only SHA-256 hashes of them
  are stored in MySQL.
- The `examscan_session` cookie is HttpOnly and SameSite=Lax. Set
  `AUTH_COOKIE_SECURE=true` whenever the frontend is served over HTTPS.
- Authenticated `POST`, `PUT`, `PATCH`, and `DELETE` requests must include the
  current `X-CSRF-Token` value. `GET /auth/me` restores the same per-session
  value when the UI reloads, so multiple tabs cannot invalidate one another.
- CORS accepts credentialed requests only from `FRONTEND_ORIGINS`; wildcard
  origins are not supported.

The only public routes are `GET /health`, `POST /auth/login`, and
`POST /auth/password/request`. Preflight `OPTIONS` requests are also allowed.
All scanner, document, session, PDF, archive, Pi-proxy, OpenAPI, and admin routes
require a valid staff session.

## Database tables

`users` contains the staff identity, role, active state, current and pending
Argon2 hashes, password-email time, login-failure state, and audit timestamps.
UCT IDs and email addresses are unique.

`auth_sessions` contains hashed opaque tokens, user ownership, a hashed CSRF
token, last-access/expiry timestamps, and revocation state. Sessions are
revocable individually and are deleted automatically if their user is deleted.

Both tables are created idempotently during FastAPI startup. Existing scan data
does not need a migration.

## API contracts

### Public authentication

`POST /auth/login`

```json
{"uct_id":"ABCDEF001","password":"emailed-password"}
```

On success it sets the session cookie and returns:

```json
{
  "user": {
    "id": 1,
    "uct_id": "ABCDEF001",
    "name": "Example Administrator",
    "email": "administrator@example.ac.za",
    "role": "admin",
    "active": true
  },
  "csrf_token": "per-session-value"
}
```

Incorrect credentials return `401` with the same message regardless of whether
the ID is missing, disabled, locked, or has no active password.

`POST /auth/password/request`

```json
{"uct_id":"ABCDEF001"}
```

Always returns `202` and a generic message. Delivery failures are written to
server logs without the generated password.

`GET /auth/me` restores the authenticated profile and its per-session CSRF
token.
`POST /auth/logout` revokes the current session and clears its cookie.

### Staff administration

- `GET /admin/users`: list accounts without password or session data.
- `POST /admin/users`: add an account and attempt to send its initial password.
- `PATCH /admin/users/{user_id}`: change name, email, role, or active state.
- `POST /admin/users/{user_id}/password`: email a pending replacement.

These routes require an administrator session. The frontend API wrapper adds
the CSRF header to state-changing requests automatically.

## Configuration

Copy the example and replace every placeholder before production use:

```bash
cd software
cp .env.example .env
```

| Variable | Purpose |
|---|---|
| `EXAMSCAN_BOOTSTRAP_UCT_ID` | First administrator's UCT ID |
| `EXAMSCAN_BOOTSTRAP_NAME` | First administrator's display name |
| `EXAMSCAN_BOOTSTRAP_EMAIL` | First administrator's delivery address |
| `SMTP_HOST`, `SMTP_PORT` | SMTP connection |
| `SMTP_USERNAME`, `SMTP_PASSWORD` | Optional SMTP authentication |
| `SMTP_SECURITY` | `none`, `starttls`, or `ssl` |
| `SMTP_FROM` | From header used for password email |
| `FRONTEND_URL` | Login link placed in email |
| `FRONTEND_ORIGINS` | Comma-separated allowed browser origins |
| `EXAMSCAN_ENV` | Set to `production` to make secure cookies the default |
| `AUTH_COOKIE_SECURE` | Explicit cookie-security override; use `true` under HTTPS |

Database variables remain documented in `software/DATABASE.md`.

## First startup

1. Configure MySQL, SMTP, and all three bootstrap values.
2. Start MySQL and Mailpit for development with `docker compose up -d` from
   `software/`. Mailpit's inbox is at `http://localhost:8025`.
3. Start FastAPI. If the users table is empty, startup creates one active
   administrator without a password. If the bootstrap values are incomplete,
   startup fails instead of exposing an unauthenticated application.
4. Open `/login`, enter the bootstrap UCT ID, and choose **Email me a password**.
5. Read the password from the configured mailbox, sign in, and add operators
   from **Staff**.

Bootstrap settings are ignored after any user exists; they do not overwrite or
re-enable an existing account.

## Verification

Run the backend suite only against an isolated database whose name ends in
`_test`; the suffix guard prevents the integration fixtures from clearing a
development or production staff table:

```bash
DB_NAME=examscan_test uv run pytest software/tests
```

The opt-in `software/tests/test_auth_mailpit_e2e.py` check requires isolated
MySQL and Mailpit services plus `EXAMSCAN_MAILPIT_E2E=1`. It performs the full
bootstrap-admin and operator flow using actual SMTP delivery. Frontend checks
run from `final-ui/` with `npm run test`, `npm run lint`, and `npm run build`.

## Manual API debugging

The supported product client is `final-ui`. If a protected endpoint must be
debugged manually, sign in once and retain the cookie and CSRF token:

```bash
curl -c cookies.txt -H 'Content-Type: application/json' \
  -d '{"uct_id":"ABCDEF001","password":"PASSWORD-FROM-EMAIL"}' \
  http://localhost:8000/auth/login
```

Use `-b cookies.txt` for authenticated `GET` requests. Also pass
`-H 'X-CSRF-Token: VALUE-FROM-LOGIN'` for state-changing requests. Cookie and
token files are secrets and must not be committed.

## Troubleshooting and recovery

- **API will not start on a new database:** configure all three bootstrap
  variables with a valid email address.
- **No password email:** check SMTP settings and server logs, then inspect
  Mailpit in development. The existing password remains valid after failure.
- **Email button appears to do nothing:** the public response is intentionally
  generic. Wait five minutes before retrying and ask an administrator to verify
  that the account is active and the address is correct.
- **Account locked:** wait 15 minutes. A replacement can be requested during
  the lockout, but cannot be used until the lockout expires.
- **Unexpected `403`:** refresh the UI to obtain a new CSRF token. Operators
  receive `403` on staff-administration routes by design.
- **Lost final administrator access:** stop the API, use an authorized MySQL
  administrator to set that user's `active = TRUE`, `role = 'admin'`, clear
  `locked_until` and `failed_login_attempts`, then restart and request a new
  password. Do not insert plaintext passwords or hashes manually.

## Acknowledgement

The ExamScan authentication flow is adapted from Johan Bontes’s Capstone
project-selection application: https://github.com/JBontes/capstone

This acknowledges the design and code influence only. It does not attribute
ExamScan itself to Johan Bontes and does not make a licensing claim.
