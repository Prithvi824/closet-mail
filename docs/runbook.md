# Runbook

Operational steps for running the service: deploy, webhooks, backups and monitoring.

## Resend webhook (bounces, complaints, delays)

Do this once, after the app is reachable at `https://app.closetcompute.online`.

1. In the Resend dashboard, go to **Webhooks → Add endpoint**:
   - URL: `https://app.closetcompute.online/hooks/email-events`
   - Events: `email.delivered`, `email.bounced`, `email.complained`, `email.delivery_delayed`, `email.suppressed`
   - `email.delivered` turns a copy's status from "sent" to "delivered" on the Activity page. Add it to an existing endpoint too.
2. Copy the endpoint's signing secret (it starts with `whsec_`) into `deploy/.env` as `RESEND_WEBHOOK_SECRET`. Redeploy, or restart the `api` service.
3. Check: Resend's "Send test event" should get `200 {"recorded": 0}`; test events don't match any sent message, so nothing is recorded.

Behaviour:
- **Without the secret,** the endpoint answers 503. Resend retries for a while, so set the secret soon after adding the webhook.
- **Signatures** are verified with Svix. Events are de-duplicated by `svix-id`, so retries are safe.
- **Matching.** Each copy sent to an inbox has its own Resend id in `delivery_log`, so an event updates exactly that copy and inbox. Older mail falls back to `mail_log.provider_id`, matched only within that subdomain. An unknown id is recorded without an inbox and never disables anything. A bounce on a reply is recorded against the alias and never counts against the inboxes.
- **Auto-disable.** Three hard bounces in a row disable an inbox, and the operator is emailed. Re-enabling the inbox from the dashboard resets the count.
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

`monitor.check` runs every 5 minutes and emails the operator. Each alert is sent at most once per 6 hours. It alerts when:
- the processor heartbeat is missing or older than 5 minutes;
- the dead-letter queue is not empty;
- today's sends reach 80% of `OUTBOUND_DAILY_CAP`;
- 24-hour hard bounces exceed 5% of delivered messages;
- a live subdomain's last status check found its Cloudflare routing missing, or no verified default inbox;
- a subdomain has used its whole daily send share.

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
1. `cd ~/mail-alias && docker compose exec api mailalias create-admin --username <you> --email <you@...>` (prompts for the password). This is the operator account; it is also the operator's own subdomain.
2. Register the Resend webhook (section above), then run `deploy.sh` again to ship the secret.
3. Run `verify-infra.sh`, then sign in at `https://app.closetcompute.online` (Cloudflare Access, then app login).

Rollback: `deploy/scripts/deploy.sh <previous sha>`. Migrations up to 0005 are additive; run `docker compose run --rm migrate alembic downgrade <rev>` on the host only if a migration itself is the problem.
- **0006** drops `users.default_recipient_id` and the `invites` table. Deploy it only after 0004 has been running for at least a day, so no container still reads the old column.
- **Downgrading below 0005** refuses while any subdomain has no email or password (subdomains created in the app have neither).

## Rolling out the operator release (migrations 0003–0006)

This release turns accounts into subdomains, and its last migration (0006) drops `users.default_recipient_id`. `deploy.sh` runs `migrate` while the old containers are still up, and the old code still loads that column, so they would fail until they are replaced. Stop them first. While they are stopped, mail waits in the Cloudflare queue.

1. Take a backup: `cd ~/mail-alias && docker compose exec worker celery -A mailalias.tasks.celery_app call maintenance.backup`, or check that last night's backup exists in R2.
2. Stop the app containers on the host (the worker also runs beat): `cd ~/mail-alias && docker compose stop api processor worker`.
3. From your machine: `deploy/scripts/deploy.sh`. It applies 0003–0006, then starts the new containers.
4. In Resend, add the `email.delivered` event to the webhook (see above).
5. Sign in. On **Subdomains**, check that `prithvi` (you) and every former account appear with their aliases, then press **Check now** on each.
6. Former accounts can no longer sign in, but API tokens they created still work inside their own subdomain. For each one, open `/s/<label>/tokens` and revoke tokens you don't want to keep.
7. Send one test mail per subdomain and confirm it shows on that subdomain's **Activity** page.

