# BFA-Scout — Deployment & Operations (Phase 8, v1.0.0)

The complete, from-scratch deploy + ops runbook. Written so a developer
who has never seen this project can stand it up and keep it running.

---

## 1. Architecture

```
                      Internet
                         │
                 ┌───────▼────────┐
                 │   Cloudflare   │  Full (strict) TLS, "Always HTTPS",
                 │   (proxy/CDN)  │  caches static, public cert at edge
                 └───────┬────────┘
                         │  re-encrypts to origin (self-signed cert)
                 ┌───────▼────────┐   DigitalOcean droplet
                 │  nginx:alpine  │   Ubuntu 24.04, 2GB/1vCPU, Frankfurt
                 │  :80 → :443    │   docker-compose.prod.yml
                 │  TLS terminate │
                 └───────┬────────┘
                         │  proxy_pass http://app:5000
                 ┌───────▼────────┐
                 │  app (gunicorn)│   Flask + WeasyPrint, 2 workers ×
                 │  :5000 /healthz│   4 threads, non-root (uid 1000)
                 └───┬────────┬───┘
                     │        │
        ┌────────────▼──┐  ┌──▼─────────────────┐
        │ DO Managed PG │  │ DO Spaces (S3 CDN) │
        │ Postgres 15   │  │ player photos +    │
        │ TLS required  │  │ nightly DB backups │
        └───────────────┘  └────────────────────┘
```

- **Photos**: uploaded → Pillow re-encode (400×400 JPEG) → Spaces
  `photos/<player_id>.jpg`, served via the Spaces CDN. Local
  filesystem is **never** used for photos in production
  (`app/storage.py` switches on `SPACES_BUCKET`).
- **Passport PDFs**: WeasyPrint embeds the photo as a base64 data-URI
  fetched from Spaces at render time, so the PDF is self-contained.
- **Logs**: stdout/stderr → `docker logs` / journald. No log files in
  the container.
- **Deviation from spec**: no custom `nginx/Dockerfile`. The stock
  `nginx:alpine` image with the site config + origin certs bind-mounted
  is functionally identical and simpler to reason about. The compose
  file documents this inline.

---

## 2. Initial provisioning (DigitalOcean console — ~45 min, Ali)

### Droplet
- Ubuntu 24.04 LTS, $12/mo (2GB RAM / 1 vCPU / 50GB SSD).
- Region: **Frankfurt** (closest low-latency to Bahrain) — Spaces and
  Managed PG **must be the same region**.
- Auth: SSH key. Hostname `bfa-scout-prod`. Note the public IP.

### Managed PostgreSQL
- Engine PostgreSQL 15, Basic plan $15/mo (1GB/10GB).
- Same region as the droplet.
- Create database `bfa_scout`. Copy the **connection string** (it
  already includes `?sslmode=require` — keep it).
- Under "Trusted Sources", add the droplet so only it can connect.

### Spaces
- $5/mo / 250GB, same region.
- Bucket `bfa-scout-photos`. File listing **disabled**. CDN **enabled**.
- Generate a Spaces access key + secret. Note the endpoint
  (e.g. `https://fra1.digitaloceanspaces.com`) and region (`fra1`).

---

## 3. DNS + Cloudflare (~10 min, Ali)

1. Add the temp domain to Cloudflare.
2. DNS: `A @ → <droplet-ip>` (Proxied), `A www → <droplet-ip>` (Proxied).
3. SSL/TLS → **Full (strict)**. Always Use HTTPS **ON**. Min TLS 1.2.
   Auto HTTPS Rewrites **ON**.
4. Verify from a laptop: `dig <temp-domain>` resolves; you can
   `ssh bfa@<droplet-ip>`.

---

## 4. First deploy (~30 min, on the droplet)

```bash
# 4.1 Base packages (as root)
ssh root@<droplet-ip>
adduser bfa && usermod -aG sudo bfa
apt-get update && apt-get install -y \
    docker.io docker-compose-plugin git awscli postgresql-client
usermod -aG docker bfa
systemctl enable --now docker

# 4.2 Clone (as bfa)
su - bfa
git clone https://github.com/<your-org>/bfa-scout.git
cd bfa-scout

# 4.3 Environment
cp .env.production.example .env.production
nano .env.production        # fill SECRET_KEY (python -c "import
                            # secrets;print(secrets.token_hex(32))"),
                            # DATABASE_URL, SPACES_*, ADMIN_*

# 4.4 Self-signed origin cert (Cloudflare validates the proxy, not CN)
mkdir -p nginx/certs
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout nginx/certs/origin.key \
    -out    nginx/certs/origin.crt \
    -subj "/CN=bfa-scout"

# 4.5 Load schema into the FRESH managed DB (no dev data carry-over)
set -a; source .env.production; set +a
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f schema.sql

# 4.6 Build + start
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d

# 4.7 Seed the first admin (idempotent — safe to re-run)
docker compose -f docker-compose.prod.yml exec app \
    python scripts/bootstrap_admin.py

# 4.8 Verify
sleep 20
docker compose -f docker-compose.prod.yml ps          # both healthy
curl -fsS -k https://localhost/healthz                 # {"status":"ok"}
curl -fsS https://<temp-domain>/healthz                # via Cloudflare

# 4.9 Backup cron (belt-and-braces over DO's own PG backups)
chmod +x scripts/*.sh
crontab -e
# add:
0 3 * * * /home/bfa/bfa-scout/scripts/backup_to_spaces.sh >> /var/log/bfa-backup.log 2>&1
```

