"""Test calendar version selection and the publication CI gate without network access."""

from copy import deepcopy
from datetime import date, datetime
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


policy = load_script("cut_release")
ci = load_script("check_release_ci")


class CalendarVersionTests(unittest.TestCase):
    def test_valid_dates_and_fixed_width_versions(self):
        for version in ("2024.02.29.00", "2026.10.03.00", "2026.12.31.99"):
            with self.subTest(version=version):
                self.assertIsNone(policy.validate_version(version))

    def test_bad_dates_or_format_are_rejected(self):
        invalid = ("2026.02.29.00", "2026.13.01.00", "2026.04.31.00", "0000.01.01.00",
                   "2026.10.03.100", "2026.10.03.0", "2026.1.03.00", "v2026.10.03.00",
                   "2026.10.03.00\n", " 2026.10.03.00", "2026.10.03.-1")
        for version in invalid:
            with self.subTest(version=version), self.assertRaises(ValueError):
                policy.validate_version(version)

    def test_current_version_filters_unrelated_and_invalid_tags(self):
        tags = ["v1.0.0", "2026.02.29.99", "2026.10.03.02", "2025.12.31.99",
                "2026.10.03.01", "wip"]
        self.assertCountEqual(policy.release_tags(tags),
                              ["2026.10.03.02", "2025.12.31.99", "2026.10.03.01"])
        self.assertEqual(policy.current_version(tags), "2026.10.03.02")
        self.assertEqual(policy.current_version(["v1.0.0"]), "")

    def test_first_release_and_day_reset_start_at_zero(self):
        self.assertEqual(policy.next_version([], date(2026, 10, 3)), "2026.10.03.00")
        self.assertEqual(policy.next_version(["2026.10.02.99"], date(2026, 10, 3)),
                         "2026.10.03.00")

    def test_serial_uses_maximum_instead_of_count(self):
        tags = ["2026.10.03.00", "2026.10.03.07", "2026.10.03.07", "v2026.10.03.98"]
        self.assertEqual(policy.next_version(tags, date(2026, 10, 3)), "2026.10.03.08")

    def test_serial_overflow_requires_another_day(self):
        with self.assertRaises(ValueError):
            policy.next_version(["2026.10.03.99"], date(2026, 10, 3))

    def test_fresh_selected_version_must_start_at_zero_or_use_next_serial(self):
        cases = [("2026.10.03.42", []),
                 ("2026.10.03.03", ["2026.10.03.00"]),
                 ("2026.10.03.01", ["2026.10.02.99"])]
        for version, tags in cases:
            with self.subTest(version=version, tags=tags), self.assertRaises(ValueError):
                policy.validate_selected_version(version, tags)

    def test_selected_version_accepts_correct_next_and_existing_resume_tags(self):
        cases = [("2026.10.03.00", []),
                 ("2026.10.03.08", ["2026.10.03.00", "2026.10.03.07"]),
                 ("2026.10.03.07", ["2026.10.03.00", "2026.10.03.07"])]
        for version, tags in cases:
            with self.subTest(version=version, tags=tags):
                self.assertIsNone(policy.validate_selected_version(version, tags))

    def test_invalid_date_is_rejected_before_remote_query_or_runner(self):
        arguments = (["--validate-version", "2026.02.29.00"],
                     ["--version", "2026.02.29.00", "--apply"])
        for args in arguments:
            with self.subTest(args=args), \
                 patch.object(policy, "local_remote_tags") as query, \
                 patch.object(policy.subprocess, "call") as run:
                with self.assertRaises(ValueError):
                    policy.main(args)
                query.assert_not_called()
                run.assert_not_called()

    def test_release_date_uses_phoenix_timezone(self):
        local_time = datetime(2026, 10, 2, 23, 30, tzinfo=ZoneInfo("America/Phoenix"))
        with patch.object(policy, "datetime") as clock:
            clock.now.return_value = local_time
            self.assertEqual(policy.release_day(), date(2026, 10, 2))
            self.assertEqual(str(clock.now.call_args.args[0]), "America/Phoenix")

    def test_convenience_command_defaults_to_dry_run(self):
        with patch.object(policy, "local_remote_tags", return_value=[]), \
             patch.object(policy, "release_day", return_value=date(2026, 10, 3)), \
             patch.object(policy.subprocess, "call", return_value=0) as run:
            self.assertEqual(policy.main([]), 0)
            command = run.call_args.args[0]
            self.assertIn("--dry-run", command)
            self.assertNotIn("--apply", command)
            self.assertEqual(command[command.index("--version") + 1], "2026.10.03.00")

    def test_remote_only_tags_are_observed_without_fetching_or_mutating_refs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, remote = root / "repo", root / "remote.git"
            env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)

            def git(*args, cwd=None):
                return subprocess.run(["git", *args], cwd=cwd, env=env, text=True,
                                      capture_output=True, check=True).stdout.strip()

            git("init", "--bare", "-q", str(remote))
            git("init", "-q", "-b", "main", str(repo))
            git("config", "user.name", "Release Test", cwd=repo)
            git("config", "user.email", "release-test@example.invalid", cwd=repo)
            (repo / "README.md").write_text("Local fixture.\n")
            git("add", ".", cwd=repo)
            git("commit", "-qm", "test: local tag fixture", cwd=repo)
            git("remote", "add", "origin", str(remote), cwd=repo)
            git("push", "-q", "origin", "main", cwd=repo)
            git("tag", "2026.10.03.00", cwd=repo)
            git("--git-dir", str(remote), "tag", "2026.10.03.07", "main")
            before = (git("show-ref", cwd=repo), git("ls-remote", "origin", cwd=repo))
            tags = policy.local_remote_tags(repo)
            self.assertCountEqual(tags, ["2026.10.03.00", "2026.10.03.07"])
            self.assertEqual(policy.next_version(tags, date(2026, 10, 3)), "2026.10.03.08")
            self.assertEqual((git("show-ref", cwd=repo), git("ls-remote", "origin", cwd=repo)),
                             before)
            self.assertNotIn("2026.10.03.07", git("tag", "--list", cwd=repo))


