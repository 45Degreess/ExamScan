# final-ui

Operator-facing rebuild of the ExamScan frontend. Login → Create Session →
Prepare → View Session → Review, plus a Debug page. The UI is wired to the
FastAPI backend in `software/`; see `../docs/final-ui-api-requirements.md` for
the per-feature status (what's implemented and anything still outstanding).

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