### Post-deploy smoke tests
1. `https://<temp-domain>/auth/login` renders.
2. Log in as the bootstrapped admin.
3. `/players` — empty list (fresh DB).
4. Add a player via the UI.
5. Upload a photo → confirm the object appears in the Spaces bucket
   (`photos/<id>.jpg`) and the card shows it; nothing written to the
   container filesystem.
6. Generate that player's passport PDF — downloads, photo embedded.
7. `/nt` — loads as admin (empty squad on a fresh DB).
8. `/healthz` → 200.
9. Cloudflare Analytics shows the requests.
10. `docker compose -f docker-compose.prod.yml logs --tail=50 app` —
    clean access logs, no tracebacks.

---

## 5. Updating production

```bash
ssh bfa@<droplet-ip>
cd /home/bfa/bfa-scout
./scripts/deploy.sh
```

`deploy.sh` pulls master, asserts `.env.production` + origin certs
exist, rebuilds, recreates the stack, and **fails loudly** if
`/healthz` doesn't pass within 90s (dumping the last 50 app log lines).
Re-runnable.

---

## 6. Restore from backup

```bash
cd /home/bfa/bfa-scout
./scripts/restore_from_spaces.sh                 # lists backups
./scripts/restore_from_spaces.sh bfa-scout-YYYY-MM-DD-HHMM.sql.gz
```

DESTRUCTIVE — drops & recreates `public`, then reloads. Requires
typing the exact `restore <filename>` confirmation. Never automated.
DO Managed PG also keeps its own automated backups (console →
Database → Backups) as a second line of defence.

---

## 7. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `deploy.sh` fails at healthcheck | App can't reach DB | `docker compose logs app`; check `DATABASE_URL`, that the droplet is in PG "Trusted Sources", `?sslmode=require` present |
| 502 from Cloudflare | app container down/unhealthy | `docker compose ps`; `docker compose restart app` |
| 525/526 SSL from Cloudflare | origin cert missing/expired | regenerate `nginx/certs/origin.{crt,key}` (step 4.4), `docker compose restart nginx` |
| Photos 404 / show placeholder | Spaces creds or bucket region wrong | check `SPACES_*` in `.env.production`; bucket region must equal `SPACES_REGION`; ACL public-read |
| Passport PDF has no photo | Spaces `get_object` failing | photo is optional — PDF still renders. Check Spaces key has read on the bucket |
| Passport PDF 500 | WeasyPrint native libs | rebuild image (Dockerfile installs libpango/cairo/fonts); `docker compose build --no-cache app` |
| OOM / worker killed mid-PDF | too many gunicorn workers | keep `workers=2` in `gunicorn.conf.py`; scale the droplet before raising workers (§9) |
| Bulk import 413 | file > 50MB | `client_max_body_size` in `nginx/conf.d/bfa-scout.conf` |
| Admin can't log in after deploy | seed didn't run / wrong env names | re-run `scripts/bootstrap_admin.py` (idempotent); it accepts ADMIN_* or INITIAL_ADMIN_* |
| Legitimate users getting 429 on `/auth/login` | rate limit too aggressive | increase `rate` (e.g. `20r/m`) or `burst` (e.g. `10`) in `nginx/conf.d/bfa-scout.conf`; `docker compose restart nginx` to apply |

---

## 11. Admin password rotation (post-launch, one-time)

After BFA-Scout is live and before handing access to staff:

```bash
# 1. Log in to https://<domain>/auth/login as the bootstrap admin
# 2. Go to /admin/users → edit admin user → Reset Password
#    New password must pass complexity: ≥12 chars, upper + lower + digit
# 3. SSH into the droplet and remove the bootstrap credentials from .env
ssh -i your-key root@164.90.181.13
cd /home/bfa/bfa-scout
nano .env.production
# Comment out or remove:
#   ADMIN_EMAIL=...
#   ADMIN_PASSWORD=...
# 4. Restart app to apply env change (no rebuild needed)
docker compose -f docker-compose.prod.yml restart app
# 5. Verify bootstrap script is now a no-op (no password reset):
docker compose -f docker-compose.prod.yml exec app python scripts/bootstrap_admin.py
# Expected: "OK — 1 admin user(s) present."
```

---

## 8. Where the logs are

- **App + access logs**: `docker compose -f docker-compose.prod.yml
  logs -f app` (gunicorn → stdout).
- **Nginx**: `docker compose -f docker-compose.prod.yml logs -f nginx`.
- **Backup cron**: `/var/log/bfa-backup.log`.
- **Docker/systemd**: `journalctl -u docker`.
- **Cloudflare**: dashboard → Analytics / Security events.
- No log files inside containers — everything is stdout/journald.

---

## 9. Scaling up

Single-droplet is sized for BFA's scale (single-digit concurrent
admins/scouts). When needed, in order of cost/benefit:

1. **Droplet resize** (DO console, ~1 min downtime): 2GB→4GB lets you
   raise `workers` 2→4 in `gunicorn.conf.py` (WeasyPrint is the memory
   driver — budget ~250MB transient/worker).
2. **PG plan bump**: Basic→larger if connection count or storage grows
   (the pool in `app/db.py` is maxconn=10 per worker).
3. **Spaces**: scales transparently; no action.
4. **Out of scope for v1** (deferred, not needed at this scale):
   external APM (Sentry), read replicas, multi-region, CI/CD,
   staging env, BFA-official subdomain swap.

---

## 10. Maintenance mode

After v1.0.0 the project is feature-complete. Routine ops only:
deploy on bug-fix commits (§5), watch `/healthz`, rotate the Spaces
backup retention (auto, 30 days). Any new feature is a new phase.