class ReleaseCIGateTests(unittest.TestCase):
    def setUp(self):
        self.head = "a" * 40
        self.run = {
            "id": 10, "run_attempt": 1, "head_sha": self.head, "head_branch": "main",
            "event": "push", "path": ".github/workflows/check.yml", "status": "completed",
            "conclusion": "success", "head_repository": {"full_name": "iancleary/nix-base"},
            "html_url": "https://github.com/iancleary/nix-base/actions/runs/10",
        }
        self.jobs = [{"name": f"check ({system})", "status": "completed", "conclusion": "success"}
                     for system in ci.SYSTEMS]
        self.outputs = {
            ("git", "status", "--short"): "",
            ("git", "branch", "--show-current"): "main",
            ("git", "remote", "get-url", "--all", "origin"): "git@github.com:iancleary/nix-base.git",
            ("git", "remote", "get-url", "--push", "--all", "origin"): "https://github.com/iancleary/nix-base.git",
            ("gh", "repo", "view", "--json", "url", "--jq", ".url"): "https://github.com/iancleary/nix-base",
            ("git", "rev-parse", "HEAD"): self.head,
        }

    def check(self, *, runs=None, latest=None, remote_heads=None):
        responses = [{"workflow_runs": runs if runs is not None else [self.run]},
                     {"total_count": 3, "jobs": self.jobs},
                     latest if latest is not None else self.run]
        with patch.object(ci, "output", side_effect=lambda repo, *args: self.outputs[args]), \
             patch.object(ci, "api", side_effect=responses) as queries, \
             patch.object(ci, "remote_main", side_effect=remote_heads or [self.head, self.head]), \
             patch("builtins.print"):
            ci.check_ci(Path("/isolated-fixture"))
            return [call.args[1] for call in queries.call_args_list]

    def test_success_requires_all_native_jobs_and_the_current_attempt(self):
        endpoints = self.check()
        self.assertEqual(endpoints, [
            "repos/iancleary/nix-base/actions/workflows/check.yml/runs"
            f"?head_sha={self.head}&branch=main&event=push&per_page=100",
            "repos/iancleary/nix-base/actions/runs/10/attempts/1/jobs?per_page=100",
            "repos/iancleary/nix-base/actions/runs/10",
        ])

    def test_run_must_be_successful_main_push_in_the_right_repository(self):
        changes = {"head_sha": "b" * 40, "head_branch": "feature", "event": "pull_request",
                   "path": ".github/workflows/other.yml", "status": "in_progress",
                   "conclusion": "failure", "head_repository": {"full_name": "other/repo"},
                   "id": "10", "run_attempt": None}
        for key, value in changes.items():
            run = deepcopy(self.run)
            run[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                ci.validate_run(run, self.head)

    def test_missing_duplicate_or_unsuccessful_native_job_blocks_release(self):
        variants = [self.jobs[:-1], [self.jobs[0]] * 3,
                    [{**self.jobs[0], "conclusion": "skipped"}, *self.jobs[1:]],
                    [{**self.jobs[0], "status": "in_progress"}, *self.jobs[1:]]]
        for jobs in variants:
            with self.subTest(jobs=jobs), self.assertRaises(ValueError):
                ci.validate_jobs(jobs)

    def test_clean_main_and_approved_fetch_and_push_origins_are_required(self):
        changes = {("git", "status", "--short"): " M README.md",
                   ("git", "branch", "--show-current"): "feature",
                   ("git", "remote", "get-url", "--all", "origin"): "https://github.com/other/nix-base.git",
                   ("git", "remote", "get-url", "--push", "--all", "origin"): "git@github.com:other/nix-base.git"}
        for command, result in changes.items():
            with self.subTest(command=command), patch.dict(self.outputs, {command: result}), \
                 self.assertRaises(ValueError):
                self.check()

    def test_second_foreign_push_url_blocks_release(self):
        command = ("git", "remote", "get-url", "--push", "--all", "origin")
        urls = "https://github.com/iancleary/nix-base.git\ngit@github.com:other/nix-base.git"
        with patch.dict(self.outputs, {command: urls}), self.assertRaises(ValueError):
            self.check()

    def test_wrong_resolved_github_repository_blocks_release(self):
        command = ("gh", "repo", "view", "--json", "url", "--jq", ".url")
        with patch.dict(self.outputs, {command: "https://github.com/other/nix-base"}), \
             self.assertRaises(ValueError):
            self.check()

    def test_latest_failed_or_pending_run_blocks_an_older_success(self):
        for state in ({"conclusion": "failure"},
                      {"status": "in_progress", "conclusion": None}):
            latest = {**self.run, "id": 11, **state}
            with self.subTest(state=state), self.assertRaises(ValueError):
                self.check(runs=[self.run, latest])

    def test_no_matching_run_blocks_release(self):
        with self.assertRaises(ValueError):
            self.check(runs=[])

    def test_changed_attempt_or_remote_main_blocks_release(self):
        with self.assertRaises(ValueError):
            self.check(latest={**self.run, "run_attempt": 2})
        with self.assertRaises(ValueError):
            self.check(remote_heads=["b" * 40])
        with self.assertRaises(ValueError):
            self.check(remote_heads=[self.head, "b" * 40])


if __name__ == "__main__":
    unittest.main()
