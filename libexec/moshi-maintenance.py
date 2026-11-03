#!/usr/bin/env python3
"""Preview or apply Moshi maintenance on macOS and Arch WSL."""
from __future__ import annotations

import argparse
import datetime
from enum import Enum
import json
import os
from pathlib import Path
import plistlib
import shlex
import shutil
import subprocess
import sys
import tempfile
import time


HOME = Path.home()
TARGETS = ("claude", "codex", "pi")
LAUNCHD_LABEL = "app.getmoshi.moshi-hook"
SYSTEMD_UNIT = "moshi-hook.service"
UPSTREAM_INSTALL_URL = "https://getmoshi.app/install.sh"
# The moshi-hook Homebrew coordinates. Set MOSHI_BREWFILE to read the tap and
# formula from a Brewfile that declares them between "# BEGIN moshi-hook" and
# "# END moshi-hook" markers instead.
DEFAULT_TAP = "rjyo/moshi"
DEFAULT_FORMULA = "moshi-hook"


class Platform(Enum):
    MACOS = "macos"
    WSL_ARCH = "wsl-archlinux"


def detect_platform() -> Platform:
    if sys.platform == "darwin":
        return Platform.MACOS
    if sys.platform.startswith("linux"):
        release = Path("/proc/sys/kernel/osrelease").read_text().lower()
        os_release = Path("/etc/os-release").read_text().splitlines()
        if "microsoft" in release and any(line in ('ID=arch', 'ID="arch"') for line in os_release):
            return Platform.WSL_ARCH
    raise RuntimeError("only macOS and Arch Linux under WSL are supported")


def local_binary() -> Path:
    return HOME / ".local/bin/moshi-hook"


def hook_files() -> tuple[Path, ...]:
    return (
        HOME / ".claude/settings.json",
        HOME / ".codex/config.toml",
        HOME / ".codex/hooks.json",
        HOME / ".pi/agent/extensions/moshi-hooks.ts",
    )


def service_file(platform: Platform) -> Path:
    if platform is Platform.MACOS:
        return HOME / "Library/LaunchAgents" / f"{LAUNCHD_LABEL}.plist"
    return HOME / ".config/systemd/user" / SYSTEMD_UNIT


def brewfile_moshi() -> tuple[str, str]:
    """Return the moshi-hook tap and formula."""
    override = os.environ.get("MOSHI_BREWFILE", "")
    if not override:
        return DEFAULT_TAP, DEFAULT_FORMULA
    lines = Path(override).expanduser().read_text().splitlines()
    try:
        start = lines.index("# BEGIN moshi-hook")
        end = lines.index("# END moshi-hook")
    except ValueError as error:
        raise RuntimeError(f"{override} is missing moshi-hook markers") from error
    if end < start:
        raise RuntimeError(f"{override} moshi-hook markers are out of order")
    taps = []
    formulas = []
    for line in lines[start + 1:end]:
        if line.startswith('tap "') and line.endswith('"'):
            taps.append(line[len('tap "'):-1])
        elif line.startswith('brew "') and line.endswith('"'):
            formulas.append(line[len('brew "'):-1])
    if len(taps) != 1 or len(formulas) != 1 or "/" not in taps[0] or "/" in formulas[0] or not formulas[0]:
        raise RuntimeError(f"{override} must declare one moshi tap and formula")
    return taps[0], formulas[0]


def package_commands(platform: Platform) -> list[list[str]]:
    """Arch WSL package upgrade. macOS uses upgrade_homebrew_moshi() instead."""
    if platform is not Platform.WSL_ARCH:
        raise RuntimeError(f"{platform.value} has no general package upgrade on the Moshi path")
    return [["sudo", "pacman", "-Syu", "--needed", "mosh"]]


