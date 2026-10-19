# Changelog

## 0.3.0 (19 Oct 2026)

First run against a real HubSpot portal (a developer test account). It found a bug the mock could not show, and the fix is measured in [docs/hubspot-live-run.md](docs/hubspot-live-run.md): 29 enquiries from 16 people, posted back to back, 16 contacts, 16 deals, 0 duplicates.

### Fixed
- A double click could fail with HubSpot 409 "Contact already exists": the search index trails writes by a few seconds, so the first click's contact was not found yet. The adapter now reads the existing id from the 409 and patches that contact.
- The open deal is read through the associations API (v4) instead of deal search, so a deal created a second earlier is found and a second deal is not opened.

### Added
- `CRM_SEARCH_LAG_SECONDS` (default 120): for that long after the engine wrote a contact, a repeat with the same email or phone reuses it even if the CRM's search misses it. Covers same-phone repeats, which the 409 cannot, because phones are not unique in HubSpot.
- `scripts/hubspot_live_check.py`: runs a slice of the seed against a portal and counts contacts per person, deals per contact, false merges, and which layer caught each repeat.
- Six tests (78 in total): the 409 path, other conflicts still raising, open deal through associations, closed deals skipped, and the engine fallback with a CRM whose search always lags.

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
