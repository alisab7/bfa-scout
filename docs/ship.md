# `ship.sh` — one-command deploy

`./ship.sh "message"` takes a change from your working tree to **verified
live** in one command: commit → push → backup → pull → migrate → build →
restart → prove it.

---

## Why this exists

The old flow was a chain of manual steps: `git status` → stage → commit →
push → SSH in → `sudo -u bfa git pull` → maybe a migration → `docker compose
build` → `up` → eyeball `/healthz` → **guess** whether the change went live.

That guess failed once, and nearly cost us an import against stale code:

> The droplet's git checkout was already at the right commit, so `git pull`
> said *"Already up to date"*. But the running Docker image had been built
> **before** that commit. Production was executing old code, and every check
> along the way — the pull, the build, `/healthz` returning `200 {"status":
> "ok"}` — reported success.

Every one of those checks verified an *input* to the deploy. None verified
the *output*. `ship.sh` fixes that: the image now bakes in the git SHA it
was built from, `/healthz` reports it, and `ship.sh` refuses to call a
deploy successful unless the **live** SHA equals the SHA it just pushed.

---

## Usage

```bash
./ship.sh "commit message"        # FULL:   commit → push → deploy → verify
./ship.sh push "commit message"   # steps 1–3 only (commit, push, verify push)
./ship.sh deploy                  # steps 4–6 only (deploy what is on origin/main)
./ship.sh status                  # read-only dry run — changes nothing
./ship.sh -h                      # usage
```

`-y` (or `--yes`) anywhere skips the confirmation prompts. Use it only when
you already know what is in your tree — it also means "stage everything
listed", which is exactly the prompt that exists to stop a stray
`cowork_*_prompt.md` getting committed.

### Typical day

```bash
./ship.sh status                     # what would happen?
./ship.sh "Fix squad search ordering"
```

### Deploy something a teammate already pushed

```bash
./ship.sh deploy
```

`deploy` mode ships whatever is on `origin/main`, not your local tree. If
those differ it says so and asks first.

---

## The six steps

| # | Step | Stops the deploy when |
|---|------|-----------------------|
| 1 | **Pre-flight** — assert branch is `main`; list changed/untracked files | you are on a side branch; you decline the staging prompt |
| 2 | **Commit + push** to `origin/main` | the commit or push fails |
| 3 | **Verify the push landed** — `git ls-remote origin main` must equal local `HEAD` | the remote does not have your commit |
| 4 | **Deploy** over one non-interactive SSH call (below) | any sub-step below |
| 5 | **SHA verification** — live `/healthz` `sha` must equal the pushed short SHA | they differ, or the image reports no SHA at all |
| 6 | **Summary** — commit, migrations applied, live SHA, healthz | — |

Step 4 is a **single** SSH call. There is never a "now paste these commands
on the server" stage. On the droplet, in order:

| | Sub-step | Stops when |
|---|---|---|
| a | `scripts/backup_to_spaces.sh` | the backup fails — **we never deploy without one** |
| b | `sudo -u bfa git pull origin main`, then compare the checked-out SHA to the pushed SHA | they differ (this is the "Already up to date but the push never landed" case, called out by name) |
| c | apply new migrations (see below) | any migration fails — **nothing is built or restarted on a half-migrated DB** |
| d | `docker compose -f docker-compose.prod.yml build app` then `up -d --force-recreate app`, then nudge nginx to re-resolve the upstream | the build or the recreate fails |
| e | drain `https://localhost/healthz` (`-k`; self-signed origin cert), ~8 tries, first connection errors tolerated | it never returns `status: ok` — the last 50 lines of `docker compose logs app` are dumped |

Every stop prints a `FATAL:`/`STOP:` line saying what happened and exits
non-zero. Nothing continues silently.

---

## How the SHA gets from your commit to `/healthz`

This is the mechanism the whole tool is built around.

```
git rev-parse HEAD                      (on the droplet, after the pull)
        │
        ▼  exported as GIT_SHA
docker-compose.prod.yml   build.args.GIT_SHA: ${GIT_SHA:-unknown}
        │
        ▼  --build-arg
Dockerfile                ARG GIT_SHA=unknown
                          ENV GIT_SHA=${GIT_SHA}
        │
        ▼  os.environ, read ONCE at import
app/healthz.py            GIT_SHA = _build_sha()
        │
        ▼
GET /healthz  →  {"status":"ok","sha":"86b1e67"}
        │
        ▼  compared against the SHA ship.sh pushed
        MATCH → SHIPPED       MISMATCH → STOP
```

Notes:

* The `ARG`/`ENV` pair sits at the **end** of the Dockerfile, after the
  expensive `pip install` and `chown` layers, so a new SHA only invalidates
  one cheap layer.
* `ship.sh` bakes the SHA it reads **from the droplet's checkout after the
  pull**, and only after asserting that checkout matches what you pushed.
  So the value in the image genuinely describes the source that was built.
* `/healthz` stays dependency-light: one environment lookup at import, no
  file read, no DB call, no subprocess. The existing DB probe and the
  `{"status":"ok"}` shape are untouched — `sha` is purely additive.
