#!/usr/bin/env bash
#
# scripts/ship_selftest.sh — offline self-test for ship.sh.
#
#   bash scripts/ship_selftest.sh
#
# Touches NOTHING real: no droplet, no production, no network. It builds a
# throwaway git triangle (origin.git <- work clone -> droplet clone) in a temp
# directory and puts stubs for ssh/sudo/docker/psql/curl/sha256sum first on
# PATH. The `ssh` stub does not fake the deploy — it EXECUTES ship.sh's own
# server-side script locally against the fake droplet, so the migration
# ledger logic, the pull/SHA comparison and the health/SHA gates are the real
# code paths, not re-implementations.
#
# Every failure mode ship.sh must stop on gets its own scenario, asserted by
# exit code AND by a message the operator would actually see.
set -uo pipefail

SHIP="$(cd "$(dirname "$0")/.." && pwd)/ship.sh"
[ -f "$SHIP" ] || { echo "cannot find ship.sh next to $0"; exit 1; }

ROOT="$(mktemp -d -t shipselftest)"
BIN="$ROOT/bin"; mkdir -p "$BIN"
REAL_GIT="$(command -v git)"
PASS=0; FAIL=0

cleanup() { rm -rf "$ROOT"; }
trap cleanup EXIT

# ── stubs ─────────────────────────────────────────────────────────────────────
cat > "$BIN/ssh" <<'EOS'
#!/usr/bin/env bash
# Ignore ssh's own flags; the last argument is the remote command. Run it
# locally with the deploy script still arriving on stdin, exactly as sshd would.
last=""; for a in "$@"; do last="$a"; done
exec bash -c "$last"
EOS

cat > "$BIN/sudo" <<'EOS'
#!/usr/bin/env bash
# `sudo -u <user> cmd ...` -> just run cmd; the harness is already that user.
while [ $# -gt 0 ]; do
    case "$1" in -u) shift 2 ;; -*) shift ;; *) break ;; esac
done
exec "$@"
EOS

cat > "$BIN/sha256sum" <<'EOS'
#!/usr/bin/env bash
exec shasum -a 256 "$@"
EOS

cat > "$BIN/psql" <<'EOS'
#!/usr/bin/env bash
# Assert ship.sh always passes the anti-pager flags (a pager left a
# transaction idle-in-transaction in production once).
case " $* " in *" -P pager=off "*) ;; *) echo "psql stub: MISSING -P pager=off" >&2; exit 99 ;; esac
case " $* " in *" -v ON_ERROR_STOP=1 "*) ;; *) echo "psql stub: MISSING ON_ERROR_STOP" >&2; exit 98 ;; esac
f=""; prev=""
for a in "$@"; do [ "$prev" = "-f" ] && f="$a"; prev="$a"; done
b="$(basename "${f:-none}")"
if [ -n "${MOCK_MIGRATION_FAIL:-}" ] && [ "$b" = "$MOCK_MIGRATION_FAIL" ]; then
    echo "psql: ERROR:  syntax error at or near \"boom\"" >&2
    exit 3
fi
echo "psql stub: applied $b"
EOS

cat > "$BIN/docker" <<'EOS'
#!/usr/bin/env bash
case " $* " in
    *" build "*)
        if [ -n "${MOCK_BUILD_FAIL:-}" ]; then echo "docker stub: build failed" >&2; exit 1; fi
        echo "docker stub: built app (GIT_SHA=${GIT_SHA:-<unset>})"
        echo "${GIT_SHA:-unset}" > "${MOCK_BUILT_SHA_FILE:-/dev/null}"
        ;;
    *" up "*)    echo "docker stub: recreated app" ;;
    *" exec "*)  echo "docker stub: nginx reloaded" ;;
    *" logs "*)  echo "docker stub: --- fake app log line 1 ---"; echo "docker stub: --- fake app log line 2 ---" ;;
    *" ps "*)    echo "bfa-scout-app-1 Up 1 minute (healthy)"; echo "bfa-scout-nginx-1 Up 3 months" ;;
    *) echo "docker stub: ignoring $*" ;;
esac
EOS

