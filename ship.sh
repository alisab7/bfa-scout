#!/usr/bin/env bash
#
# ship.sh — one-command deploy for BFA-Scout.
#
#   ./ship.sh "commit message"        FULL:   commit -> push -> deploy -> verify
#   ./ship.sh push "commit message"   steps 1-3 only (commit + push + verify push)
#   ./ship.sh deploy                  steps 4-6 only (deploy what is on origin/main)
#   ./ship.sh status                  read-only dry run; changes nothing
#   -y / --yes anywhere               skip confirmation prompts
#
# WHY THIS EXISTS
#   The old flow was: git push, ssh in, `sudo -u bfa git pull`, docker build,
#   docker up, eyeball /healthz, then *guess* whether the change went live.
#   That guess failed once: the droplet's checkout was already at the right
#   commit ("Already up to date"), but the running image had been built from
#   an EARLIER commit, so production was executing old code.
#
#   The fix is step 6: the image bakes in its own git SHA (Dockerfile ARG
#   GIT_SHA -> ENV -> /healthz "sha" field), and this script asserts that the
#   SHA reported by the LIVE endpoint equals the SHA it just pushed. That is
#   the only honest answer to "did my change actually go live?".
#
# EVERYTHING FAILS LOUD. Every stop condition prints why and exits non-zero.
#
# Written for bash 3.2 (macOS /bin/bash) — no associative arrays, no mapfile.
set -euo pipefail

# ── Configuration (override via environment) ──────────────────────────────────
SSH_KEY="${SHIP_SSH_KEY:-$HOME/.ssh/bfa_scout_new}"
SSH_HOST="${SHIP_SSH_HOST:-root@164.90.181.13}"
REMOTE_DIR="${SHIP_REMOTE_DIR:-/home/bfa/bfa-scout}"
REMOTE_GIT_USER="${SHIP_REMOTE_GIT_USER:-bfa}"
BRANCH="${SHIP_BRANCH:-main}"
GIT_REMOTE="${SHIP_GIT_REMOTE:-origin}"
COMPOSE_FILE="${SHIP_COMPOSE_FILE:-docker-compose.prod.yml}"
LEDGER="${SHIP_LEDGER:-$REMOTE_DIR/.deployed_migrations}"
HEALTH_URL="${SHIP_HEALTH_URL:-https://localhost/healthz}"
HEALTH_TRIES="${SHIP_HEALTH_TRIES:-8}"
HEALTH_SLEEP="${SHIP_HEALTH_SLEEP:-5}"

# Untracked/changed paths that must NEVER be auto-staged. A stray
# cowork_*_prompt.md has nearly been committed before.
JUNK_GLOBS='cowork_*_prompt.md exports/ .DS_Store'

# ── Output helpers ────────────────────────────────────────────────────────────
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    C_RESET=$'\033[0m'; C_BOLD=$'\033[1m'; C_DIM=$'\033[2m'
    C_RED=$'\033[31m'; C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_BLUE=$'\033[36m'
else
    C_RESET=''; C_BOLD=''; C_DIM=''; C_RED=''; C_GREEN=''; C_YELLOW=''; C_BLUE=''
fi

SHIP_TMPFILES=""
cleanup() { if [ -n "$SHIP_TMPFILES" ]; then rm -f $SHIP_TMPFILES 2>/dev/null || true; fi; }
trap cleanup EXIT

step() { printf '\n%s==> %s%s\n' "$C_BOLD$C_BLUE" "$*" "$C_RESET"; }
info() { printf '    %s\n' "$*"; }
dim()  { printf '    %s%s%s\n' "$C_DIM" "$*" "$C_RESET"; }
ok()   { printf '    %s* %s%s\n' "$C_GREEN" "$*" "$C_RESET"; }
warn() { printf '    %sWARN: %s%s\n' "$C_YELLOW" "$*" "$C_RESET" >&2; }
die()  { printf '\n%sSTOP: %s%s\n' "$C_BOLD$C_RED" "$*" "$C_RESET" >&2; exit "${SHIP_EXIT:-1}"; }

