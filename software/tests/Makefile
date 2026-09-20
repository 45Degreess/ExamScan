# Manual pipeline testing without a Raspberry Pi.
#
# Logs in as a staff account, creates a scan session if needed, and submits a
# folder of images as a booklet — the same thing `POST /sessions/{code}/booklets`
# does for a real operator upload. Run from the software/ directory.
#
# Usage:
#   make test-pipeline UCT_ID=MSTDEV001 PASSWORD=yourpassword
#
# Optional overrides:
#   make test-pipeline UCT_ID=... PASSWORD=... SESSION_CODE=MySession \
#       COURSE_CODE=CSC3003S FOLDER=/path/to/images
#
# Re-run without logging in again (cookie/token are cached in .cookies.txt /
# .csrf_token until you `make clean-auth`):
#   make post-booklet SESSION_CODE=MySession
#
# `make collect-runs` simulates the Pi's hardware API (rather than uploading
# a folder directly) so you can test the real POST .../collect-runs pipeline.
# It expects an EXISTING session (it never creates one) and a folder of
# pre-made run .zip archives — one zip per simulated Pi run, named
# <run_id>.zip. It requires the API server itself to be started with
# RUNS_API_BASE_URL pointed at the fake Pi (the Makefile tells you the exact
# command to use — the already-running server can't be redirected without a
# restart, since that env var is only read at process startup):
#   make collect-runs SESSION_CODE=MySession RUNS_FOLDER=/path/to/zips

BASE_URL      ?= http://localhost:8000
UCT_ID        ?=
PASSWORD      ?=
SESSION_CODE  ?= CSCTest
COURSE_CODE   ?= CSC3003S
OPERATOR_NAME ?= LocalTest
TEST_DATE     ?= $(shell date +%F)
FOLDER        ?= $(CURDIR)/demo_images
RUNS_FOLDER   ?=
FAKE_PI_PORT  ?= 9100
POLL_SECONDS  ?= 180
COOKIE_JAR    := .cookies.txt
CSRF_FILE     := .csrf_token

.PHONY: login create-session post-booklet collect-runs test-pipeline clean-auth

login:
	@if [ -z "$(UCT_ID)" ] || [ -z "$(PASSWORD)" ]; then \
		echo "Usage: make login UCT_ID=<id> PASSWORD=<password>"; exit 1; \
	fi
	curl -s -c $(COOKIE_JAR) -H 'Content-Type: application/json' \
		-d '{"uct_id":"$(UCT_ID)","password":"$(PASSWORD)"}' \
		$(BASE_URL)/auth/login \
	| python3 scripts/extract_csrf.py > $(CSRF_FILE)
	@echo "Logged in. Session cookie + CSRF token saved."

create-session:
	@echo "Creating session '$(SESSION_CODE)' (a 409 here just means it already exists, that's fine):"
	curl -s -b $(COOKIE_JAR) -H "X-CSRF-Token: $$(cat $(CSRF_FILE))" \
		-X POST $(BASE_URL)/sessions \
		-F session_code=$(SESSION_CODE) \
		-F operator_name=$(OPERATOR_NAME) \
		-F test_date=$(TEST_DATE) \
		-F course_code=$(COURSE_CODE)
	@echo ""

post-booklet:
	@echo "Submitting $(FOLDER) as a booklet in session '$(SESSION_CODE)':"
	curl -s -b $(COOKIE_JAR) -H "X-CSRF-Token: $$(cat $(CSRF_FILE))" \
		-X POST $(BASE_URL)/sessions/$(SESSION_CODE)/booklets \
		-F folder_path=$(FOLDER)
	@echo ""

collect-runs:
	@if [ -z "$(SESSION_CODE)" ]; then \
		echo "Usage: make collect-runs SESSION_CODE=<existing session> RUNS_FOLDER=<folder of .zip run archives>"; exit 1; \
	fi
	@if [ -z "$(RUNS_FOLDER)" ] || [ ! -d "$(RUNS_FOLDER)" ]; then \
		echo "RUNS_FOLDER must point at a directory of .zip run archives (one per simulated Pi run)."; exit 1; \
	fi
	@echo "IMPORTANT: the API server must be running with:"
	@echo "  RUNS_API_BASE_URL=http://127.0.0.1:$(FAKE_PI_PORT) uv run uvicorn scanner_api:app --reload --port 8000"
	@echo "so it talks to this fake Pi instead of real hardware. Restart it that way first if it isn't already."
	@echo ""
	python3 scripts/fake_pi_server.py "$(RUNS_FOLDER)" $(FAKE_PI_PORT) & \
	PI_PID=$$!; \
	trap "kill $$PI_PID 2>/dev/null" EXIT; \
	sleep 1; \
	echo "Requesting collect-runs for session '$(SESSION_CODE)':"; \
	curl -s -b $(COOKIE_JAR) -H "X-CSRF-Token: $$(cat $(CSRF_FILE))" \
		-X POST $(BASE_URL)/sessions/$(SESSION_CODE)/collect-runs; \
	echo ""; \
	echo "Polling until every collected run finishes (up to $(POLL_SECONDS)s)..."; \
	python3 scripts/poll_booklets.py $(BASE_URL) $(COOKIE_JAR) $(SESSION_CODE) $(POLL_SECONDS)

test-pipeline: login create-session post-booklet

clean-auth:
	rm -f $(COOKIE_JAR) $(CSRF_FILE)
