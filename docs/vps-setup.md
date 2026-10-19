# Putting it on a VPS

The compose file in the repository runs on a laptop. The same file runs on a small VPS with three additions: a domain, HTTPS in front of n8n, and backups. About an hour the first time.

## 1. The server

- Any 2 vCPU / 4 GB box is enough for one business. Pick a provider with a UK or EU region if the enquiries are UK or EU personal data (for example DigitalOcean London, OVH London, Hetzner Falkenstein or Helsinki).
- Ubuntu 24.04. Install Docker with the official convenience script, add your user to the `docker` group, log out and in.
- Point a DNS A record at the server: `n8n.yourdomain.co.uk`.

```bash
sudo apt-get update && sudo apt-get -y install git ufw
sudo ufw allow OpenSSH && sudo ufw allow 80 && sudo ufw allow 443 && sudo ufw enable
git clone https://github.com/danilablagorodniy37/n8n-lead-intake && cd n8n-lead-intake
cp .env.example .env
```

## 2. `.env` for production

```ini
N8N_ENCRYPTION_KEY=<openssl rand -hex 32, generated once, never changed>
N8N_HOST=n8n.yourdomain.co.uk
N8N_PROTOCOL=https
WEBHOOK_URL=https://n8n.yourdomain.co.uk/
N8N_ACTIVATE_WORKFLOWS=true
API_TOKEN=<openssl rand -hex 24>          # n8n sends it to the engine as a bearer token
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
CRM_PROVIDER=hubspot
HUBSPOT_ACCESS_TOKEN=...
ANTHROPIC_API_KEY=...
REPLY_FROM=hello@yourdomain.co.uk
SMTP_HOST=smtp.postmarkapp.com            # or Brevo, or a Google Workspace app password
SMTP_PORT=587
SMTP_USER=...
SMTP_PASSWORD=...
SMTP_SECURE=false
```

Remove the Mailpit service from the compose file, or leave it and simply point `SMTP_HOST` at your provider; nothing else reads it.

## 3. HTTPS with Caddy

Add a `caddy` service to `docker-compose.yml` and stop publishing n8n's port directly:

```yaml
  caddy:
    image: caddy:2
    ports: ["80:80", "443:443"]
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddydata:/data
    depends_on: [n8n]
```

`Caddyfile`:

```
n8n.yourdomain.co.uk {
    reverse_proxy n8n:5678
}
```

Add `caddydata:` under `volumes:`, delete the `ports:` block from the `n8n` service, and keep the engine's port unpublished too (n8n reaches it on the compose network as `http://engine:8000`). Caddy fetches and renews the certificate itself.

```bash
docker compose up -d --build
docker compose logs -f n8n-import     # "Successfully imported 3 workflows", then the activation lines
```

Open `https://n8n.yourdomain.co.uk`, create the owner account, check that the three workflows are active. Telegram's webhook is registered when the approval workflow activates; a tap on a button now reaches n8n.

## 4. Point the website form at it

The form posts JSON to `https://n8n.yourdomain.co.uk/webhook/lead`. Field names the engine understands: `name`, `email`, `phone`, `message`, `area` (or `postcode`), `budget`, `enquiry_type`, `source`. Unknown fields are kept in the raw record and ignored. For WordPress, a Contact Form 7 or WPForms webhook add-on does this without code; for a static site, a 10-line fetch.

Put the webhook behind a shared secret if the form is public: add a header check in the Webhook node (Authentication: Header Auth) and send the header from the form handler.

## 5. Backups

Two things hold state: the Postgres volume (n8n's workflows, credentials, executions) and `data/leadintake.sqlite` (leads, the fake CRM if you use it, incidents).

```bash
# nightly, from cron
docker compose exec -T db pg_dump -U n8n n8n | gzip > backups/n8n-$(date +%F).sql.gz
cp data/leadintake.sqlite backups/leadintake-$(date +%F).sqlite
```

Copy `backups/` off the box (rclone to an object store in the same region). Test a restore once: `docker compose down -v`, restore the dump into a fresh `db`, and bring the stack up again. The encryption key in `.env` must be the same one the credentials were saved with.

## 6. Upgrades

Pin `N8N_VERSION` in `.env` and move it on purpose: read the release notes, take a backup, change the version, `docker compose pull && docker compose up -d`. The engine rebuilds from the repository; `git pull` then `docker compose up -d --build`.

## What this costs to run (estimates, October 2026)

- VPS: about £5 to £10 a month.
- Domain: already owned, or about £10 a year.
- Model: at `claude-haiku-5-5` prices, a few pence a month for a business that gets 100 enquiries.
- Transactional email: free tiers of Postmark or Brevo cover a few hundred replies a month.
- HubSpot: free tier.
