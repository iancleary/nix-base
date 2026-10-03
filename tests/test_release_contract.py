"""Exercise release guards with an isolated Git remote and a fake GitHub CLI."""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
VERSION = "2026.10.03.00"


class ReleaseContractTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.repo = self.directory / "repo"
        self.remote = self.directory / "remote.git"
        self.bin = self.directory / "bin"
        self.bin.mkdir()
        self.gh_calls = self.directory / "gh-calls"
        self.gh_calls.touch()
        gh = self.bin / "gh"
        gh.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$TEST_GH_CALLS"\nexit 0\n')
        gh.chmod(0o755)
        self.env = dict(os.environ, PATH=f"{self.bin}{os.pathsep}{os.environ['PATH']}",
                        TEST_GH_CALLS=str(self.gh_calls), GIT_CONFIG_NOSYSTEM="1",
                        GIT_CONFIG_GLOBAL=os.devnull)
        self.run_command(["git", "init", "--bare", "-q", str(self.remote)])
        self.run_command(["git", "init", "-q", "-b", "main", str(self.repo)])
        self.git("config", "user.name", "Release Test")
        self.git("config", "user.email", "release-test@example.invalid")
        (self.repo / "scripts").mkdir()
        for script in ("release.py", "cut_release.py"):
            shutil.copyfile(ROOT / "scripts" / script, self.repo / "scripts" / script)
        (self.repo / "README.md").write_text("Isolated release test.\n")
        self.write_contract()
        self.commit()
        self.git("remote", "add", "origin", str(self.remote))
        self.git("push", "-q", "origin", "main")

    def run_command(self, argv, *, cwd=None):
        return subprocess.run(argv, cwd=cwd, env=self.env, text=True,
                              capture_output=True, check=True).stdout.strip()

    def git(self, *args):
        return self.run_command(["git", *args], cwd=self.repo)

    def commit(self):
        self.git("add", ".")
        self.git("commit", "-qm", "test: prepare isolated release")

    def write_contract(self, check="pass"):
        # Exercise the consumer contract. Only the launcher and controlled checks differ.
        contract = (ROOT / "release.toml").read_text().replace(
            '"uv", "run", "--script"', json.dumps(sys.executable)
        )
        checks = f'[checks]\ncommands = {json.dumps([[sys.executable, "-c", check]])}\n\n'
        contract, count = re.subn(r"(?ms)^\[checks\]\n.*?(?=^\[|\Z)",
                                 lambda match: checks, contract)
        self.assertEqual(count, 1, "production contract must declare one checks table")
        (self.repo / "release.toml").write_text(contract)

    def runner(self, action, *args):
        return subprocess.run([sys.executable, "scripts/release.py", action, *args, "--json"],
                              cwd=self.repo, env=self.env, text=True, capture_output=True)

    def plan(self):
        result = self.runner("plan", "--version", VERSION)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        return json.loads(result.stdout)

    def snapshot(self):
        return (self.git("rev-parse", "HEAD"), self.git("status", "--porcelain"),
                self.git("tag", "--list"), self.git("ls-remote", "origin"))

    def assert_rejected(self, result, message):
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(message, result.stdout + result.stderr)
        self.assertNotIn("release create", self.gh_calls.read_text())

    def test_tag_only_plan_accepts_calver_and_captures_exact_guards(self):
        before = self.snapshot()
        plan = self.plan()
        self.assertEqual(plan["version"], VERSION)
        self.assertEqual(plan["tag"], VERSION)
        self.assertEqual(plan["target_commit"], self.git("rev-parse", "HEAD"))
        self.assertEqual(plan["config_sha256"],
                         hashlib.sha256((self.repo / "release.toml").read_bytes()).hexdigest())
        self.assertFalse(plan["checks_verified"])
        self.assertIsNone(plan["ready"])
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.gh_calls.read_text(), "")

    def test_consumer_validator_rejects_invalid_date_before_mutation(self):
        for action in ("plan", "run"):
            before = self.snapshot()
            args = ("--apply",) if action == "run" else ()
            result = self.runner(action, "--version", "2026.02.29.00", *args)
            with self.subTest(action=action):
                self.assert_rejected(result, "day is out of range for month")
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(self.gh_calls.read_text(), "")

    def test_consumer_validator_rejects_explicit_serial_jump_before_mutation(self):
        for action in ("plan", "run"):
            before = self.snapshot()
            args = ("--apply",) if action == "run" else ()
            result = self.runner(action, "--version", "2026.10.03.42", *args)
            with self.subTest(action=action):
                self.assert_rejected(result, "New release version must be 2026.10.03.00")
                self.assertEqual(self.snapshot(), before)
                self.assertEqual(self.gh_calls.read_text(), "")

    def test_default_run_is_a_read_only_dry_run(self):
        plan = self.plan()
        before = self.snapshot()
        result = self.runner("run", "--version", VERSION,
                             "--expected-head", plan["target_commit"],
                             "--expected-config", plan["config_sha256"])
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertEqual(json.loads(result.stdout)["mode"], "dry_run")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.gh_calls.read_text(), "")

    def test_failed_checks_block_local_tag_push_and_publication(self):
        self.write_contract("raise SystemExit('intentional failing check')")
        self.commit()
        before = self.snapshot()
        result = self.runner("run", "--apply", "--version", VERSION)
        self.assert_rejected(result, "release check failed")
        self.assertEqual(self.snapshot(), before)

    def test_check_that_changes_head_blocks_tagging_and_publication(self):
        self.write_contract("import subprocess; subprocess.run(['git', 'commit', '--allow-empty', '-qm', 'test: changed HEAD'], check=True)")
        self.commit()
        remote_before = self.git("ls-remote", "origin")
        result = self.runner("run", "--apply", "--version", VERSION)
        self.assert_rejected(result, "HEAD changed during checks")
        self.assertEqual(self.git("tag", "--list"), "")
        self.assertEqual(self.git("ls-remote", "origin"), remote_before)

    def test_check_that_changes_files_blocks_tagging_and_publication(self):
        self.write_contract("from pathlib import Path; Path('README.md').write_text('Check modified source.')")
        self.commit()
        head, _, tags, remote = self.snapshot()
        result = self.runner("run", "--apply", "--version", VERSION)
        self.assert_rejected(result, "checks modified the working tree")
        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        self.assertEqual(self.git("tag", "--list"), tags)
        self.assertEqual(self.git("ls-remote", "origin"), remote)

    def test_dirty_tree_blocks_release_before_checks_or_publication(self):
        (self.repo / "README.md").write_text("Uncommitted change.\n")
        before = self.snapshot()
        result = self.runner("run", "--apply", "--version", VERSION)
        self.assert_rejected(result, "working tree must be clean")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.gh_calls.read_text(), "")

    def test_changed_runner_checksum_blocks_plan(self):
        with (self.repo / "scripts/release.py").open("a") as stream:
            stream.write("\n# Accidental runner drift.\n")
        self.commit()
        before = self.snapshot()
        self.assert_rejected(self.runner("plan", "--version", VERSION), "checksum mismatch")
        self.assertEqual(self.snapshot(), before)

    def test_stale_head_guard_blocks_execution(self):
        plan = self.plan()
        (self.repo / "README.md").write_text("New commit after planning.\n")
        self.commit()
        before = self.snapshot()
        result = self.runner("run", "--apply", "--version", VERSION,
                             "--expected-head", plan["target_commit"],
                             "--expected-config", plan["config_sha256"])
        self.assert_rejected(result, "HEAD differs from --expected-head")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.gh_calls.read_text(), "")

    def test_stale_config_guard_blocks_execution(self):
        plan = self.plan()
        with (self.repo / "release.toml").open("a") as stream:
            stream.write("\n# Configuration changed after planning.\n")
        self.commit()
        before = self.snapshot()
        result = self.runner("run", "--apply", "--version", VERSION,
                             "--expected-head", self.git("rev-parse", "HEAD"),
                             "--expected-config", plan["config_sha256"])
        self.assert_rejected(result, "configuration differs from --expected-config")
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.gh_calls.read_text(), "")


if __name__ == "__main__":
    unittest.main()