def run_upstream_installer() -> None:
    """Download and run the moshi-hook upstream installer.

    Skips first-run guidance and service startup; hooks and the service are
    separate steps of this procedure. INSTALL_DIR keeps the preflight-owned
    ~/.local/bin location.
    """
    scratch = tempfile.mkdtemp(prefix="moshi-upgrade.")
    try:
        script = Path(scratch) / "install.sh"
        run(["curl", "-fsSL", "--retry", "3", "--connect-timeout", "10", "--max-time", "120",
             UPSTREAM_INSTALL_URL, "-o", str(script)])
        run(["sh", "-n", str(script)])
        environment = dict(os.environ,
                           INSTALL_DIR=os.environ.get("INSTALL_DIR", str(HOME / ".local/bin")),
                           MOSHI_HOOK_SKIP_FIRST_RUN="1",
                           MOSHI_HOOK_SKIP_SERVICE="1")
        print("Run: sh", script, flush=True)
        result = subprocess.run(["sh", str(script)], env=environment)
        if result.returncode:
            raise RuntimeError(f"upstream installer failed ({result.returncode}): {UPSTREAM_INSTALL_URL}")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def run(command: list[str], *, capture: bool = False, timeout: int | None = None,
        check: bool = True, echo: bool | None = None):
    if echo is None:
        echo = not capture
    if echo:
        print("Run:", shlex.join(command), flush=True)
    environment = dict(os.environ, MOSHI_HOOK_SKIP_FIRST_RUN="1",
                       HOMEBREW_NO_AUTO_UPDATE="1", HOMEBREW_NO_INSTALL_CLEANUP="1")
    # The binary wrapper sets its own skip flag. Explicit service commands must run.
    environment.pop("MOSHI_HOOK_SKIP_SERVICE", None)
    result = subprocess.run(command, env=environment, capture_output=capture,
                            text=True, timeout=timeout)
    if check and result.returncode:
        # Captured diagnostics may contain machine-local account metadata.
        raise RuntimeError(f"command failed ({result.returncode}): {shlex.join(command)}")
    return result


def upgrade_homebrew_moshi() -> None:
    """Refresh Homebrew, then install and upgrade only the moshi-hook formula.

    Install runs when the Homebrew prefix has no moshi-hook binary. Other
    formulae are left alone. A dependency declared by the formula is Homebrew's
    to install; this recipe never names mosh.
    """
    tap, formula = brewfile_moshi()
    run(["brew", "update"])
    run(["brew", "tap", tap])
    run(["brew", "trust", tap])
    if not hook_binary(Platform.MACOS).is_file():
        run(["brew", "install", formula])
    run(["brew", "upgrade", formula])


def check_paths(paths: tuple[Path, ...]) -> None:
    for path in paths:
        if path.is_symlink() or path.resolve() != path.absolute():
            raise RuntimeError(f"refusing a symlinked managed path: {path}")
        if path.exists() and (not path.is_file() or path.stat().st_uid != os.getuid()):
            raise RuntimeError(f"refusing a non-regular or foreign-owned file: {path}")


def hook_binary(platform: Platform) -> Path:
    if platform is Platform.WSL_ARCH:
        return local_binary()
    prefix_text = run(["brew", "--prefix"], capture=True, timeout=30).stdout.strip()
    prefix = Path(prefix_text)
    if not prefix.is_absolute():
        raise RuntimeError("brew --prefix did not return an absolute path")
    _, formula = brewfile_moshi()
    binary = prefix / "bin" / formula
    if binary.exists() or binary.is_symlink():
        resolved = binary.resolve()
        root = prefix.resolve()
        if resolved != root and root not in resolved.parents:
            raise RuntimeError(f"moshi-hook resolved outside the Homebrew prefix: {resolved}")
    return binary


def custom_launch_agent_plist() -> Path | None:
    """Return the pre-Homebrew plist, or None when that agent is not installed."""
    unit = service_file(Platform.MACOS)
    if unit.is_symlink() or (unit.exists() and not unit.is_file()):
        raise RuntimeError("refusing a symlinked or non-regular Moshi launch agent plist")
    if not unit.exists():
        return None
    data = plistlib.loads(unit.read_bytes())
    if data.get("Label") != LAUNCHD_LABEL:
        raise RuntimeError("the Moshi launch agent uses another installation")
    return unit


