# Convenience targets. Every target has a plain command equivalent in the README.
PY ?= python

.PHONY: install dev lint format test secrets hooks serve seed seed-generate seed-post report status reset up down logs

install:
	$(PY) -m pip install -e .

dev:
	$(PY) -m pip install -e ".[dev]"

lint:
	ruff check . && ruff format --check .

format:
	ruff format . && ruff check --fix .

test:
	pytest -q

secrets:
	$(PY) scripts/check_secrets.py

hooks:
	printf '#!/bin/sh\nexec python scripts/check_secrets.py --staged\n' > .git/hooks/pre-commit
	@echo "pre-commit hook installed: commits that contain something like a key are refused"

serve:
	leadintake serve

# in-process: 200 enquiries through the engine, approved and marked sent, no n8n needed
seed:
	leadintake seed --auto-approve

seed-generate:
	leadintake seed --generate

# through n8n: the webhook, the engine and the Telegram message, one enquiry every 0.2 s
seed-post:
	leadintake seed --post http://localhost:5678/webhook/lead

report:
	leadintake report --markdown docs/report.md

status:
	leadintake status

reset:
	leadintake reset --yes

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f n8n engine
