#!/usr/bin/env bash
# Weekly price run for this PC (ruling weekly-price-run-on-this-pc-commits-history-csv).
#
# Pulls main, runs the deal finder, commits ONLY data/history.csv, REPORT.md and data/last_success.txt (rulings
# weekly-price-run-on-this-pc-commits-history-csv and phone-report-md-committed-to-public-repo),
# pushes to main (never forced) and shows a Windows notification. Everything is logged to
# out/last-run.log. Exit status: 0 OK, 2 the finder reported source errors (history was
# still committed), 1 anything else (nothing is committed on a crash or a refusal).
#
# Safety rules: local main must equal origin/main before the run (a commit left local by
# an earlier failed push is reported, never stacked on), and the outgoing range
# origin/main..HEAD must be exactly one commit that changes only data/history.csv,
# REPORT.md and data/last_success.txt.
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
REPORT=REPORT.md
LAST_SUCCESS=data/last_success.txt
FILES_TEXT="$HISTORY, $REPORT and $LAST_SUCCESS"
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
            -Status "$1" -Title "$2" -NoLog
    fi
}

# The notifier runs even when the log cannot be opened: log() then writes to stderr only.
# This script is the only writer of the log during a run: the notifier's output is
# captured here and appended afterwards (-NoLog stops notify.ps1 writing it itself, which
# fails with "being used by another process" while the log is open).
notify() {
    local out rc
    out="$(run_notifier "$1" "$2" 2>&1)"
    rc=$?
    out="${out//$'\r'/}"
    if [ -n "$out" ]; then log "$out"; fi
    if [ "$rc" -ne 0 ]; then log "weekly-run: notifier failed (exit $rc)"; fi
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

# Reads file names on stdin; succeeds when there is at least one and each is one of the three allowed files.
only_allowed_files() {
    local f seen=0
    while IFS= read -r f; do
        case "$f" in
            "$HISTORY"|"$REPORT"|"$LAST_SUCCESS") seen=1 ;;
            *) return 1 ;;
        esac
    done
    [ "$seen" = 1 ]
}

# Exactly one commit may leave this machine, and it may change only the three allowed files.
check_outgoing() {
    local count
    count="$(git rev-list --count "$ORIGIN_REF..HEAD")" || return 1
    [ "$count" = 1 ] || return 1
    git diff --name-only "$ORIGIN_REF..HEAD" | only_allowed_files
}

# Needs exactly one valid 'Offers kept:' line and one 'Source errors:' line; sets
# offers_line, errors_line and offers (the sum of the per-product counts). Exactly one
# 'Notification:' line is needed, in the form "no good offers" or "N good offer(s): names",
# at most 300 characters; it becomes the second half of the notification text (note).
parse_finder_output() {
    local n_offers n_errors n_notes
    n_offers="$(grep -c '^Offers kept:' "$FINDER_OUT" || true)"
    n_errors="$(grep -c '^Source errors:' "$FINDER_OUT" || true)"
    [ "$n_offers" = 1 ] && [ "$n_errors" = 1 ] || return 1
    n_notes="$(grep -c '^Notification:' "$FINDER_OUT" || true)"
    [ "$n_notes" = 1 ] || return 1
    note="$(grep '^Notification:' "$FINDER_OUT")"
    printf '%s\n' "$note" \
        | grep -Eq '^Notification: (no good offers|[1-9][0-9]* good offers?: .+)$' || return 1
    note="${note#Notification: }"
    [ "${#note}" -le 300 ] || return 1
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
    || fail "finder output lacks exactly one valid 'Offers kept:', 'Source errors:' and 'Notification:' line, nothing committed"
if [ "$rc" -eq 0 ]; then
    status="OK, $offers offers"
    code=0
else
    status="Source errors, $offers offers"
    code=2
fi
if [ -n "$note" ]; then
    status="$status; $note"
fi
title="Pepsi prices updated"

# Only the three allowed files may have changed.
others="$(git status --porcelain --untracked-files=no 2>/dev/null \
    | grep -v -x " M $HISTORY" | grep -v -x " M $REPORT" | grep -v -x " M $LAST_SUCCESS" \
    || true)"
if [ -n "$others" ]; then
    log "$others"
    fail "the finder left other tracked changes, nothing committed"
fi

# Stage each of the allowed files that changed; REPORT.md and the last-success file are
# untracked on the very first run.
staged_any=0
for f in "$HISTORY" "$REPORT" "$LAST_SUCCESS"; do
    if [ -n "$(git status --porcelain -- "$f")" ]; then
        git add -- "$f" >> "$LOG" 2>&1 || fail "git add failed"
        staged_any=1
    fi
done
if [ "$staged_any" = 0 ]; then
    log "weekly-run: $FILES_TEXT unchanged, nothing to commit"
    finish "$code" "$status" "$title"
fi
if ! git diff --cached --name-only | only_allowed_files; then
    git reset -q >> "$LOG" 2>&1
    fail "staged files are not exactly $FILES_TEXT, nothing committed"
fi

git commit -q -m "Weekly prices $(date +%F)" -m "$offers_line
$errors_line" >> "$LOG" 2>&1 || fail "git commit failed"

check_outgoing || fail "outgoing range is not exactly one commit changing only $FILES_TEXT, not pushing"
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
    check_outgoing || fail "after the rebase the outgoing range is not exactly one commit changing only $FILES_TEXT, not pushing"
    git push origin "$BRANCH" >> "$LOG" 2>&1 || fail "push failed twice, the commit stays local"
fi

finish "$code" "$status" "$title"