def preflight(platform: Platform, *, upgrade: bool) -> None:
    if os.geteuid() == 0:
        raise RuntimeError("run as the normal user, not root")
    defaults = {"CODEX_HOME": HOME / ".codex", "PI_CODING_AGENT_DIR": HOME / ".pi/agent",
                "CLAUDE_CONFIG_DIR": HOME / ".claude", "XDG_CONFIG_HOME": HOME / ".config"}
    for name, default in defaults.items():
        if os.environ.get(name, str(default)) != str(default):
            raise RuntimeError(f"unset {name}; backups cover only the default configuration homes")
    check_paths(hook_files())
    if platform is Platform.MACOS:
        if shutil.which("brew") is None:
            raise RuntimeError(
                "Homebrew is required on macOS. This repository does not install Homebrew.")
        if os.environ.get("INSTALL_DIR"):
            raise RuntimeError("unset INSTALL_DIR; macOS Moshi is installed with Homebrew")
        brewfile_moshi()
        hook_binary(platform)
        custom_launch_agent_plist()
    else:
        if os.environ.get("INSTALL_DIR", str(local_binary().parent)) != str(local_binary().parent):
            raise RuntimeError("unset INSTALL_DIR; this workflow owns ~/.local/bin/moshi-hook")
        check_paths((local_binary(), service_file(platform)))
        alias = local_binary().parent / "moshi"
        if alias.is_symlink() and os.readlink(alias) != "moshi-hook":
            raise RuntimeError("refusing a foreign ~/.local/bin/moshi symlink")
        if shutil.which("pacman") is None or shutil.which("systemctl") is None:
            raise RuntimeError("pacman and the systemd user manager are required")
        loaded = run(["systemctl", "--user", "show", "--property=FragmentPath", "--value", SYSTEMD_UNIT],
                     capture=True, timeout=10).stdout.strip()
        unit = service_file(platform)
        if loaded and Path(loaded) != unit:
            raise RuntimeError("the loaded Moshi user unit belongs to another installation")
        if unit.exists():
            starts = [shlex.split(line.strip().removeprefix("ExecStart="))
                      for line in unit.read_text().splitlines() if line.strip().startswith("ExecStart=")]
            if len(starts) != 1 or not starts[0] or starts[0][0] != str(local_binary()):
                raise RuntimeError("the Moshi user unit uses another installation")
        wants = unit.parent / "default.target.wants" / SYSTEMD_UNIT
        if wants.parent.resolve() != wants.parent.absolute():
            raise RuntimeError("refusing a symlinked systemd wants directory")
        if (wants.exists() or wants.is_symlink()) and (not wants.is_symlink() or wants.resolve() != unit.resolve()):
            raise RuntimeError("refusing a foreign Moshi systemd enablement target")
    if upgrade and platform is Platform.WSL_ARCH and shutil.which("curl") is None:
        raise RuntimeError("curl is required by the executable installer")
    if not upgrade and not hook_binary(platform).is_file():
        raise RuntimeError("install the binary with just moshi::install first")


def backup(platform: Platform, *, upgrade: bool) -> Path:
    base = HOME / ".local/state/dotfiles/moshi-backups"
    if base.resolve() != base.absolute():
        raise RuntimeError("refusing a symlinked private backup location")
    for parent in (base, *base.parents):
        if parent == HOME:
            break
        if parent.exists() and (not parent.is_dir() or parent.stat().st_uid != os.getuid() or
                                parent.stat().st_mode & 0o022):
            raise RuntimeError(f"private backup parent must be user-owned and not group/world writable: {parent}")
    os.umask(0o077)
    directory = base / datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    directory.mkdir(parents=True, mode=0o700)
    paths = (*hook_files(), service_file(platform))
    if upgrade and platform is Platform.WSL_ARCH:
        paths += (local_binary(), service_file(platform).parent / "default.target.wants" / SYSTEMD_UNIT)
    entries = []
    for path in paths:
        relative = path.relative_to(HOME)
        existed = path.exists() or path.is_symlink()
        entries.append({"path": str(relative), "existed": existed})
        if existed:
            target = directory / "files" / relative
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.copy2(path, target, follow_symlinks=False)
    (directory / "manifest.json").write_text(json.dumps(entries, indent=2) + "\n")
    print("Private backup:", directory, flush=True)
    return directory