cat > "$BIN/curl" <<'EOS'
#!/usr/bin/env bash
# Health responses are driven by MOCK_HEALTH_*: fail the first N attempts,
# then return a body whose sha is whatever the last "build" baked in
# (or MOCK_LIVE_SHA to force a mismatch / a pre-GIT_SHA image).
CNT="${MOCK_CURL_COUNT_FILE:-/dev/null}"
n=0; [ -f "$CNT" ] && n="$(cat "$CNT")"
n=$((n + 1)); echo "$n" > "$CNT"
if [ "$n" -le "${MOCK_HEALTH_FAIL_FIRST:-0}" ]; then
    echo "curl: (7) Failed to connect" >&2; exit 7
fi
if [ "${MOCK_HEALTH_NEVER:-0}" = "1" ]; then
    echo "curl: (7) Failed to connect" >&2; exit 7
fi
sha="${MOCK_LIVE_SHA:-}"
if [ -z "$sha" ] && [ -f "${MOCK_BUILT_SHA_FILE:-/nonexistent}" ]; then
    sha="$(cut -c1-7 < "$MOCK_BUILT_SHA_FILE")"
fi
if [ "${MOCK_HEALTH_NO_SHA:-0}" = "1" ]; then
    printf '{"status":"ok"}'
else
    printf '{"sha":"%s","status":"ok"}' "$sha"
fi
EOS

cat > "$BIN/git" <<'EOS'
#!/usr/bin/env bash
# Passthrough, except: MOCK_LSREMOTE_SHA forces `git ls-remote` to report a
# different SHA — that is how "the push silently did not land" is simulated.
if [ -n "${MOCK_LSREMOTE_SHA:-}" ] && [ "${1:-}" = "ls-remote" ]; then
    echo "$MOCK_LSREMOTE_SHA	refs/heads/main"; exit 0
fi
exec "$REAL_GIT_BIN" "$@"
EOS

