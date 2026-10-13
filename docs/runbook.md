# Runbook

Operational steps for running the service: deploy, webhooks, backups and monitoring.

## Resend webhook (bounces, complaints, delays)

Do this once, after the app is reachable at `https://app.closetcompute.online`.

1. In the Resend dashboard, go to **Webhooks → Add endpoint**:
   - URL: `https://app.closetcompute.online/hooks/email-events`
   - Events: `email.bounced`, `email.complained`, `email.delivery_delayed`, `email.suppressed`
2. Copy the endpoint's signing secret (it starts with `whsec_`) into `deploy/.env` as `RESEND_WEBHOOK_SECRET`. Redeploy, or restart the `api` service.
3. Check: Resend's "Send test event" should get `200 {"recorded": 0}`; test events don't match any sent message, so nothing is recorded.

Behaviour:
- **Without the secret,** the endpoint answers 503. Resend retries for a while, so set the secret soon after adding the webhook.
- **Signatures** are verified with Svix. Events are de-duplicated by `svix-id`, so retries are safe.
- **Matching.** Events are matched to our messages through `mail_log.provider_id` (the Resend email id). A bounce on a reply is recorded against the alias and never counts against the owner's recipients.
- **Auto-disable.** Three hard bounces in a row disable a recipient. The user is told through their other usable recipients, or the admins are told if there are none. Re-enabling the recipient from the dashboard resets the count.
- `/hooks/*` must be on the Cloudflare Access bypass list, together with `/a/*` and `/api/v1/*`.

## Backups and restore

- **Schedule:** the Celery beat task `maintenance.backup` runs daily at 20:30 UTC (02:00 Asia/Kolkata). It writes `backups/mailalias-YYYYMMDD.sql.gz.gpg` to the `mail-inbox` R2 bucket.
- **Lifecycle:** the `backups-30d` rule deletes backups after 30 days.
- **Format:** plain-SQL `pg_dump --no-owner --no-privileges`, gzipped, then GPG symmetric (AES256) with `BACKUP_PASSPHRASE`. **Without that passphrase the backups cannot be read.** Keep it in your password manager.

Restore into a scratch database (any machine with gpg and psql 17):

```sh
gpg --batch --pinentry-mode loopback --passphrase-fd 0 --decrypt mailalias-YYYYMMDD.sql.gz.gpg \
  <<< "$BACKUP_PASSPHRASE" | gunzip > restore.sql
createdb restore_check && psql -v ON_ERROR_STOP=1 -d restore_check < restore.sql
```

Verified on 2026-10-12 against the dev database. The restored database had the same users, aliases, mail_log rows and alembic version as the source.

## Monitoring

`monitor.check` runs every 5 minutes and emails every enabled admin. Each alert is sent at most once per 6 hours. It alerts when:
- the processor heartbeat is missing or older than 5 minutes;
- the dead-letter queue is not empty;
- today's sends reach 80% of `OUTBOUND_DAILY_CAP`;
- 24-hour hard bounces exceed 5% of delivered messages.

**Queue retention is one day.** Both `mail-inbound` and `mail-inbound-dlq` have `message_retention_period = 86400` (the account's current plan limit). If the processor is down for more than 24 hours, queued jobs expire. The raw messages stay in R2 `in/` for 3 days, but nothing points the processor at them. Treat a "processor not running" alert as urgent.

## Production deploy

The server never gets source code. Every push to `main` runs CI (`.github/workflows/ci.yml`): tests, then three images published to GHCR, each tagged with the commit SHA and `latest`:
- `ghcr.io/prithvi824/closet-mail-backend` (api, processor, worker, migrate)
- `ghcr.io/prithvi824/closet-mail-web` (Caddy serving the SPA and proxying the API)
- `ghcr.io/prithvi824/closet-mail-rspamd` (official Rspamd with `deploy/rspamd/` baked in)

The host only holds `~/mail-alias/` with `docker-compose.yml`, `.env`, `.env.prod` and `logs/`.

Prerequisites, done once:
1. `deploy/.env` contains the provider credentials, `PROD_DATABASE_URL` (role `mailalias` on `global-postgres`) and `DEPLOY_HOST=user@host`.
2. Run `deploy/scripts/gen-prod-secrets.sh`. It creates `deploy/.env.prod` (mode 600) with `APP_ENV=prod`, `APP_BASE_URL` and fresh `DATA_ENCRYPTION_KEY`, `HASH_KEY`, `SIGNING_KEY` and `BACKUP_PASSPHRASE`. **Copy the file into your password manager before deploying.** Losing it makes encrypted data and backups unreadable. The script refuses to overwrite an existing file.
3. Key-based SSH to `DEPLOY_HOST` works, and the host has Docker with Compose v2+ and the external `global-network`.

Deploy (repeatable):

```sh
git push origin main            # wait for the CI run to finish (images published)
deploy/scripts/deploy.sh        # copy compose + env files, pull, migrate, start, wait for /healthz
deploy/scripts/verify-infra.sh  # read-only checks; all PASS once the app is live
```

`deploy.sh` deploys the images of the current local commit (`git rev-parse HEAD`) unless a tag is given: `deploy/scripts/deploy.sh <sha>`. The tag is written into the host's `.env` as `IMAGE_TAG`.

What runs (`docker-compose.yml`, project `mailalias`):
- **Services:**
  - `migrate` (one-shot `alembic upgrade head`; the others start after it succeeds)
  - `api`
  - `processor`
  - `worker` (Celery with embedded beat)
  - `rspamd`
  - `web` (Caddy)
- **Ports:** only `web` publishes a port, on `127.0.0.1:8080`, which is what the Cloudflare tunnel targets.
- **Networks and data:** the backend services join the external `global-network` to reach `global-postgres` and `global-redis` (DB 3). Nothing else on the host is touched.
- **Logs:** `~/mail-alias/logs/{api,processor,worker}/` (JSON lines, rotated daily, 14 kept) plus `docker compose logs`.

After the first deploy:
1. `cd ~/mail-alias && docker compose exec api mailalias create-admin --username <you> --email <you@...>` (prompts for the password).
2. Register the Resend webhook (section above), then run `deploy.sh` again to ship the secret.
3. Run `verify-infra.sh`, then sign in at `https://app.closetcompute.online` (Cloudflare Access, then app login).

Rollback: `deploy/scripts/deploy.sh <previous sha>`. Migrations are additive; run `docker compose run --rm migrate alembic downgrade <rev>` on the host only if a migration itself is the problem.

## Edge Worker

The Worker is deployed from a workstation, not CI, so the Cloudflare token stays off GitHub:

```sh
cp edge/wrangler.example.toml edge/wrangler.toml   # once; set the KV namespace id (gitignored)
cd edge && npx wrangler deploy
```
