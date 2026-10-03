import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "check_source", Path(__file__).resolve().parents[1] / "scripts/check_source.py"
)
check_source = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_source)


class SourceAuditTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self.lock = {
            "nodes": {
                "root": {"inputs": {"nixpkgs": "nixpkgs"}},
                "nixpkgs": {
                    field: {"type": "github", "owner": "NixOS", "repo": "nixpkgs"}
                    for field in ("original", "locked")
                },
            }
        }
        self.write_lock()

    def write_lock(self):
        (self.root / "flake.lock").write_text(json.dumps(self.lock))
        subprocess.run(["git", "-C", str(self.root), "add", "flake.lock"], check=True)

    def track(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        subprocess.run(["git", "-C", str(self.root), "add", name], check=True)

    def test_public_text_source_passes(self):
        self.track("README.md", b"Small stable package base.\n")
        self.assertEqual(check_source.audit(self.root), [])

    def test_font_assets_and_disguised_fonts_fail(self):
        self.track("assets/PrivateFont.OTF", b"font data")
        self.track("assets/renamed.dat", b"wOF2" + b"\0" * 12)
        self.assertEqual(
            sum("font asset" in error for error in check_source.audit(self.root)), 2
        )

    def test_binary_archive_fails(self):
        self.track("assets/fonts.zip", b"PK\x03\x04\xff")
        self.assertTrue(any("UTF-8" in error for error in check_source.audit(self.root)))

    def test_staged_font_is_rejected_after_worktree_replacement(self):
        self.track("assets/renamed.dat", b"wOF2" + b"\0" * 12)
        (self.root / "assets/renamed.dat").write_text("ordinary text")
        self.assertTrue(any("font asset" in error for error in check_source.audit(self.root)))

    def test_staged_private_dependency_is_rejected_after_worktree_replacement(self):
        public_lock = json.dumps(self.lock)
        self.lock["nodes"]["private-font"] = {}
        self.write_lock()
        (self.root / "flake.lock").write_text(public_lock)
        self.assertTrue(any("lock graph" in error for error in check_source.audit(self.root)))

    def test_source_symlink_fails(self):
        (self.root / "external-font").symlink_to("/outside/PrivateFont.ttf")
        subprocess.run(["git", "-C", str(self.root), "add", "external-font"], check=True)
        self.assertTrue(any("symlinks" in error for error in check_source.audit(self.root)))

    def test_private_font_dependency_fails(self):
        self.lock["nodes"]["private-font"] = {"locked": {"url": "git+ssh://private.invalid/fonts"}}
        self.lock["nodes"]["root"]["inputs"]["private-font"] = "private-font"
        self.write_lock()
        self.assertTrue(any("lock graph" in error for error in check_source.audit(self.root)))

    def test_nixpkgs_from_another_owner_fails(self):
        self.lock["nodes"]["nixpkgs"]["locked"]["owner"] = "another-owner"
        self.write_lock()
        self.assertTrue(any("public NixOS/nixpkgs" in error for error in check_source.audit(self.root)))