def install_hooks(platform: Platform) -> None:
    # Closed stdin preserves Codex's shared-server choice instead of accepting
    # an interactive request to change it. No doctor --yes is ever invoked.
    environment = dict(os.environ, MOSHI_HOOK_SKIP_FIRST_RUN="1", MOSHI_HOOK_SKIP_SERVICE="1")
    command = [str(hook_binary(platform)), "install", "--target", ",".join(TARGETS)]
    print("Run:", shlex.join(command), flush=True)
    result = subprocess.run(command, env=environment, stdin=subprocess.DEVNULL)
    if result.returncode:
        raise RuntimeError("hook installation failed; inspect the private backup before retrying")


def status(platform: Platform, *, require_ready: bool) -> None:
    binary = hook_binary(platform)
    if not binary.is_file():
        raise RuntimeError(f"Moshi is not installed at {binary}")
    run([str(binary), "version"])
    probe = json.loads(run([str(binary), "probe", "--json"], capture=True, timeout=15).stdout)
    print("Daemon running:", probe.get("running") is True)
    print("Gateway at 127.0.0.1:24543:", probe.get("gateway") is True)
    print("Installed version:", probe.get("version", "unknown"))
    report = json.loads(run([str(binary), "doctor", "--json"], capture=True, timeout=30).stdout)
    checks = report.get("checks", [])
    ready = probe.get("running") is True and probe.get("gateway") is True
    for subject in ("daemon", "gateway"):
        ready = ready and any(c.get("group") == "Host" and c.get("subject") == subject and
                              c.get("status") == "ok" for c in checks)
    for target in TARGETS:
        current = any(c.get("group") == "Agents" and c.get("subject") == target and
                      c.get("status") == "ok" and c.get("detail") == "hooks current"
                      for c in checks)
        print(f"{target} hooks: {'current' if current else 'not current'}")
        ready = ready and current
    for check in checks:
        if check.get("group") == "Account" or check.get("status") not in ("ok", "info", None):
            print(f"Diagnostic: {check.get('group')}/{check.get('subject')}: {check.get('status')}")
    if require_ready and not ready:
        raise RuntimeError("daemon, default gateway, or requested hooks are not ready; run moshi-hook doctor yourself")


def brew_service_running(formula: str) -> bool:
    result = run(["brew", "services", "info", formula, "--json"], capture=True, echo=True,
                 check=False, timeout=30)
    text = (result.stdout or "").strip()
    if not text:
        raise RuntimeError(f"command failed ({result.returncode}): brew services info {formula} --json")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise RuntimeError("brew services info did not return JSON") from error
    if isinstance(payload, list):
        entries = [item for item in payload if isinstance(item, dict)]
    elif isinstance(payload, dict):
        nested = payload.get("services") if isinstance(payload.get("services"), list) else None
        if "running" in payload or "status" in payload:
            entries = [payload]
        elif nested is not None:
            entries = [item for item in nested if isinstance(item, dict)]
        else:
            entries = [payload]
    else:
        raise RuntimeError("brew services info returned an unexpected JSON shape")
    for entry in entries:
        if entry.get("running") is True:
            return True
        if str(entry.get("status", "")).lower() in {"started", "running"}:
            return True
    if result.returncode not in (0, 1):
        raise RuntimeError(f"command failed ({result.returncode}): brew services info {formula} --json")
    return False


