# ExamScan

ExamScan combines a Raspberry Pi document-scanner rig with a separate OCR/application backend and operator frontend. The Pi captures examination pages, advances the booklet, and exposes its camera and workflow through a REST API.

## Repository areas

| Path | Responsibility |
|---|---|
| [`hardware/scanner-service`](hardware/scanner-service) | Raspberry Pi camera, hand detection, page-turn control, run storage, API, and Rig UI |
| [`software`](software) | OCR, authentication, database, and application API |
| [`final-ui`](final-ui) | Product operator interface |
| [`examscan-ui`](examscan-ui) | Legacy frontend prototype |

## Hardware service

Start with the [hardware quick start](hardware/README.md). Detailed information is split by task:

- [Hardware overview](docs/hardware/README.md)
- [Setup and deployment](docs/hardware/setup-deployment.md)
- [Configuration and API](docs/hardware/configuration-api.md)
- [Testing and troubleshooting](docs/hardware/testing-troubleshooting.md)

The engineering page served by `examscan-rig` is the **Rig UI**. It is a hardware-testing interface, not the product UI, and its controls can move physical components.

The scanner commands may be run either from `hardware/scanner-service`, or from the repository root through the compatibility launchers:

```bash
uv run examscan
uv run examscan-dev
uv run examscan-rig
```

## Product software

The product backend remains under `software/` and the supported frontend remains under `final-ui/`. See the [backend overview](docs/software/README.md), [database guide](docs/software/database.md), [software scripts guide](docs/software/scripts.md), [frontend guide](docs/software/frontend.md), and [staff authentication guide](docs/authentication.md) for component-specific guidance.

## Staff authentication

The operator-facing `final-ui` requires a registered staff account. It uses a
UCT ID and a random password delivered by email; users do not self-register or
choose passwords. The current password remains valid when a replacement is
requested and is retired only after the replacement is successfully used.

Authentication is enforced by the FastAPI application in `software/`, not just
by frontend routing. All document, scan-session, download, debug, and Pi-proxy
routes require a revocable browser session. `GET /health`, login, and password
request are the only public application routes. The low-level Pi hardware API
served by `hardware/scanner-service` is unchanged and must remain on its private network.

For the full user flow, API contracts, schema, security decisions, deployment,
and recovery procedures, see [Staff authentication](docs/authentication.md).

### Development setup: laptop UI and backend, Pi hardware

The recommended development layout keeps only camera and mechanical control on
the Raspberry Pi. A seperate device runs `final-ui`, FastAPI, MySQL, and
Mailpit. In this layout the browser talks to the laptop, and FastAPI proxies
hardware operations to the Pi's private API.

#### 1. Install prerequisites

Install and start:

- Docker Desktop using Linux containers. Wait for **Engine running** before
  using `docker compose`.
- a current Node.js LTS release, including npm;
- `uv` for the Python environment.

Open a new PowerShell window after installing Node.js, then verify:

```powershell
docker info
node --version
npm.cmd --version
uv --version
```

The laptop needs the complete ExamScan repository, not just `final-ui`, because
the Python project metadata and lockfile live at the repository root. Changes
that have not been committed and pushed cannot be obtained with `git pull`;
copy them from the Pi or commit and push them before cloning.

#### 2. Configure the laptop services

From PowerShell in the laptop repository:

```powershell
cd C:\Users\<you>\Documents\ExamScan\software
Copy-Item .env.example .env
notepad .env
```

Set local values similar to these, replacing the bootstrap identity and both
database passwords:

```dotenv
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=examscan
DB_PASSWORD=choose-a-local-development-password
DB_ROOT_PASSWORD=choose-a-different-local-development-password
DB_NAME=examscan

EXAMSCAN_BOOTSTRAP_UCT_ID=YOUR_UCT_ID
EXAMSCAN_BOOTSTRAP_NAME=Your Full Name
EXAMSCAN_BOOTSTRAP_EMAIL=admin@example.test

SMTP_HOST=127.0.0.1
SMTP_PORT=1025
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_SECURITY=none
SMTP_FROM=ExamScan <examscan@example.test>

EXAMSCAN_ENV=development
FRONTEND_URL=http://localhost:5173
FRONTEND_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
AUTH_COOKIE_SECURE=false
MAILPIT_UI_PORT=8025
```

