# final-ui

Operator-facing rebuild of the ExamScan frontend. Login → Create Session →
View Session → Debug. See `../docs/final-ui-api-requirements.md` and
`../docs/software-compatibility-changes.md` for what the backend still needs
to support this UI fully — several features here are backed by a temporary
localStorage mock layer (`src/api/mockRuns.js`) until those endpoints exist.

## Run

```bash
npm install
npm run dev
```

Requires the FastAPI backend running on port 8000 (from `software/`):

```bash
uvicorn scanner_api:app --reload --port 8000
```

`vite.config.js` proxies `/api/*` to `http://localhost:8000` (prefix
stripped), same contract as `examscan-ui/vite.config.js`.
