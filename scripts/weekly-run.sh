#!/usr/bin/env bash
# Weekly price run for this PC (ruling weekly-price-run-on-this-pc-commits-history-csv).
#
# Pulls main, runs the deal finder, commits ONLY data/history.csv, pushes to main
# (never forced) and shows a Windows notification. Everything is logged to
# out/last-run.log. Exit status: 0 OK, 2 the finder reported source errors (history was
# still committed), 1 anything else (nothing is committed on a crash or a refusal).
#
# Overrides, used by tests/test_weekly_run.py:
#   WEEKLY_REPO     repository to work in (default: the repo holding this script)
#   DEALFINDER_CMD  finder command (default: python3 -m dealfinder)
#   NOTIFY_CMD      one executable called as: NOTIFY_CMD <status> <title>
#                   (default: scripts/notify.ps1 through powershell.exe)
set -u
export GIT_TERMINAL_PROMPT=0   # never wait for a credential prompt in a scheduled run

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="${WEEKLY_REPO:-$(dirname "$SCRIPT_DIR")}"
DEALFINDER_CMD="${DEALFINDER_CMD:-python3 -m dealfinder}"
BRANCH=main
HISTORY=data/history.csv

cd "$REPO" || { echo "weekly-run: cannot cd to $REPO" >&2; exit 1; }
mkdir -p out
LOG="$REPO/out/last-run.log"
: > "$LOG"

log() {
    printf '%s\n' "$*" >> "$LOG"
    printf '%s\n' "$*" >&2
}

notify() {
    local status="$1" title="$2"
    if [ -n "${NOTIFY_CMD:-}" ]; then
        "$NOTIFY_CMD" "$status" "$title" >> "$LOG" 2>&1
    else
        powershell.exe -NoProfile -ExecutionPolicy Bypass \
            -File "$(wslpath -w "$SCRIPT_DIR/notify.ps1")" \
            -Message "$status" -Title "$title" >> "$LOG" 2>&1
    fi || log "weekly-run: notifier failed (see above)"
}

# finish <exit code> <status text> <notification title>
finish() {
    log "weekly-run: $2"
    notify "$2" "$3"
    exit "$1"
}

fail() {
    finish 1 "failed: $1" "Pepsi prices run failed"
}

log "weekly-run: $(date '+%F %T') in $REPO"

# A dirty tracked tree is never committed over, and blocks the checkout and pull anyway.
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    log "$(git status --short --untracked-files=no)"
    fail "tracked changes present before the run, nothing done"
fi

git checkout -q "$BRANCH" >> "$LOG" 2>&1 || fail "cannot check out $BRANCH"
git pull --ff-only origin "$BRANCH" >> "$LOG" 2>&1 || fail "git pull --ff-only failed"

read -r -a finder <<< "$DEALFINDER_CMD"
"${finder[@]}" >> "$LOG" 2>&1
rc=$?
case "$rc" in
    0|2) ;;
    *) fail "finder crashed (exit $rc), nothing committed" ;;
esac

offers_line="$(grep '^Offers kept:' "$LOG" | tail -n 1)"
errors_line="$(grep '^Source errors:' "$LOG" | tail -n 1)"
offers="$(printf '%s\n' "$offers_line" | grep -o ': [0-9]\+' | grep -o '[0-9]\+' \
    | awk '{ s += $1 } END { print s + 0 }')"
if [ "$rc" -eq 0 ]; then
    status="OK, $offers offers"
    title="Pepsi prices updated"
    code=0
else
    status="Source errors, $offers offers"
    title="Pepsi prices updated"
    code=2
fi

# Only data/history.csv may have changed.
others="$(git status --porcelain --untracked-files=no | grep -v -x " M $HISTORY" || true)"
if [ -n "$others" ]; then
    log "$others"
    fail "the finder left other tracked changes, nothing committed"
fi

if [ -z "$(git status --porcelain -- "$HISTORY")" ]; then
    log "weekly-run: $HISTORY unchanged, nothing to commit"
    finish "$code" "$status" "$title"
fi

git add -- "$HISTORY" >> "$LOG" 2>&1 || fail "git add failed"
if [ "$(git diff --cached --name-only)" != "$HISTORY" ]; then
    git reset -q >> "$LOG" 2>&1
    fail "staged files are not exactly $HISTORY, nothing committed"
fi

git commit -q -m "Weekly prices $(date +%F)" -m "$offers_line
$errors_line" >> "$LOG" 2>&1 || fail "git commit failed"

if ! git push origin "$BRANCH" >> "$LOG" 2>&1; then
    log "weekly-run: push rejected, pulling with rebase once"
    if ! git pull --rebase origin "$BRANCH" >> "$LOG" 2>&1; then
        git rebase --abort >> "$LOG" 2>&1
        fail "rebase failed, the commit stays local"
    fi
    git push origin "$BRANCH" >> "$LOG" 2>&1 || fail "push failed twice, the commit stays local"
fi

finish "$code" "$status" "$title"
