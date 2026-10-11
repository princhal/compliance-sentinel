# Local development shortcuts. On macOS, Homebrew's Pango must be on the library path for PDFs.
export DYLD_FALLBACK_LIBRARY_PATH := /opt/homebrew/lib
PY := .venv/bin/python
SENTINEL := $(PY) -m sentinel.cli
# Override when 8000 is taken locally, e.g. `make api API_PORT=8010`, and set SENTINEL_API_URL in web/.env.local to match.
API_PORT ?= 8000

.PHONY: setup up migrate seed demo test lint eval api worker web
setup:          ## Install Python deps and Chromium for Playwright
	uv sync && .venv/bin/playwright install chromium
up:             ## Start Postgres and Redis
	docker compose up -d --wait
migrate: up
	$(SENTINEL) db-upgrade
seed: migrate
	$(SENTINEL) seed
demo: seed      ## Full offline pipeline: scrape fixtures, audit the demo repo, write a PDF, score it
	$(SENTINEL) scrape -s fixtures
	$(SENTINEL) audit --approve-as "Demo Auditor"
	$(SENTINEL) eval
amendment:      ## Ingest the synthetic amendment and show the targeted re-audit
	$(SENTINEL) scrape -s fixtures --fixture-dir sentinel/fixtures/regulations/demo-amendments
test: up
	$(PY) -m pytest -q
lint:
	.venv/bin/ruff check .
eval:
	$(SENTINEL) eval
api:
	JOBS_INLINE=true $(SENTINEL) api --port $(API_PORT)
worker:
	$(SENTINEL) worker
web:
	cd web && npm run dev
