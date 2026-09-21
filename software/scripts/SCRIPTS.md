# `software/scripts/` — Script Overview

Standalone dev/ops tooling that runs outside the FastAPI app.

| File | Description |
|---|---|
| `fake_pi_server.py` | Mocks the Raspberry Pi hardware API so `/collect-runs` can be tested without physical hardware — serves a folder of pre-made run `.zip` archives as if they were completed Pi runs. |
| `zip_runs_for_fake_pi.py` | Zips a folder of raw run directories into per-run `.zip` archives in the shape `fake_pi_server.py` expects. |
| `poll_booklets.py` | Polls `GET /sessions/{code}/booklets` until processing finishes, printing status/mark as each booklet updates. |
| `extract_csrf.py` | Reads a login response from stdin and prints its `csrf_token`, for use in shell/Makefile login flows. |
| `batch_eval_cover_pages.py` | Runs a batch of cover-page images through the debug OCR routes over real HTTP and writes a `results.csv` for manual scoring. |
| `build_contact_sheet.py` | Builds a browser-viewable HTML contact sheet from a batch-eval `results.csv`, for visually grading OCR predictions. |
| `score_results.py` | Reads graded `results.csv` file(s) and prints accuracy / confidence-tier statistics. |


## GenAI decleration
Majority of the code in the repository was written by Claude Sonnet 4.5. This code was used to simulate the Raspberry Pi hardware API, process large amount of test images through OCR. The scripts helped process and display the test data. Results were graded and collected and analysed by Devak Mistry.

