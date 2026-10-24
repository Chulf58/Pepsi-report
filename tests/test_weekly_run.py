"""Git-safety tests for scripts/weekly-run.sh.

The script runs against a throwaway repository with a bare repository as origin. The
deal finder is replaced through DEALFINDER_CMD and the Windows notifier through
NOTIFY_CMD, so no network, PowerShell or real repository is touched.
"""
import os
import shutil
import subprocess
import tempfile
import unittest

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "scripts", "weekly-run.sh")

FAKE_FINDER = r"""#!/usr/bin/env bash
# FAKE_MODE: append | errors | crash | unchanged | touch_other | race
case "$FAKE_MODE" in
  race)
    # Another machine pushes to origin after our pull and before our push.
    other="$(mktemp -d)"
    git clone -q "$ORIGIN" "$other/c"
    ( cd "$other/c" && echo "remote change" >> other.txt && git add other.txt \
      && git commit -q -m "remote commit" && git push -q origin main )
    rm -rf "$other"
    ;;
esac
case "$FAKE_MODE" in
  append|race|touch_other) echo "2026-10-26,new row" >> data/history.csv ;;
  errors) echo "2026-10-26,new row" >> data/history.csv ;;
  crash) echo "half written" >> data/history.csv ;;
esac
[ "$FAKE_MODE" = touch_other ] && echo "changed" >> other.txt
echo "Offers kept: Pepsi Max: 3, Cult Energy: 2"
if [ "$FAKE_MODE" = errors ]; then
  echo "Source errors: tjek: boom"
else
  echo "Source errors: none"
fi
[ "$FAKE_MODE" = crash ] && { echo "Traceback: boom" >&2; exit 1; }
[ "$FAKE_MODE" = errors ] && exit 2
exit 0
"""

FAKE_NOTIFY = """#!/usr/bin/env bash
printf '%s|%s\\n' "$1" "$2" >> "$NOTIFY_LOG"
"""


class WeeklyRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.origin = os.path.join(self.tmp, "origin.git")
        self.repo = os.path.join(self.tmp, "repo")
        self.notify_log = os.path.join(self.tmp, "notify.log")
        self.finder = self._write("finder.sh", FAKE_FINDER)
        self.notifier = self._write("notify.sh", FAKE_NOTIFY)
        self.env = dict(
            os.environ,
            GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
            GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
            GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid",
            WEEKLY_REPO=self.repo, ORIGIN=self.origin, NOTIFY_LOG=self.notify_log,
            DEALFINDER_CMD="bash " + self.finder, NOTIFY_CMD=self.notifier)
        self.git(self.tmp, "init", "-q", "--bare", "-b", "main", self.origin)
        self.git(self.tmp, "clone", "-q", self.origin, self.repo)
        os.makedirs(os.path.join(self.repo, "data"))
        self._put("data/history.csv", "date,price\n")
        self._put("other.txt", "keep\n")
        self.git(self.repo, "add", "-A")
        self.git(self.repo, "commit", "-q", "-m", "initial")
        self.git(self.repo, "push", "-q", "origin", "main")
        self.base = self.git(self.repo, "rev-parse", "HEAD")

    def _write(self, name, text):
        path = os.path.join(self.tmp, name)
        with open(path, "w", newline="\n") as fh:
            fh.write(text)
        os.chmod(path, 0o755)
        return path

    def _put(self, rel, text, mode="w"):
        with open(os.path.join(self.repo, rel), mode, newline="\n") as fh:
            fh.write(text)

    def git(self, cwd, *args):
        done = subprocess.run(["git", *args], cwd=cwd, env=self.env, check=True,
                              capture_output=True, text=True)
        return done.stdout.strip()

    def run_script(self, mode):
        env = dict(self.env, FAKE_MODE=mode)
        return subprocess.run(["bash", SCRIPT], env=env, capture_output=True, text=True)

    def notifications(self):
        with open(self.notify_log) as fh:
            return fh.read().splitlines()

    def head(self):
        return self.git(self.repo, "rev-parse", "HEAD")

    def test_commits_and_pushes_only_history_csv(self):
        self._put("scratch.txt", "untracked\n")
        done = self.run_script("append")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.git(self.repo, "show", "--name-only", "--format=", "HEAD"),
                         "data/history.csv")
        self.assertEqual(self.git(self.repo, "rev-parse", "HEAD~1"), self.base)
        subject = self.git(self.repo, "log", "-1", "--format=%s")
        self.assertRegex(subject, r"^Weekly prices \d{4}-\d{2}-\d{2}$")
        body = self.git(self.repo, "log", "-1", "--format=%b")
        self.assertIn("Offers kept: Pepsi Max: 3, Cult Energy: 2", body)
        self.assertIn("Source errors: none", body)
        self.assertEqual(self.git(self.origin, "rev-parse", "main"), self.head())
        self.assertIn("scratch.txt", self.git(self.repo, "status", "--porcelain"))
        self.assertEqual(self.notifications(), ["OK, 5 offers|Pepsi prices updated"])
        with open(os.path.join(self.repo, "out", "last-run.log")) as fh:
            self.assertIn("Offers kept:", fh.read())

    def test_source_errors_still_commit_and_exit_2(self):
        done = self.run_script("errors")
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertEqual(self.git(self.origin, "rev-parse", "main"), self.head())
        self.assertIn("Source errors: tjek: boom", self.git(self.repo, "log", "-1", "--format=%b"))
        self.assertEqual(self.notifications(), ["Source errors, 5 offers|Pepsi prices updated"])

    def test_refuses_when_another_tracked_file_is_dirty(self):
        self._put("other.txt", "edited\n")
        done = self.run_script("append")
        self.assertEqual(done.returncode, 1)
        self.assertEqual(self.head(), self.base)
        with open(os.path.join(self.repo, "data", "history.csv")) as fh:
            self.assertNotIn("new row", fh.read())
        self.assertTrue(self.notifications()[0].startswith("failed:"))

    def test_refuses_when_something_else_is_staged(self):
        self._put("other.txt", "staged\n")
        self.git(self.repo, "add", "other.txt")
        done = self.run_script("append")
        self.assertEqual(done.returncode, 1)
        self.assertEqual(self.head(), self.base)
        self.assertEqual(self.git(self.origin, "rev-parse", "main"), self.base)

    def test_refuses_when_the_finder_changes_another_tracked_file(self):
        done = self.run_script("touch_other")
        self.assertEqual(done.returncode, 1)
        self.assertEqual(self.head(), self.base)
        self.assertEqual(self.git(self.origin, "rev-parse", "main"), self.base)
        self.assertTrue(self.notifications()[0].startswith("failed:"))

    def test_no_commit_on_a_crash(self):
        done = self.run_script("crash")
        self.assertEqual(done.returncode, 1)
        self.assertEqual(self.head(), self.base)
        self.assertEqual(self.git(self.origin, "rev-parse", "main"), self.base)
        self.assertEqual(self.git(self.repo, "diff", "--cached", "--name-only"), "")
        self.assertIn("failed: finder crashed (exit 1)", self.notifications()[0])

    def test_no_commit_when_history_is_unchanged(self):
        done = self.run_script("unchanged")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.head(), self.base)
        self.assertEqual(self.notifications(), ["OK, 5 offers|Pepsi prices updated"])

    def test_switches_to_main_first(self):
        self.git(self.repo, "checkout", "-q", "-b", "side")
        done = self.run_script("append")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.git(self.repo, "branch", "--show-current"), "main")
        self.assertEqual(self.git(self.origin, "rev-parse", "main"), self.head())

    def test_rejected_push_is_rebased_once_and_pushed(self):
        done = self.run_script("race")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(self.git(self.origin, "rev-parse", "main"), self.head())
        subjects = self.git(self.repo, "log", "--format=%s", "-3").splitlines()
        self.assertEqual(subjects[1], "remote commit")
        self.assertRegex(subjects[0], r"^Weekly prices ")
        with open(os.path.join(self.repo, "out", "last-run.log")) as fh:
            self.assertIn("push rejected", fh.read())


if __name__ == "__main__":
    unittest.main()