confirm() {
    # confirm "question"  -> returns 0 for yes, 1 for no. Honours -y.
    if [ "$ASSUME_YES" = "1" ]; then
        dim "(-y) $1 -> yes"
        return 0
    fi
    if [ ! -t 0 ]; then
        die "$1 — no TTY to ask on. Re-run with -y if you are sure."
    fi
    printf '%s%s [y/N] %s' "$C_BOLD" "$1" "$C_RESET"
    local reply=""
    read -r reply || true
    case "$reply" in [yY]|[yY][eE][sS]) return 0 ;; *) return 1 ;; esac
}

usage() {
    sed -n '3,10p' "$0" | sed 's/^# \{0,1\}//'
    exit "${1:-0}"
}

# ── Argument parsing ──────────────────────────────────────────────────────────
ASSUME_YES=0
MODE=""
MESSAGE=""
POSITIONAL=""      # newline-separated; bash 3.2-friendly

for arg in "$@"; do
    case "$arg" in
        -y|--yes)   ASSUME_YES=1 ;;
        -h|--help)  usage 0 ;;
        *)          POSITIONAL="$POSITIONAL$arg"$'\n' ;;
    esac
done

# First positional selects the mode; anything after it is the commit message.
first=""
rest=""
seen_first=0
while IFS= read -r line; do
    [ -z "$line" ] && continue
    if [ "$seen_first" = "0" ]; then first="$line"; seen_first=1; else rest="$rest$line "; fi
done <<EOF
$POSITIONAL
EOF

case "$first" in
    status)  MODE="status" ;;
    deploy)  MODE="deploy" ;;
    push)    MODE="push";   MESSAGE="$(printf '%s' "$rest" | sed 's/ *$//')" ;;
    full)    MODE="full";   MESSAGE="$(printf '%s' "$rest" | sed 's/ *$//')" ;;
    "")      usage 1 ;;
    *)       MODE="full";   MESSAGE="$first${rest:+ $(printf '%s' "$rest" | sed 's/ *$//')}" ;;
esac

case "$MODE" in
    push|full)
        [ -n "$MESSAGE" ] || die "mode '$MODE' needs a commit message: ./ship.sh $MODE \"your message\"" ;;
esac

# ── Repo root ─────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR" || die "cannot cd to script directory: $SCRIPT_DIR"
git rev-parse --git-dir >/dev/null 2>&1 || die "$SCRIPT_DIR is not a git repository"

# ── SSH plumbing ──────────────────────────────────────────────────────────────
ssh_exec() {
    # ssh_exec <<'EOS' ... EOS   — script on stdin, args after `--`.
    ssh -i "$SSH_KEY" \
        -o BatchMode=yes -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new \
        "$SSH_HOST" "$@"
}

# ── Local helpers ─────────────────────────────────────────────────────────────
is_junk() {
    # NOTE: `set -f` is essential — without it, `for g in $JUNK_GLOBS` would
    # pathname-expand `cowork_*_prompt.md` against the repo root (which is
    # full of them) and compare paths against filenames instead of patterns.
    local path="$1" g rc=1
    set -f
    for g in $JUNK_GLOBS; do
        case "$path" in
            $g|$g*|*/$g) rc=0; break ;;
        esac
    done
    set +f
    return "$rc"
}

# Prints changed/untracked paths, one per line, junk removed.
dirty_paths() {
    git status --porcelain 2>/dev/null | while IFS= read -r line; do
        [ -n "$line" ] || continue
        local p="${line:3}"
        case "$p" in *' -> '*) p="${p##* -> }" ;; esac
        p="${p%\"}"; p="${p#\"}"
        if is_junk "$p"; then continue; fi
        printf '%s\n' "$p"
    done
}

junk_paths() {
    git status --porcelain 2>/dev/null | while IFS= read -r line; do
        [ -n "$line" ] || continue
        local p="${line:3}"
        case "$p" in *' -> '*) p="${p##* -> }" ;; esac
        p="${p%\"}"; p="${p#\"}"
        if is_junk "$p"; then printf '%s\n' "$p"; fi
    done
}

count_lines() { if [ -z "$1" ]; then echo 0; else printf '%s\n' "$1" | grep -c . || true; fi; }

remote_head_sha() { git ls-remote "$GIT_REMOTE" "refs/heads/$BRANCH" 2>/dev/null | awk '{print $1}' | head -1; }