def retire_custom_launch_agent() -> None:
    """Unload and delete only the pre-Homebrew launch agent, when it is present.

    Stops gui/<uid>/app.getmoshi.moshi-hook and removes that plist when its
    Label matches. Leaves Homebrew's homebrew.mxcl.moshi-hook.plist, Keychain
    items, ~/.config/moshi, and ~/.local/bin/moshi-hook in place.
    """
    unit = custom_launch_agent_plist()
    target = f"gui/{os.getuid()}/{LAUNCHD_LABEL}"
    loaded = run(["launchctl", "print", target], capture=True, echo=True, check=False)
    if loaded.returncode == 0:
        run(["launchctl", "bootout", target])
        print(f"Unloaded launch agent {target}. Pairing data and Keychain items were not removed.")
    if unit is not None:
        unit.unlink()
        print(f"Removed custom launch agent {unit}. Pairing data and Keychain items were not removed.")
    previous = local_binary()
    if previous.exists() or previous.is_symlink():
        print(f"Left {previous} in place. It is not the Homebrew service. "
              "Pairing data and Keychain items were not removed.")


def restart_service(platform: Platform) -> None:
    # Windows tasks WSL-Moshi-Proxy-* and WSL-Moshi-SSH-* do not run moshi-hook.
    binary = hook_binary(platform)
    if not binary.is_file():
        raise RuntimeError("install the binary with just moshi::install first")
    if platform is Platform.MACOS:
        # Refuse a missing Homebrew binary before stopping the only running agent.
        if custom_launch_agent_plist() is not None:
            backup(platform, upgrade=False)
        retire_custom_launch_agent()
        _, formula = brewfile_moshi()
        if brew_service_running(formula):
            run(["brew", "services", "restart", formula])
        else:
            run(["brew", "services", "start", formula])
        return
    unit = service_file(platform)
    if not unit.exists():
        run([str(binary), "service", "install"])
        return
    run(["systemctl", "--user", "enable", SYSTEMD_UNIT])
    run(["systemctl", "--user", "restart", SYSTEMD_UNIT])
    for state in ("is-enabled", "is-active"):
        run(["systemctl", "--user", state, "--quiet", SYSTEMD_UNIT], capture=True, timeout=10)


def wait_for_gateway(platform: Platform) -> None:
    # Gateway startup can lag the service manager's successful restart.
    binary = hook_binary(platform)
    for _ in range(15):
        probe = json.loads(run([str(binary), "probe", "--json"], capture=True, timeout=10).stdout)
        if probe.get("running") is True and probe.get("gateway") is True:
            return
        time.sleep(1)


def usage_setting_unsupported(returncode: int, detail: str) -> bool:
    text = detail.lower()
    if returncode == 2:
        return True
    markers = (
        "unknown setting", "unknown command", "unrecognized", "unexpected argument",
        "unexpected flag", "invalid setting", "invalid argument", "not a valid",
        "no such option", "does not support",
    )
    return any(marker in text for marker in markers)