* Without the build arg (a plain `docker build`, or the app run directly)
  it degrades to `"sha":"unknown"` and still returns `200`, so a local
  container's healthcheck still passes.
* `ship.sh` treats `"sha":"unknown"` on a **deploy** as a failure, not a
  pass: an image that cannot identify itself cannot be verified.

---

## Migrations

`ship.sh` applies new `migrations/*.sql` automatically, before the build,
using a ledger on the droplet at `/home/bfa/bfa-scout/.deployed_migrations`.
Each line is `<sha256>  <filename>`.

For each `migrations/*.sql` not named in the ledger:

```bash
psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 -P pager=off -f <file> </dev/null
```

then the file is recorded. `-P pager=off` is **not optional**: a wide result
set once opened psql's pager, which left a transaction `idle in transaction`
and blocked the next run behind its locks.

* **Idempotent** — a recorded migration is never applied twice.
* **First run seeds a baseline.** The ledger does not exist yet. On the
  first `ship.sh` deploy it is seeded from the migrations present in the
  droplet checkout *before* that run's pull — i.e. everything production has
  already had applied — and **none of them are re-run**. Anything the pull
  brings in is applied normally. The baselined list is printed.
  * This assumes every migration already in the droplet checkout really has
    been applied. If one has not, apply it by hand **before** the first
    `ship.sh` deploy.
* **Edited history is flagged, not re-run.** If a recorded migration's
  contents have changed since it was applied, you get a warning and it is
  left alone. Write a new migration file instead.

---

## `status` mode

Read-only. It changes nothing, locally or on the droplet — no fetch, no
build, no migration, no restart. It reports:

* current branch and `HEAD`
* uncommitted/untracked files, with known junk (`cowork_*_prompt.md`,
  `exports/`, `.DS_Store`) listed separately as *never staged*
* commits not yet on `origin/main`
* the droplet's checked-out SHA and container states
* **migrations that would run** — local `migrations/*.sql` vs the droplet
  ledger
* the **live** `/healthz` body, and live SHA vs local `HEAD`

A clean, fully-deployed tree looks like:

```
    * nothing to commit
    * origin/main == local HEAD (nothing unpushed)
    * no pending migrations (17 in ledger)
    * live SHA 86b1e67 == local HEAD 86b1e67
```

---

## What it will not do

* Ship from a branch other than `main`.
* `git add .`. It lists what it found and asks; `[s]elect` lets you pick
  file by file. `cowork_*_prompt.md`, `exports/` and `.DS_Store` are never
  offered.
* Deploy without a fresh backup.
* Build or restart on a half-migrated database.
* Call a deploy successful without a matching live SHA.

---

## Configuration

Defaults are the production droplet. Override via environment if needed:

| Variable | Default |
|---|---|
| `SHIP_SSH_KEY` | `~/.ssh/bfa_scout_new` |
| `SHIP_SSH_HOST` | `root@164.90.181.13` |
| `SHIP_REMOTE_DIR` | `/home/bfa/bfa-scout` |
| `SHIP_REMOTE_GIT_USER` | `bfa` (git runs as `bfa`; docker as `root`) |
| `SHIP_BRANCH` | `main` |
| `SHIP_COMPOSE_FILE` | `docker-compose.prod.yml` |
| `SHIP_LEDGER` | `$SHIP_REMOTE_DIR/.deployed_migrations` |
| `SHIP_HEALTH_URL` | `https://localhost/healthz` |
| `SHIP_HEALTH_TRIES` / `SHIP_HEALTH_SLEEP` | `8` / `5` |

`NO_COLOR=1` disables colour.

---

## Self-test

```bash
bash scripts/ship_selftest.sh
```

Runs offline: no network, no droplet, no production. It builds a throwaway
git triangle in a temp directory and puts stubs for
`ssh`/`sudo`/`docker`/`psql`/`curl` first on `PATH`. The `ssh` stub does not
fake the deploy — it **executes ship.sh's own server-side script** against
the fake droplet, so the ledger logic and the pull/health/SHA gates are the
real code paths.

It asserts `ship.sh` stops on: push-not-landed (both locally and after the
droplet pull), backup failure, migration failure, build failure, `/healthz`
never healthy, live-SHA mismatch, and an image reporting no SHA — plus the
happy path, ledger idempotency, junk exclusion, and clean-tree `status`.

---

## Relationship to `scripts/deploy.sh`

`scripts/deploy.sh` is unchanged and still works as the **on-droplet manual
fallback** (`ssh` in, `cd /home/bfa/bfa-scout && ./scripts/deploy.sh`). It
pulls, builds the whole stack, and gates on `/healthz`.

It is deliberately *not* what `ship.sh` calls, because it has no backup
step, no migration handling, and — critically — no SHA verification: its
health gate is exactly the check that passed while production ran stale
code. Reach for `ship.sh` by default; keep `deploy.sh` for the case where
you are already on the box and just want the stack rebuilt.