Later contract migrations should drop a column one release after the code stops mapping it, so no stop is needed.

## Edge Worker

The Worker is deployed from a workstation, not CI, so the Cloudflare token stays off GitHub:

```sh
cp edge/wrangler.example.toml edge/wrangler.toml   # once; set the KV namespace id (gitignored)
cd edge && npx wrangler deploy
```

## Landing page

`landing/` is a static Astro site served by Cloudflare Pages (project `closet-mail-landing`) on the apex domain. It is live at https://closetcompute.online: the Pages custom domain replaced the old parking A record on the apex, and `www` is not configured. Site-wide facts such as the invite address live in `landing/src/lib/site.ts`.

**One-time setup:**

1. Create the project: `cd landing && npx wrangler pages project create closet-mail-landing --production-branch main`.
2. Deploy once (below), then in the dashboard open Workers & Pages → `closet-mail-landing` → Custom domains and add the apex domain. Delete any existing A/AAAA/CNAME record on the apex first. Cloudflare then creates the CNAME itself. MX and TXT records stay as they are.
3. For CI deploys, create a **separate** API token with only *Account → Cloudflare Pages → Edit*, and add it to the GitHub repository secrets as `CLOUDFLARE_API_TOKEN`, along with `CLOUDFLARE_ACCOUNT_ID`. Never use the main token here. Without these secrets, CI still builds the site and skips the deploy.

**Deploy by hand** (from a workstation, using the same narrow token):

```sh
cd landing && npm run build && npm run deploy
```

The "Get in touch" buttons open a pre-filled email to the contact address (`invite@prithvi.closetcompute.online`). That address must accept mail: its subdomain needs Email Routing enabled, and the alias must exist (or the subdomain catch-all must be on).

## Adding a subdomain

Each person served gets a subdomain `<label>.closetcompute.online`. The label can't be changed later.

1. **Create it in the app:** Subdomains → New subdomain (label, display name, first inbox, notes), or on the server:
   `docker compose exec api mailalias create-subdomain --label <label> --inbox <address> [--display-name "<name>"]`.
   The first inbox is emailed a verification link and becomes a default inbox. Catch-all starts on.
2. **Add it in Cloudflare by hand:** Email Routing → Settings → Subdomains → add `<label>.closetcompute.online`. Cloudflare adds the MX records (route1/2/3.mx.cloudflare.net) and an SPF TXT record. The zone catch-all rule does not cover a subdomain until it is added, and the app never changes DNS or Email Routing.
3. **Press "Check now"** on the subdomain. It reads the MX and SPF records through the Cloudflare API, the edge flag `s:<label>` in KV, and whether a verified default inbox exists. The same check runs every 15 minutes (`subdomains.check_status`). The API token needs **Zone → DNS → Read** for the zone in `CF_ZONE_ID`; without it the status stays "Not checked".
4. **The person clicks the verification link.** Status turns "Ready" once DNS is in place and an inbox is verified.

Statuses: **Ready**, **DNS missing** (step 2 not done), **No inbox** (no verified default inbox), **Suspended**, **Retired**, **Not checked** (Cloudflare could not be read).

**Send share.** Each subdomain may send `SUBDOMAIN_SENDS_PER_DAY` messages a day (default 40; forwards and replies, one per inbox) out of the global `OUTBOUND_DAILY_CAP`. Change it per subdomain in its detail sheet ("Sends per day"). Over its share, the subdomain's mail waits in the queue until midnight UTC, and the operator is emailed once.

**Catch-all limit.** A subdomain can create at most `SUBDOMAIN_CATCHALL_CREATES_PER_DAY` new catch-all aliases a day (default 200; "New catch-all addresses per day" in its sheet). This stops a spam run from filling the alias table and the KV write budget. Mail to further new addresses is dropped as "catch-all limit", and the operator is emailed once that day.

**Suspend and retire.** Suspending stops forwarding and removes the edge catch-all flag until resumed. Retiring forgets every alias (the addresses stay reserved, and the edge rejects them), disables the inboxes and keeps all history. Your own subdomain can't be suspended or retired.

## Operator account

Only the operator (the admin account) signs in. There is no emailed password reset. To set a new password on the server (this signs out every session):

```sh
docker compose exec api mailalias reset-password --username <operator>
```