def set_usage_collection_off(platform: Platform) -> None:
    # Writes usage_collection = false. Repeating it is the same value.
    # The running daemon keeps the old value until the service restart.
    command = [str(hook_binary(platform)), "set", "usage-collection", "off"]
    print("Run:", shlex.join(command), flush=True)
    result = run(command, capture=True, check=False)
    if result.returncode == 0:
        print("Usage collection is off. Usages rings stop updating from this host.")
        return
    detail = "\n".join(
        line.strip() for line in f"{result.stderr or ''}\n{result.stdout or ''}".splitlines()
        if line.strip())
    if usage_setting_unsupported(result.returncode, detail):
        print("Warning: this moshi-hook does not support `set usage-collection off`. "
              "Usage collection was left unchanged. Continuing to the service restart.",
              file=sys.stderr)
        return
    raise RuntimeError(f"command failed ({result.returncode}): {shlex.join(command)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=("preview", "upgrade", "hooks", "status", "restart", "set-usage-collection-off"),
        nargs="?", default="preview")
    parser.add_argument("--platform", choices=[p.value for p in Platform], help="preview another platform; never applies it")
    args = parser.parse_args()
    if args.platform and args.action != "preview":
        parser.error("--platform is allowed only with preview")
    platform = Platform(args.platform) if args.platform else detect_platform()
    if args.action == "preview":
        print("Preview only:", platform.value)
        print("Back up the native service file and Claude Code/Codex/Pi hook configuration privately.")
        if platform is Platform.WSL_ARCH:
            print("Back up ~/.local/bin/moshi-hook before replacing that upstream binary.")
        else:
            print("macOS uses the Homebrew formula. The Cellar binary is not copied into the backup.")
        if platform is Platform.MACOS:
            tap, formula = brewfile_moshi()
            print(f"brew tap {tap}")
            print(f"brew trust {tap}")
            print(f"brew install {formula} when that formula is not already installed")
            print(f"brew upgrade {formula}")
            print("No other Homebrew formulae are upgraded, and mosh is not installed by this recipe.")
            print(f"Unload launch agent {LAUNCHD_LABEL} when it is loaded, and remove "
                  f"~/Library/LaunchAgents/{LAUNCHD_LABEL}.plist when its Label matches.")
            print("Leave Homebrew's homebrew.mxcl.moshi-hook.plist, pairing data, Keychain items, "
                  "and ~/.local/bin/moshi-hook in place.")
            print(f"brew services start {formula} when the Homebrew service is stopped")
            print(f"brew services restart {formula} when it is already running")
        else:
            for command in package_commands(platform):
                print(shlex.join(command))
            print(f"Download and run {UPSTREAM_INSTALL_URL} (first-run and service startup skipped)")
            print("moshi-hook install --target claude,codex,pi (closed stdin; no automatic Codex server fix)")
            print(f"systemctl --user enable {SYSTEMD_UNIT}")
            print(f"systemctl --user restart {SYSTEMD_UNIT}")
            print("moshi-hook service install when that native service file is absent")
        if platform is Platform.MACOS:
            print("moshi-hook install --target claude,codex,pi (closed stdin; no automatic Codex server fix)")
        print("After the upgrade succeeds: moshi-hook set usage-collection off")
        print("If this moshi-hook has no usage-collection setting, warn and continue.")
        print("Then restart the service once. An unchanged binary still restarts; that recycle is harmless.")
        print("Re-enable with: moshi-hook set usage-collection on")
        print("On-demand upload remains: moshi-hook usage --sync")
        print("Verify daemon, default gateway, requested hooks; report other doctor warnings.")
        print("No pairing, agent reloads, unrelated service restarts, or Windows changes.")
        return
    if args.action == "status":
        status(platform, require_ready=False)
        return
    if args.action == "restart":
        preflight(platform, upgrade=False)
        restart_service(platform)
        wait_for_gateway(platform)
        status(platform, require_ready=True)
        print("Service restarted. Reload/restart the affected agents yourself when safe; "
              "their current sessions were not restarted.")
        return
    if args.action == "set-usage-collection-off":
        preflight(platform, upgrade=False)
        set_usage_collection_off(platform)
        return
    upgrade = args.action == "upgrade"
    preflight(platform, upgrade=upgrade)
    backup(platform, upgrade=upgrade)
    if upgrade:
        if platform is Platform.MACOS:
            upgrade_homebrew_moshi()
        else:
            for command in package_commands(platform):
                run(command)
            run_upstream_installer()
    install_hooks(platform)
    if upgrade:
        # Readiness is checked after the service restart, which is a separate
        # step. A stopped daemon must not block that restart.
        print("Upgrade applied. Usage collection is turned off next, then the service restarts once.")
        return
    status(platform, require_ready=False)
    print("Complete. Reload/restart the affected agents yourself when safe; their current sessions were not restarted.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"moshi maintenance: {error}", file=sys.stderr)
        raise SystemExit(1)
