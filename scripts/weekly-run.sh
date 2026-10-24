#!/usr/bin/env bash
# Weekly price run for this PC (ruling weekly-price-run-on-this-pc-commits-history-csv).
#
# Pulls main, runs the deal finder, commits ONLY data/history.csv, pushes to main
# (never forced) and shows a Windows notification. Everything is logged to
# out/last-run.log. Exit status: 0 OK, 2 the finder reported source errors (history was
# still committed), 1 anything else (nothing is committed on a crash or a refusal).
#
# Safety rules: local main must equal origin/main before the run (a commit left local by
# an earlier failed push is reported, never stacked on), and the outgoing range
# origin/main..HEAD must be exactly one commit that changes only data/history.csv.
# Every failure, including a failed start-up, ends in a notification.
#
# Overrides, used by tests/test_weekly_run.py:
#   WEEKLY_REPO     repository to work in (default: the repo holding this script)
#   DEALFINDER_CMD  finder command (default: python3 -m dealfinder)
#   NOTIFY_CMD      one executable called as: NOTIFY_CMD <status> <title>
#                   (default: scripts/notify.ps1 through powershell.exe)
set -u
export GIT_TERMINAL_PROMPT=0   # never wait for a credential prompt in a scheduled run

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"
REPO="${WEEKLY_REPO:-$(dirname "$SCRIPT_DIR")}"
DEALFINDER_CMD="${DEALFINDER_CMD:-python3 -m dealfinder}"
BRANCH=main
ORIGIN_REF="refs/remotes/origin/$BRANCH"
HISTORY=data/history.csv
LOG="$REPO/out/last-run.log"
FINDER_OUT="$LOG.finder"
LOG_OK=0   # set once the log file is open; until then messages go to stderr only

log() {
    printf '%s\n' "$*" >&2
    if [ "$LOG_OK" = 1 ]; then
        printf '%s\n' "$*" >> "$LOG" 2>/dev/null
    fi
}

run_notifier() {
    if [ -n "${NOTIFY_CMD:-}" ]; then
        "$NOTIFY_CMD" "$1" "$2"
    else
        powershell.exe -NoProfile -ExecutionPolicy Bypass \
            -File "$(wslpath -w "$SCRIPT_DIR/notify.ps1")" \
            -Status "$1" -Title "$2"
    fi
}

# The notifier runs even when the log cannot be opened: its output then goes to stderr.
notify() {
    if [ "$LOG_OK" = 1 ] && { : >> "$LOG"; } 2>/dev/null; then
        run_notifier "$1" "$2" >> "$LOG" 2>&1
    else
        run_notifier "$1" "$2" >&2
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

cd "$REPO" 2>/dev/null || fail "cannot cd to $REPO"
{ mkdir -p out && : > "$LOG"; } 2>/dev/null || fail "cannot open the log $LOG"
LOG_OK=1

rebase_in_progress() {
    [ -d "$(git rev-parse --git-path rebase-merge)" ] || [ -d "$(git rev-parse --git-path rebase-apply)" ]
}

# Exactly one commit may leave this machine, and it may change only data/history.csv.
check_outgoing() {
    local count files
    count="$(git rev-list --count "$ORIGIN_REF..HEAD")" || return 1
    files="$(git diff --name-only "$ORIGIN_REF..HEAD")" || return 1
    [ "$count" = 1 ] && [ "$files" = "$HISTORY" ]
}

# Needs exactly one valid 'Offers kept:' line and one 'Source errors:' line; sets
# offers_line, errors_line and offers (the sum of the per-product counts).
parse_finder_output() {
    local n_offers n_errors
    n_offers="$(grep -c '^Offers kept:' "$FINDER_OUT" || true)"
    n_errors="$(grep -c '^Source errors:' "$FINDER_OUT" || true)"
    [ "$n_offers" = 1 ] && [ "$n_errors" = 1 ] || return 1
    offers_line="$(grep '^Offers kept:' "$FINDER_OUT")"
    errors_line="$(grep '^Source errors:' "$FINDER_OUT")"
    printf '%s\n' "$offers_line" \
        | grep -Eq '^Offers kept: [^:,]+: [0-9]+(, [^:,]+: [0-9]+)*$' || return 1
    printf '%s\n' "$errors_line" | grep -Eq '^Source errors: .+$' || return 1
    offers="$(printf '%s\n' "$offers_line" | grep -Eo ': [0-9]+' | grep -Eo '[0-9]+' \
        | awk '{ s += $1 } END { print s + 0 }')"
}

log "weekly-run: $(date '+%F %T') in $REPO"

# A dirty tracked tree is never committed over, and blocks the checkout and pull anyway.
dirty="$(git status --porcelain --untracked-files=no 2>/dev/null)" \
    || fail "git status failed (is $REPO a git repository?)"
if [ -n "$dirty" ]; then
    log "$dirty"
    fail "tracked changes present before the run, nothing done"
fi

git checkout -q "$BRANCH" >> "$LOG" 2>&1 || fail "cannot check out $BRANCH"
git fetch origin "+refs/heads/$BRANCH:$ORIGIN_REF" >> "$LOG" 2>&1 || fail "git fetch failed"
git pull --ff-only origin "$BRANCH" >> "$LOG" 2>&1 || fail "git pull --ff-only failed"
if [ "$(git rev-parse HEAD)" != "$(git rev-parse "$ORIGIN_REF")" ]; then
    log "$(git log --oneline "$ORIGIN_REF..HEAD")"
    fail "local $BRANCH is ahead of origin/$BRANCH (an earlier commit was never pushed?), nothing done"
fi

read -r -a finder <<< "$DEALFINDER_CMD"
"${finder[@]}" > "$FINDER_OUT" 2>&1
rc=$?
cat "$FINDER_OUT" >> "$LOG"
case "$rc" in
    0|2) ;;
    *) fail "finder crashed (exit $rc), nothing committed" ;;
esac

parse_finder_output \
    || fail "finder output lacks exactly one valid 'Offers kept:' and 'Source errors:' line, nothing committed"
if [ "$rc" -eq 0 ]; then
    status="OK, $offers offers"
    code=0
else
    status="Source errors, $offers offers"
    code=2
fi
title="Pepsi prices updated"

# Only data/history.csv may have changed.
others="$(git status --porcelain --untracked-files=no 2>/dev/null | grep -v -x " M $HISTORY" || true)"
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

check_outgoing || fail "outgoing range is not exactly one commit changing only $HISTORY, not pushing"
if ! git push origin "$BRANCH" >> "$LOG" 2>&1; then
    log "weekly-run: push rejected, pulling with rebase once"
    if ! git pull --rebase origin "$BRANCH" >> "$LOG" 2>&1; then
        if rebase_in_progress && ! git rebase --abort >> "$LOG" 2>&1; then
            notify "Manual recovery needed: git rebase --abort failed in $REPO" \
                "Pepsi prices needs attention"
            fail "rebase failed and could not be aborted, manual recovery needed"
        fi
        fail "rebase failed, the commit stays local"
    fi
    git fetch origin "+refs/heads/$BRANCH:$ORIGIN_REF" >> "$LOG" 2>&1 || fail "git fetch failed"
    check_outgoing || fail "after the rebase the outgoing range is not exactly one commit changing only $HISTORY, not pushing"
    git push origin "$BRANCH" >> "$LOG" 2>&1 || fail "push failed twice, the commit stays local"
fi

finish "$code" "$status" "$title"