Mailpit captures mail locally, so `admin@example.test` does not have to be a
real mailbox. The generated ExamScan staff password is unrelated to the two
MySQL passwords. Keep `.env` private; it is excluded from Git.

#### 3. Start the Pi hardware API

In a terminal connected to the Pi:

```bash
ssh Pi
cd /home/chidi/Desktop/ExamScan/hardware/scanner-service
sudo systemctl start pigpiod
uv run examscan
```

Keep that process running. From the laptop, verify the private hardware API:

```powershell
Invoke-RestMethod http://10.42.0.1:8000/api/health
```

`software/constants.py` currently points `RUNS_API_BASE_URL` at
`http://10.42.0.1:8000`. If the Pi is reached through mDNS instead of that
private address, change it to `http://examscan.local:8000` before starting the
laptop backend.

#### 4. Start MySQL and Mailpit on the laptop

In the first laptop PowerShell window:

```powershell
cd C:\Users\<you>\Documents\ExamScan\software
docker compose up -d
docker compose ps
```

Wait for MySQL and Mailpit to be running. On the first start Docker downloads
their images and creates the database named by `DB_NAME`.

#### 5. Start FastAPI on the laptop

In a second PowerShell window:

```powershell
cd C:\Users\<you>\Documents\ExamScan\software
uv run uvicorn scanner_api:app --host 0.0.0.0 --port 8000
```

FastAPI creates the scan and authentication tables automatically. Confirm it
is available with `Invoke-RestMethod http://localhost:8000/health`.

#### 6. Start the frontend on the laptop

In a third PowerShell window:

```powershell
cd C:\Users\<you>\Documents\ExamScan\final-ui
npm.cmd ci
npm.cmd run dev
```

Open `http://localhost:5173/login`. The existing Vite configuration proxies
`/api` to FastAPI on `localhost:8000`; it must not point directly to the Pi in
this layout.

#### 7. Create the first login

1. Enter `EXAMSCAN_BOOTSTRAP_UCT_ID` on the login page.
2. Select **Email me a password**.
3. Open Mailpit at `http://localhost:8025` and copy the generated password.
4. Sign in and use **Staff** to create operator accounts.

The bootstrap account is inserted only when the `users` table is empty. Later
changes to the three bootstrap environment variables do not alter that account.

To stop the laptop services without deleting data, stop FastAPI and Vite with
Ctrl+C, then run `docker compose down` from `software/`. Do not add `-v` unless
you intentionally want to delete the local database volume.

Common startup failures:

- `dockerDesktopLinuxEngine` pipe missing: open Docker Desktop and wait for
  **Engine running**.
- `npm` or `npm.cmd` not recognized: install Node.js LTS and open a new
  PowerShell window.
- MySQL authentication error after editing `.env`: the existing Docker volume
  still has its original credentials. Restore them, or intentionally reset the
  development volume with `docker compose down -v` before starting again.

The environment reference is grouped as follows: `DB_HOST`, `DB_PORT`,
`DB_USER`, `DB_PASSWORD`, and `DB_NAME` configure MySQL; the three
`EXAMSCAN_BOOTSTRAP_*` values create the first administrator; `SMTP_*`
configures delivery; and `FRONTEND_URL`, `FRONTEND_ORIGINS`, `EXAMSCAN_ENV`,
and `AUTH_COOKIE_SECURE` define the browser boundary. Safe placeholders and
development defaults are in `software/.env.example`.

Production deployments must use real SMTP credentials, set
`EXAMSCAN_ENV=production` (and preferably `AUTH_COOKIE_SECURE=true`
explicitly), serve the frontend over HTTPS, and restrict
`FRONTEND_ORIGINS` to the deployed frontend origin. Never copy SMTP or session
credentials from the reference Capstone project into ExamScan.

## Acknowledgements

The ExamScan authentication flow is adapted from Johan Bontes’s Capstone
project-selection application: https://github.com/JBontes/capstone

This is an acknowledgement of the authentication design and code influence;
it does not attribute the ExamScan project to Johan Bontes or assert a license
for the referenced project.
