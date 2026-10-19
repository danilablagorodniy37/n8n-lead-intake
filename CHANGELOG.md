# Changelog

## 0.2.0 (19 Oct 2026)

Tested end to end with a real Telegram bot, `claude-haiku-5-5` and the bundled tunnel: enquiry in, approval tap on a phone, email out, lead marked sent.

### Added
- Optional `tunnel` service in `docker-compose.yml` (cloudflared quick tunnel), so Telegram button taps reach n8n on a laptop with nothing to install: `docker compose --profile tunnel up -d tunnel`.
- `N8N_WEBHOOK_URL` is set alongside `WEBHOOK_URL`, the name newer n8n releases expect.
- README section "Live run" with the green approval execution and the approved email, and the measured cost of one model-drafted reply ($0.00025 at the configured prices).

### Fixed
- Telegram rejected the owner's message when it contained an email address in angle brackets or an underscore, because the node used Markdown parsing. Every Telegram node now sends with `parse_mode` HTML, the engine escapes all text it puts into the message, and the error alert escapes its fields. New test with hostile input.
- README test and line counts.

## 0.1.0 (19 Oct 2026)

First release: three n8n workflows (intake, Telegram approval, error handler) and the Python engine.

- Email and E.164 phone normalisation, de-duplication by email or phone, idempotent contact and deal upsert (fake CRM or HubSpot v3).
- Scoring against the owner's `criteria.yaml`, reply drafting by template or model with a figures guard.
- Approval state machine: a lead cannot be marked sent without a recorded approve or edit.
- 200 synthetic enquiries from 120 people: 127 contacts, 0 duplicates.
- Docker Compose with n8n 2.43, PostgreSQL 17, Mailpit and a one-shot import of workflows and credentials; CI that lints, tests, seeds and imports the workflows into n8n.