local_migration_names() { ls -1 migrations/*.sql 2>/dev/null | while IFS= read -r f; do basename "$f"; done; }

# ══════════════════════════════════════════════════════════════════════════════
# STEP 1-3 — local: preflight, commit, push, verify push landed
# ══════════════════════════════════════════════════════════════════════════════
preflight_and_push() {
    step "[1/6] Pre-flight (local)"

    local cur_branch
    cur_branch="$(git rev-parse --abbrev-ref HEAD)"
    [ "$cur_branch" = "$BRANCH" ] || die "on branch '$cur_branch', expected '$BRANCH'. Refusing to ship from a side branch."
    ok "branch: $cur_branch"

    local junk dirty n_dirty
    junk="$(junk_paths || true)"
    dirty="$(dirty_paths || true)"
    n_dirty="$(count_lines "$dirty")"

    if [ -n "$junk" ]; then
        info "ignored (known junk, never staged):"
        printf '%s\n' "$junk" | sed "s/^/      ${C_DIM}-  /;s/$/${C_RESET}/"
    fi

    if [ "$n_dirty" -gt 0 ]; then
        info "$n_dirty changed/untracked file(s):"
        printf '%s\n' "$dirty" | while IFS= read -r p; do
            [ -n "$p" ] || continue
            printf '      %s %s\n' "$(git status --porcelain -- "$p" | cut -c1-2)" "$p"
        done

        local choice="a"
        if [ "$ASSUME_YES" = "1" ]; then
            dim "(-y) staging all $n_dirty listed file(s)"
        else
            if [ ! -t 0 ]; then die "files need staging but there is no TTY to ask on. Re-run with -y."; fi
            printf '%sStage: [a]ll listed / [s]elect one by one / [n] abort? %s' "$C_BOLD" "$C_RESET"
            read -r choice || true
        fi

        case "$choice" in
            n|N|"") die "aborted before staging anything. Nothing was changed." ;;
            s|S)
                local staged_any=0
                local p
                while IFS= read -r p; do
                    [ -n "$p" ] || continue
                    printf '  stage %s? [y/N] ' "$p"
                    local r=""; read -r r </dev/tty || true
                    case "$r" in [yY]*) git add -- "$p"; staged_any=1 ;; *) dim "skipped $p" ;; esac
                done <<EOF
$dirty
EOF
                [ "$staged_any" = "1" ] || dim "nothing selected"
                ;;
            *)
                local p
                while IFS= read -r p; do
                    [ -n "$p" ] || continue
                    git add -- "$p"
                done <<EOF
$dirty
EOF
                ;;
        esac
    else
        info "working tree clean (ignoring known junk)"
    fi

    step "[2/6] Commit and push"

    local have_staged=0
    git diff --cached --quiet || have_staged=1

    local remote_sha ahead
    remote_sha="$(remote_head_sha)"
    ahead=0
    if [ -n "$remote_sha" ] && git cat-file -e "$remote_sha^{commit}" 2>/dev/null; then
        ahead="$(git rev-list --count "$remote_sha..HEAD" 2>/dev/null || echo 0)"
    fi

    if [ "$have_staged" = "0" ] && [ "$ahead" = "0" ]; then
        printf '\n%sNothing to ship:%s no staged changes and nothing unpushed.\n' "$C_YELLOW" "$C_RESET"
        info "If you want to redeploy what is already on $GIT_REMOTE/$BRANCH: ./ship.sh deploy"
        exit 0
    fi

    if [ "$have_staged" = "1" ]; then
        info "staged for commit:"
        git diff --cached --name-status | sed 's/^/      /'
        info "message: $MESSAGE"
        confirm "Commit these changes?" || die "aborted before committing. Files are staged but uncommitted."
        git commit -m "$MESSAGE"
        ok "committed"
    else
        info "nothing staged; $ahead local commit(s) not yet on $GIT_REMOTE/$BRANCH"
    fi

    info "pushing to $GIT_REMOTE/$BRANCH"
    git push "$GIT_REMOTE" "$BRANCH" || die "git push failed — nothing was deployed."

    step "[3/6] Verify the push landed"
    PUSHED_SHA="$(git rev-parse HEAD)"
    local remote_now
    remote_now="$(remote_head_sha)"
    [ -n "$remote_now" ] || die "could not read $GIT_REMOTE/$BRANCH via git ls-remote."
    if [ "$remote_now" != "$PUSHED_SHA" ]; then
        die "push did not land.
       local  HEAD:            $PUSHED_SHA
       $GIT_REMOTE/$BRANCH on remote: $remote_now
       Deploying now would ship the WRONG commit."
    fi
    ok "$GIT_REMOTE/$BRANCH == local HEAD == $(printf '%s' "$PUSHED_SHA" | cut -c1-7)"
}

# ══════════════════════════════════════════════════════════════════════════════
# STEP 4-6 — one non-interactive SSH call, then assert the live SHA
# ══════════════════════════════════════════════════════════════════════════════
deploy_remote() {
    local sha="$1"
    local short
    short="$(printf '%s' "$sha" | cut -c1-7)"

    step "[4/6] Deploy on the droplet ($SSH_HOST)"
    info "target commit: $short"
    confirm "Backup, pull, migrate, build and restart PRODUCTION at $sha?" \
        || die "deploy aborted by you. The droplet was not touched."

    local out
    out="$(mktemp -t ship_deploy)" || die "cannot create temp file"
    SHIP_TMPFILES="$SHIP_TMPFILES $out"

    # ONE ssh call. The whole server-side procedure is on stdin, values as args.
    if ! ssh_exec "bash -s -- '$sha' '$REMOTE_DIR' '$REMOTE_GIT_USER' '$COMPOSE_FILE' '$LEDGER' '$HEALTH_URL' '$HEALTH_TRIES' '$HEALTH_SLEEP' '$BRANCH'" <<'REMOTE_DEPLOY' | tee "$out"
set -euo pipefail
PUSHED_SHA="$1"; REPO_DIR="$2"; GIT_USER="$3"; COMPOSE_FILE="$4"
LEDGER="$5"; HEALTH_URL="$6"; TRIES="$7"; SLEEP_S="$8"; BRANCH="$9"

SHORT="$(printf '%s' "$PUSHED_SHA" | cut -c1-7)"
COMPOSE="docker compose -f $COMPOSE_FILE"

cd "$REPO_DIR" || { echo "FATAL: no repo at $REPO_DIR"; exit 30; }

# ---------------------------------------------------------------- a. BACKUP
echo "--- [a] Backup to Spaces (must succeed before anything else) ---"
[ -f scripts/backup_to_spaces.sh ] || { echo "FATAL: scripts/backup_to_spaces.sh missing"; exit 20; }
if ! BFA_SCOUT_DIR="$REPO_DIR" bash scripts/backup_to_spaces.sh </dev/null; then
    echo "FATAL: backup failed — refusing to deploy without a fresh backup."
    exit 21
fi
echo "SHIP_BACKUP=ok"

# Snapshot the migrations that exist BEFORE the pull. If the ledger does not
# exist yet, these are exactly the ones production has already had applied,
# and they become the baseline — so a first run never re-applies history,
# while anything the pull brings in IS applied.
PRE_PULL_MIGRATIONS="$(ls -1 migrations/*.sql 2>/dev/null || true)"

# ------------------------------------------------------------------ b. PULL
echo "--- [b] git pull (as $GIT_USER) ---"
if ! PULL_OUT="$(sudo -u "$GIT_USER" git pull origin "$BRANCH" 2>&1)"; then
    echo "$PULL_OUT"
    echo "FATAL: git pull failed on the droplet."
    exit 22
fi
echo "$PULL_OUT"
DROPLET_SHA="$(sudo -u "$GIT_USER" git rev-parse HEAD)"
echo "SHIP_DROPLET_SHA=$DROPLET_SHA"
if [ "$DROPLET_SHA" != "$PUSHED_SHA" ]; then
    echo "FATAL: droplet checkout is $DROPLET_SHA but you pushed $PUSHED_SHA."
    case "$PULL_OUT" in
        *"Already up to date"*|*"Already up-to-date"*)
            echo "       git reported 'Already up to date' — the push did NOT land on $BRANCH." ;;
    esac
    echo "       Nothing was built or restarted."
    exit 23
fi
echo "  droplet checkout matches the pushed commit"

# ------------------------------------------------------------ c. MIGRATIONS
echo "--- [c] Migrations (ledger: $LEDGER) ---"
set -a; . "$REPO_DIR/.env.production"; set +a
[ -n "${DATABASE_URL:-}" ] || { echo "FATAL: DATABASE_URL not set from .env.production"; exit 27; }

if [ ! -f "$LEDGER" ]; then
    echo "  no ledger yet — seeding a BASELINE from the pre-pull checkout."
    echo "  (assumption: everything already in the droplet checkout before this"
    echo "   pull has already been applied to production.)"
    for f in $PRE_PULL_MIGRATIONS; do
        printf 'baseline  %s\n' "$(basename "$f")"
    done | sudo -u "$GIT_USER" tee "$LEDGER" >/dev/null
    awk '{print "    baselined: " $2}' "$LEDGER"
fi

MIGRATIONS_APPLIED=0
for f in migrations/*.sql; do
    [ -e "$f" ] || continue
    b="$(basename "$f")"
    h="$(sha256sum "$f" | awk '{print $1}')"
    recorded="$(awk -v n="$b" '$2 == n { print $1 }' "$LEDGER" | tail -1)"
    if [ -n "$recorded" ]; then
        if [ "$recorded" != "baseline" ] && [ "$recorded" != "$h" ]; then
            echo "  WARN: $b was applied earlier but its contents have changed."
            echo "        NOT re-applying (that could be destructive). Add a new"
            echo "        migration file instead if the change must reach prod."
        fi
        continue
    fi
    echo "  applying $b"
    if ! PAGER=cat psql "$DATABASE_URL" -X -v ON_ERROR_STOP=1 -P pager=off -f "$f" </dev/null; then
        echo "FATAL: migration $b FAILED."
        echo "       The database may be half-migrated. NOT building, NOT restarting."
        echo "       Fix the migration, then re-run ./ship.sh deploy."
        exit 24
    fi
    printf '%s  %s\n' "$h" "$b" | sudo -u "$GIT_USER" tee -a "$LEDGER" >/dev/null
    MIGRATIONS_APPLIED=$((MIGRATIONS_APPLIED + 1))
    echo "SHIP_MIGRATION_APPLIED=$b"
done
echo "SHIP_MIGRATIONS_APPLIED_COUNT=$MIGRATIONS_APPLIED"
if [ "$MIGRATIONS_APPLIED" -eq 0 ]; then echo "  no new migrations"; fi

# ------------------------------------------------------- d. BUILD + RECREATE
echo "--- [d] Build + recreate app (GIT_SHA=$SHORT) ---"
export GIT_SHA="$DROPLET_SHA"
$COMPOSE build app || { echo "FATAL: docker build failed."; exit 28; }
$COMPOSE up -d --force-recreate app || { echo "FATAL: docker compose up failed."; exit 29; }

# nginx proxy_passes to the literal host `app` and caches that resolution.
# A force-recreate can hand the app container a new IP, so nudge nginx to
# re-resolve. Best effort: the health drain below goes through nginx and
# would catch a stale upstream anyway.
$COMPOSE exec -T nginx nginx -s reload >/dev/null 2>&1 \
    && echo "  nginx reloaded (upstream re-resolved)" \
    || echo "  WARN: nginx reload skipped/failed — health drain will catch a stale upstream"

# ---------------------------------------------------------- e. HEALTH DRAIN
echo "--- [e] Draining /healthz (max $TRIES tries) ---"
BODY=""
HEALTHY=0
i=0
while [ "$i" -lt "$TRIES" ]; do
    i=$((i + 1))
    BODY="$(curl -fsS -k --max-time 10 "$HEALTH_URL" 2>/dev/null || true)"
    case "$BODY" in
        *'"status"'*'"ok"'*) HEALTHY=1; break ;;
    esac
    echo "  attempt $i/$TRIES: not healthy yet"
    sleep "$SLEEP_S"
done

if [ "$HEALTHY" != "1" ]; then
    echo "FATAL: /healthz never returned status=ok after $TRIES tries."
    echo "--- last 50 lines of app logs ---"
    $COMPOSE logs --tail=50 app 2>&1 || true
    exit 25
fi
echo "SHIP_HEALTH_BODY=$BODY"

# ------------------------------------------------------- f. SHA VERIFICATION
# The drain above breaks as soon as SOMETHING answers status=ok — and during
# a force-recreate that something can still be the OLD container. So the SHA
# is polled in its own loop rather than read from that first response: a
# correct deploy simply needs a few more seconds for the new container to
# come up behind nginx. Only a SHA that is still absent or wrong after every
# retry is a real failure.
echo "--- [f] Verifying live SHA (max $TRIES tries) ---"
LIVE_SHA=""
SHA_OK=0
i=0
while [ "$i" -lt "$TRIES" ]; do
    i=$((i + 1))
    SHA_BODY="$(curl -fsS -k --max-time 10 "$HEALTH_URL" 2>/dev/null || true)"
    LIVE_SHA="$(printf '%s' "$SHA_BODY" | sed -n 's/.*"sha"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)"
    if [ -n "$SHA_BODY" ]; then BODY="$SHA_BODY"; fi
    if [ -n "$LIVE_SHA" ] && [ "$LIVE_SHA" = "$SHORT" ]; then
        SHA_OK=1
        break
    fi
    echo "  attempt $i/$TRIES: live sha='${LIVE_SHA:-<absent>}' (want $SHORT) — still settling"
    sleep "$SLEEP_S"
done

echo "SHIP_LIVE_SHA=$LIVE_SHA"
if [ "$SHA_OK" != "1" ]; then
    if [ -z "$LIVE_SHA" ] || [ "$LIVE_SHA" = "unknown" ]; then
        echo "FATAL: /healthz still reported sha='${LIVE_SHA:-<absent>}' after $TRIES tries."
        echo "       The image was built without the GIT_SHA build arg, so the deploy"
        echo "       CANNOT be verified. Treat production as unverified."
    else
        echo "FATAL: live SHA mismatch after $TRIES tries — the deploy did NOT take."
        echo "       expected (just pushed): $SHORT"
        echo "       live /healthz reports:  $LIVE_SHA"
        echo "       Likely a cached build, a stale image, or the wrong branch."
    fi
    echo "--- last 50 lines of app logs ---"
    $COMPOSE logs --tail=50 app 2>&1 || true
    exit 26
fi
echo "  live /healthz sha = $LIVE_SHA  == pushed $SHORT (after $i attempt(s))"
echo "SHIP_DEPLOY=ok"
REMOTE_DEPLOY
    then
        rm -f "$out"
        die "the droplet deploy FAILED (see the server output above). Production may be unchanged or partially updated — read the FATAL line."
    fi

    step "[5/6] SHA verification (local re-assert)"
    local live
    live="$( { grep '^SHIP_LIVE_SHA=' "$out" || true; } | tail -1 | cut -d= -f2- | tr -d '\r')"
    MIGRATIONS_APPLIED_LIST="$( { grep '^SHIP_MIGRATION_APPLIED=' "$out" || true; } | cut -d= -f2- | tr -d '\r')"
    rm -f "$out"

    [ -n "$live" ] || die "the droplet never reported a live SHA. Deploy unverified."
    if [ "$live" != "$short" ]; then
        die "live SHA does not match what you pushed.
       pushed: $short
       live:   $live
       Your change is NOT running in production."
    fi
    ok "live /healthz sha = $live == pushed $short"

    step "[6/6] Summary"
    printf '    %scommit%s         %s\n' "$C_BOLD" "$C_RESET" "$sha"
    if [ -n "$MIGRATIONS_APPLIED_LIST" ]; then
        printf '    %smigrations%s     applied:\n' "$C_BOLD" "$C_RESET"
        printf '%s\n' "$MIGRATIONS_APPLIED_LIST" | sed 's/^/                     /'
    else
        printf '    %smigrations%s     none pending\n' "$C_BOLD" "$C_RESET"
    fi
    printf '    %slive SHA%s       %s (matches)\n' "$C_BOLD" "$C_RESET" "$live"
    printf '    %shealthz%s        ok\n' "$C_BOLD" "$C_RESET"
    printf '\n%s  SHIPPED — %s is live and verified.%s\n\n' "$C_GREEN$C_BOLD" "$short" "$C_RESET"
}

# ══════════════════════════════════════════════════════════════════════════════
# status — read-only. Touches nothing, locally or on the droplet.
# ══════════════════════════════════════════════════════════════════════════════
do_status() {
    step "status — read-only dry run (nothing will be changed)"

    local cur_branch local_head local_short
    cur_branch="$(git rev-parse --abbrev-ref HEAD)"
    local_head="$(git rev-parse HEAD)"
    local_short="$(printf '%s' "$local_head" | cut -c1-7)"

    step "Local"
    if [ "$cur_branch" = "$BRANCH" ]; then ok "branch: $cur_branch"; else warn "branch: $cur_branch (expected $BRANCH — ship.sh would refuse)"; fi
    info "HEAD: $local_short"

    local junk dirty n_dirty
    junk="$(junk_paths || true)"
    dirty="$(dirty_paths || true)"
    n_dirty="$(count_lines "$dirty")"

    if [ "$n_dirty" -eq 0 ]; then
        ok "nothing to commit"
    else
        warn "$n_dirty uncommitted/untracked file(s):"
        printf '%s\n' "$dirty" | while IFS= read -r p; do
            [ -n "$p" ] || continue
            printf '      %s %s\n' "$(git status --porcelain -- "$p" | cut -c1-2)" "$p"
        done
    fi
    if [ -n "$junk" ]; then
        info "ignored as junk (never staged by ship.sh):"
        printf '%s\n' "$junk" | sed 's/^/      -  /'
    fi

    local remote_sha ahead
    remote_sha="$(remote_head_sha)"
    if [ -z "$remote_sha" ]; then
        warn "could not reach $GIT_REMOTE to read $BRANCH"
    elif [ "$remote_sha" = "$local_head" ]; then
        ok "$GIT_REMOTE/$BRANCH == local HEAD (nothing unpushed)"
    elif git cat-file -e "$remote_sha^{commit}" 2>/dev/null; then
        ahead="$(git rev-list --count "$remote_sha..HEAD" 2>/dev/null || echo '?')"
        warn "$ahead local commit(s) not pushed to $GIT_REMOTE/$BRANCH"
        git log --oneline "$remote_sha..HEAD" 2>/dev/null | sed 's/^/      /' || true
    else
        warn "$GIT_REMOTE/$BRANCH is at $(printf '%s' "$remote_sha" | cut -c1-7), which this checkout does not have — fetch first"
    fi

    step "Droplet ($SSH_HOST) — read-only"
    local out
    out="$(mktemp -t ship_status)" || die "cannot create temp file"
    SHIP_TMPFILES="$SHIP_TMPFILES $out"
    if ! ssh_exec "bash -s -- '$REMOTE_DIR' '$REMOTE_GIT_USER' '$LEDGER' '$HEALTH_URL' '$COMPOSE_FILE'" >"$out" 2>&1 <<'REMOTE_STATUS'
set -uo pipefail
REPO_DIR="$1"; GIT_USER="$2"; LEDGER="$3"; HEALTH_URL="$4"; COMPOSE_FILE="$5"
cd "$REPO_DIR" 2>/dev/null || { echo "SHIP_ERR=no repo at $REPO_DIR"; exit 1; }
echo "SHIP_DROPLET_SHA=$(sudo -u "$GIT_USER" git rev-parse HEAD 2>/dev/null || echo unknown)"
echo "SHIP_DROPLET_BRANCH=$(sudo -u "$GIT_USER" git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
if [ -f "$LEDGER" ]; then
    echo "SHIP_LEDGER_PRESENT=yes"
    awk '{print "SHIP_LEDGER_ENTRY=" $2}' "$LEDGER"
else
    echo "SHIP_LEDGER_PRESENT=no"
fi
BODY="$(curl -fsS -k --max-time 10 "$HEALTH_URL" 2>/dev/null || true)"
echo "SHIP_HEALTH_BODY=$BODY"
echo "SHIP_LIVE_SHA=$(printf '%s' "$BODY" | sed -n 's/.*"sha"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)"
docker compose -f "$COMPOSE_FILE" ps --format '{{.Name}} {{.Status}}' 2>/dev/null \
    | sed 's/^/SHIP_CONTAINER=/' || true
REMOTE_STATUS
    then
        warn "could not read droplet state over SSH:"
        sed 's/^/      /' "$out" >&2
        rm -f "$out"
        return 0
    fi

    local d_sha d_branch ledger_present live body
    d_sha="$({ grep '^SHIP_DROPLET_SHA=' "$out" || true; } | tail -1 | cut -d= -f2- | tr -d '\r')"
    d_branch="$({ grep '^SHIP_DROPLET_BRANCH=' "$out" || true; } | tail -1 | cut -d= -f2- | tr -d '\r')"
    ledger_present="$({ grep '^SHIP_LEDGER_PRESENT=' "$out" || true; } | tail -1 | cut -d= -f2- | tr -d '\r')"
    body="$({ grep '^SHIP_HEALTH_BODY=' "$out" || true; } | tail -1 | cut -d= -f2- | tr -d '\r')"
    live="$({ grep '^SHIP_LIVE_SHA=' "$out" || true; } | tail -1 | cut -d= -f2- | tr -d '\r')"

    info "checkout: ${d_sha:0:7} on ${d_branch:-?}"
    { grep '^SHIP_CONTAINER=' "$out" || true; } | cut -d= -f2- | sed 's/^/      /' 

    # ── migrations that WOULD run ────────────────────────────────────────────
    local ledger_names pending n_pending
    ledger_names="$( { grep '^SHIP_LEDGER_ENTRY=' "$out" || true; } | cut -d= -f2- | tr -d '\r')"
    if [ "$ledger_present" != "yes" ]; then
        warn "no migration ledger on the droplet yet ($LEDGER)"
        info "the first ./ship.sh deploy will BASELINE the $(local_migration_names | wc -l | tr -d ' ') migration(s)"
        info "already in the droplet checkout (applied none), then apply only new ones."
    else
        pending=""
        local m
        while IFS= read -r m; do
            [ -n "$m" ] || continue
            if ! printf '%s\n' "$ledger_names" | grep -qx "$m"; then
                pending="$pending$m"$'\n'
            fi
        done <<EOF
$(local_migration_names)
EOF
        n_pending="$(count_lines "$pending")"
        if [ "$n_pending" -eq 0 ]; then
            ok "no pending migrations ($(count_lines "$ledger_names") in ledger)"
        else
            warn "$n_pending migration(s) WOULD run on the next deploy:"
            printf '%s\n' "$pending" | sed '/^$/d;s/^/      -  /'
        fi
    fi

    # ── live SHA vs local HEAD ───────────────────────────────────────────────
    if [ -z "$body" ]; then
        warn "/healthz unreachable from the droplet ($HEALTH_URL)"
    else
        info "healthz: $body"
        if [ -z "$live" ] || [ "$live" = "unknown" ]; then
            warn "live image reports sha='${live:-<absent>}' — it predates the GIT_SHA build arg."
            info "the next ./ship.sh deploy will bake it in and make this verifiable."
        elif [ "$live" = "$local_short" ]; then
            ok "live SHA $live == local HEAD $local_short"
        else
            warn "live SHA $live != local HEAD $local_short — production is running different code"
        fi
    fi

    rm -f "$out"
    printf '\n%s  status complete — nothing was changed.%s\n\n' "$C_DIM" "$C_RESET"
}

# ══════════════════════════════════════════════════════════════════════════════
main() {
    case "$MODE" in
        status)
            do_status
            ;;
        push)
            preflight_and_push
            printf '\n%s  Pushed %s. Deploy it with: ./ship.sh deploy%s\n\n' \
                "$C_GREEN$C_BOLD" "$(printf '%s' "$PUSHED_SHA" | cut -c1-7)" "$C_RESET"
            ;;
        deploy)
            step "[1-3/6] Skipped (deploy mode) — deploying what is on $GIT_REMOTE/$BRANCH"
            local target
            target="$(remote_head_sha)"
            [ -n "$target" ] || die "could not read $GIT_REMOTE/$BRANCH via git ls-remote."
            local head_sha
            head_sha="$(git rev-parse HEAD)"
            if [ "$target" != "$head_sha" ]; then
                warn "$GIT_REMOTE/$BRANCH ($(printf '%s' "$target" | cut -c1-7)) differs from your local HEAD ($(printf '%s' "$head_sha" | cut -c1-7))."
                warn "ship.sh will deploy what is on the REMOTE, not your local tree."
                confirm "Deploy $(printf '%s' "$target" | cut -c1-7) from $GIT_REMOTE/$BRANCH anyway?" \
                    || die "aborted. Nothing was touched."
            fi
            deploy_remote "$target"
            ;;
        full)
            preflight_and_push
            deploy_remote "$PUSHED_SHA"
            ;;
        *)
            usage 1
            ;;
    esac
}

PUSHED_SHA=""
MIGRATIONS_APPLIED_LIST=""
main