chmod +x "$BIN"/*
export REAL_GIT_BIN="$REAL_GIT"
export PATH="$BIN:$PATH"

# ── fake world ────────────────────────────────────────────────────────────────
"$REAL_GIT" init -q --bare "$ROOT/origin.git"
"$REAL_GIT" -C "$ROOT/origin.git" symbolic-ref HEAD refs/heads/main
"$REAL_GIT" clone -q "$ROOT/origin.git" "$ROOT/work"
cd "$ROOT/work"
"$REAL_GIT" config user.email selftest@example.com
"$REAL_GIT" config user.name "ship selftest"
"$REAL_GIT" symbolic-ref HEAD refs/heads/main

mkdir -p migrations scripts
cat > scripts/backup_to_spaces.sh <<'EOS'
#!/usr/bin/env bash
set -euo pipefail
if [ -n "${MOCK_BACKUP_FAIL:-}" ]; then echo "pg_dump: connection refused" >&2; exit 1; fi
echo "backup stub: dumped + uploaded"
EOS
echo "CREATE TABLE a();" > migrations/001_a.sql
echo "CREATE TABLE b();" > migrations/002_b.sql
echo "services: {app: {build: .}}" > docker-compose.prod.yml
cp "$SHIP" ./ship.sh
chmod +x ship.sh scripts/backup_to_spaces.sh
"$REAL_GIT" add -A >/dev/null
"$REAL_GIT" commit -qm "seed"
"$REAL_GIT" push -q origin main 2>/dev/null || "$REAL_GIT" push -q origin HEAD:main

"$REAL_GIT" clone -q "$ROOT/origin.git" "$ROOT/droplet"
[ -f "$ROOT/droplet/scripts/backup_to_spaces.sh" ] \
    || { echo "harness bug: fake droplet clone has no working tree"; exit 1; }
printf 'DATABASE_URL=postgresql://fake/fake\n' > "$ROOT/droplet/.env.production"
# A stale remote: has the seed commit but never receives anything after it.
"$REAL_GIT" clone -q --bare "$ROOT/origin.git" "$ROOT/stale.git"

export SHIP_SSH_KEY=/dev/null
export SHIP_SSH_HOST=fake@fake
export SHIP_REMOTE_DIR="$ROOT/droplet"
export SHIP_REMOTE_GIT_USER="$(id -un)"
export SHIP_LEDGER="$ROOT/droplet/.deployed_migrations"
export SHIP_HEALTH_URL="http://fake/healthz"
export SHIP_HEALTH_TRIES=3
export SHIP_HEALTH_SLEEP=0
export SHIP_COMPOSE_FILE=docker-compose.prod.yml
export MOCK_BUILT_SHA_FILE="$ROOT/built_sha"
export MOCK_CURL_COUNT_FILE="$ROOT/curl_count"
export NO_COLOR=1

reset_mocks() {
    unset MOCK_BACKUP_FAIL MOCK_MIGRATION_FAIL MOCK_BUILD_FAIL \
          MOCK_HEALTH_NEVER MOCK_HEALTH_FAIL_FIRST MOCK_LIVE_SHA \
          MOCK_HEALTH_NO_SHA MOCK_LSREMOTE_SHA 2>/dev/null || true
    rm -f "$MOCK_CURL_COUNT_FILE"
}

OUT="$ROOT/out.txt"
run_ship() { ( cd "$ROOT/work" && ./ship.sh "$@" ) >"$OUT" 2>&1; echo $?; }

check() {
    # check <label> <expected_exit> <actual_exit> <expected substring>
    local label="$1" want="$2" got="$3" needle="$4"
    if [ "$got" = "$want" ] && grep -q -- "$needle" "$OUT"; then
        printf '  PASS  %s (exit %s)\n' "$label" "$got"; PASS=$((PASS + 1))
    else
        printf '  FAIL  %s — wanted exit %s + %s, got exit %s\n' "$label" "$want" "$needle" "$got"
        sed 's/^/          /' "$OUT" | tail -25
        FAIL=$((FAIL + 1))
    fi
}

SEQ=0
new_commit() {
    SEQ=$((SEQ + 1))
    ( cd "$ROOT/work" && echo "change $SEQ $(date +%s) $RANDOM" > change.txt \
      && "$REAL_GIT" add change.txt >/dev/null )
}
new_migration() {
    ( cd "$ROOT/work" && echo "CREATE TABLE $1();" > "migrations/$1.sql" && "$REAL_GIT" add -A >/dev/null )
}

echo
echo "=== ship.sh self-test (no network, no droplet, no production) ==="
echo

# ── 1. FULL happy path: ledger baseline is seeded, nothing re-applied ────────
reset_mocks; new_commit
rc="$(run_ship "first ship" -y)"
check "happy path: full deploy verifies live SHA" 0 "$rc" "SHIPPED"
grep -q "seeding a BASELINE" "$OUT" \
    && { echo "  PASS  first run baselines existing migrations instead of re-applying"; PASS=$((PASS+1)); } \
    || { echo "  FAIL  expected a baseline seed on the first run"; FAIL=$((FAIL+1)); }
grep -q "no new migrations" "$OUT" \
    && { echo "  PASS  baselined migrations are NOT applied"; PASS=$((PASS+1)); } \
    || { echo "  FAIL  baseline run should apply nothing"; FAIL=$((FAIL+1)); }

# ── 2. A genuinely new migration is detected and applied exactly once ────────
reset_mocks; new_migration 003_c
rc="$(run_ship "adds a migration" -y)"
check "new migration detected + applied" 0 "$rc" "SHIP_MIGRATION_APPLIED=003_c.sql"
reset_mocks; new_commit
rc="$(run_ship "no new migration" -y)"
check "ledger is idempotent: not re-applied" 0 "$rc" "no new migrations"
if grep -q "applying 003_c.sql" "$OUT"; then
    echo "  FAIL  003_c.sql was applied twice"; FAIL=$((FAIL+1))
else
    echo "  PASS  003_c.sql was not applied a second time"; PASS=$((PASS+1))
fi

# ── 3. STOP: the push did not land (local ls-remote disagrees) ───────────────
reset_mocks; new_commit
MOCK_LSREMOTE_SHA=0000000000000000000000000000000000000000 \
    rc="$(MOCK_LSREMOTE_SHA=0000000000000000000000000000000000000000 run_ship "push wont land" -y)"
check "STOP on push-not-landed (local verify)" 1 "$rc" "push did not land"

# ── 4. STOP: droplet says 'Already up to date' but is on the wrong commit ────
reset_mocks; new_commit
( cd "$ROOT/droplet" && "$REAL_GIT" remote set-url origin "$ROOT/stale.git" )
rc="$(run_ship "droplet cannot see this commit" -y)"
check "STOP on droplet SHA mismatch after pull" 1 "$rc" "the push did NOT land"
grep -q "Already up to date" "$OUT" \
    && { echo "  PASS  the 'Already up to date' near-miss is named explicitly"; PASS=$((PASS+1)); } \
    || { echo "  FAIL  expected the 'Already up to date' diagnosis"; FAIL=$((FAIL+1)); }
( cd "$ROOT/droplet" && "$REAL_GIT" remote set-url origin "$ROOT/origin.git" && "$REAL_GIT" pull -q origin main )

# ── 5. STOP: backup fails -> never deploy without one ────────────────────────
reset_mocks; new_commit
rc="$(MOCK_BACKUP_FAIL=1 run_ship "backup will fail" -y)"
check "STOP when the backup fails" 1 "$rc" "refusing to deploy without a fresh backup"
if grep -q "docker stub: built app" "$OUT"; then
    echo "  FAIL  it built despite the failed backup"; FAIL=$((FAIL+1))
else
    echo "  PASS  nothing was built after the backup failed"; PASS=$((PASS+1))
fi

# ── 6. STOP: a migration fails -> never build on a half-migrated DB ──────────
reset_mocks; new_migration 004_bad
rc="$(MOCK_MIGRATION_FAIL=004_bad.sql run_ship "bad migration" -y)"
check "STOP when a migration fails" 1 "$rc" "NOT building, NOT restarting"
if grep -q "docker stub: built app" "$OUT"; then
    echo "  FAIL  it built on a half-migrated database"; FAIL=$((FAIL+1))
else
    echo "  PASS  no build/restart after a failed migration"; PASS=$((PASS+1))
fi
if grep -q "004_bad.sql" "$SHIP_LEDGER"; then
    echo "  FAIL  a failed migration was recorded in the ledger"; FAIL=$((FAIL+1))
else
    echo "  PASS  a failed migration is NOT recorded in the ledger"; PASS=$((PASS+1))
fi
( cd "$ROOT/work" && rm -f migrations/004_bad.sql && "$REAL_GIT" add -A >/dev/null \
  && "$REAL_GIT" commit -qm "drop bad migration" && "$REAL_GIT" push -q origin main )
( cd "$ROOT/droplet" && "$REAL_GIT" pull -q origin main )

# ── 7. STOP: /healthz never comes back ───────────────────────────────────────
reset_mocks; new_commit
rc="$(MOCK_HEALTH_NEVER=1 run_ship "health never ok" -y)"
check "STOP when /healthz never returns ok" 1 "$rc" "never returned status=ok"
grep -q "fake app log line" "$OUT" \
    && { echo "  PASS  app logs are dumped on health failure"; PASS=$((PASS+1)); } \
    || { echo "  FAIL  expected the last app logs on health failure"; FAIL=$((FAIL+1)); }

# ── 8. Transient SSL/connection errors early in the drain are tolerated ──────
reset_mocks; new_commit
rc="$(MOCK_HEALTH_FAIL_FIRST=2 run_ship "slow to come up" -y)"
check "tolerates the first couple of connection errors" 0 "$rc" "SHIPPED"

# ── 9. STOP: live SHA differs -> the deploy did not take ─────────────────────
reset_mocks; new_commit
rc="$(MOCK_LIVE_SHA=badbad1 run_ship "stale image" -y)"
check "STOP on live-SHA mismatch (the near-miss this tool exists for)" 1 "$rc" "the deploy did NOT take"

# ── 10. STOP: image predates the build arg -> unverifiable, not 'fine' ───────
reset_mocks; new_commit
rc="$(MOCK_HEALTH_NO_SHA=1 run_ship "image without GIT_SHA" -y)"
check "STOP when /healthz reports no sha at all" 1 "$rc" "CANNOT be verified"

# ── 11. STOP: docker build fails ─────────────────────────────────────────────
reset_mocks; new_commit
rc="$(MOCK_BUILD_FAIL=1 run_ship "build fails" -y)"
check "STOP when the image build fails" 1 "$rc" "docker build failed"

# ── 12. Junk is never staged; real changes are ───────────────────────────────
reset_mocks
( cd "$ROOT/work" && echo x > cowork_selftest_prompt.md && mkdir -p exports && echo x > exports/a.csv \
  && echo real > real_change.txt )
rc="$(run_ship status)"
if grep -q "real_change.txt" "$OUT" \
   && grep -q "cowork_selftest_prompt.md" "$OUT" \
   && ! ( sed -n '/uncommitted\/untracked/,/ignored as junk/p' "$OUT" | grep -q "cowork_selftest_prompt" ) \
   && ! ( sed -n '/uncommitted\/untracked/,/ignored as junk/p' "$OUT" | grep -q "exports/" ); then
    echo "  PASS  status lists real changes, quarantines cowork_*_prompt.md and exports/"; PASS=$((PASS+1))
else
    echo "  FAIL  junk filtering wrong"; sed 's/^/          /' "$OUT" | head -25; FAIL=$((FAIL+1))
fi
rc="$(run_ship "stage only the real file" -y)"
check "full run stages the real file only" 0 "$rc" "SHIPPED"
if ( cd "$ROOT/work" && "$REAL_GIT" log -1 --name-only --format= ) | grep -q "cowork_selftest_prompt.md"; then
    echo "  FAIL  a cowork_*_prompt.md got committed"; FAIL=$((FAIL+1))
else
    echo "  PASS  no cowork_*_prompt.md in the commit"; PASS=$((PASS+1))
fi
( cd "$ROOT/work" && rm -rf cowork_selftest_prompt.md exports )

# ── 13. status on a clean, in-sync tree ──────────────────────────────────────
reset_mocks
rc="$(run_ship status)"
if [ "$rc" = "0" ] \
   && grep -q "nothing to commit" "$OUT" \
   && grep -q "no pending migrations" "$OUT" \
   && grep -q "live SHA .* == local HEAD" "$OUT" \
   && grep -q "nothing was changed" "$OUT"; then
    echo "  PASS  clean tree: nothing to commit, no pending migrations, live SHA matches"; PASS=$((PASS+1))
else
    echo "  FAIL  clean-tree status"; sed 's/^/          /' "$OUT"; FAIL=$((FAIL+1))
fi

# ── 14. status reports a trivial local change, then stops reporting it ───────
( cd "$ROOT/work" && echo "trivial" >> README_TRIVIAL.txt )
rc="$(run_ship status)"
grep -q "README_TRIVIAL.txt" "$OUT" \
    && { echo "  PASS  status shows a trivial change as uncommitted"; PASS=$((PASS+1)); } \
    || { echo "  FAIL  status missed a trivial change"; FAIL=$((FAIL+1)); }
( cd "$ROOT/work" && rm -f README_TRIVIAL.txt )
rc="$(run_ship status)"
if grep -q "README_TRIVIAL.txt" "$OUT"; then
    echo "  FAIL  status still reports a reverted change"; FAIL=$((FAIL+1))
else
    echo "  PASS  after reverting, status is clean again"; PASS=$((PASS+1))
fi

# ── 15. push mode stops before touching the droplet ──────────────────────────
reset_mocks
( cd "$ROOT/work" && echo p > push_only.txt )
rc="$(run_ship push "push only" -y)"
if [ "$rc" = "0" ] && grep -q "Deploy it with" "$OUT" && ! grep -q "docker stub" "$OUT"; then
    echo "  PASS  push mode commits+pushes and never touches the droplet"; PASS=$((PASS+1))
else
    echo "  FAIL  push mode"; sed 's/^/          /' "$OUT"; FAIL=$((FAIL+1))
fi
rc="$(run_ship deploy -y)"
check "deploy mode ships what is already on origin/main" 0 "$rc" "SHIPPED"

echo
printf '=== %s passed, %s failed ===\n\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
