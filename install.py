#!/usr/bin/env python3
"""Install or remove only Rawly's self-contained skill folders. Python stdlib only."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "skills/rawly"
MARKER = ".rawly-install.json"


def targets(home, host):
    selected = ("codex", "claude") if host == "both" else (host,)
    return [
        (name, home / (".agents" if name == "codex" else ".claude") / "skills/rawly")
        for name in selected
    ]


def install(target, skip_deps=False):
    if target.is_symlink():
        raise ValueError(f"Refusing existing symlink: {target}")
    marker = target / MARKER
    if target.exists() and not marker.is_file():
        raise ValueError(
            f"An unrelated skill already exists: {target}. Nothing was overwritten."
        )
    if target.exists() and json.loads(marker.read_text()).get("project") != "rawly":
        raise ValueError(f"Unknown installation at {target}")
    if target.exists():
        for child in target.rglob("*"):
            if ".venv" not in child.relative_to(target).parts and child.is_symlink():
                raise ValueError(f"Refusing symlink inside installed skill: {child}")
    target.parent.mkdir(parents=True, exist_ok=True)
    # Stage a complete skill before replacing files. Python dependencies are isolated.
    with tempfile.TemporaryDirectory(
        prefix=".rawly-install-", dir=target.parent
    ) as tmp:
        stage = Path(tmp) / "rawly"
        shutil.copytree(
            SOURCE,
            stage,
            ignore=shutil.ignore_patterns(".venv", "__pycache__", "*.pyc", MARKER),
        )
        files = [str(p.relative_to(stage)) for p in stage.rglob("*") if p.is_file()]
        if target.exists():
            old = json.loads(marker.read_text()).get("files", [])
            # Updates preserve custom files and .venv. Remove only old tracked source files.
            for name in old:
                path = target / name
                if ".." in Path(name).parts or Path(name).is_absolute():
                    raise ValueError("Invalid install manifest.")
                if name not in files and path.is_file():
                    path.unlink()
            shutil.copytree(stage, target, dirs_exist_ok=True)
        else:
            stage.rename(target)
        marker.write_text(
            json.dumps({"project": "rawly", "version": "1.0.0", "files": files}) + "\n"
        )
    if not skip_deps:
        subprocess.run(
            [sys.executable, str(target / "scripts/bootstrap.py")], check=True
        )
    return target


def uninstall(target):
    marker = target / MARKER
    if target.is_symlink() or not marker.is_file():
        raise ValueError(f"Not an installer-owned Rawly skill: {target}")
    data = json.loads(marker.read_text())
    if data.get("project") != "rawly":
        raise ValueError("Unknown installation.")
    for name in data["files"]:
        path = Path(name)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Invalid install manifest.")
        if not (target / path).parent.resolve().is_relative_to(target.resolve()):
            raise ValueError("Install path escapes the skill folder.")
    for name in data["files"]:
        (target / name).unlink(missing_ok=True)
    env = target / ".venv"
    if env.is_symlink():
        env.unlink()
    elif env.exists():
        shutil.rmtree(env)
    marker.unlink()
    for path in sorted(target.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if path.is_dir() and not path.is_symlink():
            try:
                path.rmdir()
            except OSError:
                pass
    try:
        target.rmdir()
    except OSError:
        print("Kept custom files:", target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", choices=["codex", "claude", "both"], default="both")
    parser.add_argument(
        "--home",
        type=Path,
        default=Path.home(),
        help="Home directory to install into (also useful for isolated tests).",
    )
    parser.add_argument(
        "--skip-deps",
        action="store_true",
        help="Copy the skill only; bootstrap its .venv later.",
    )
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args()
    try:
        for host, target in targets(args.home.expanduser().resolve(), args.host):
            if args.uninstall:
                uninstall(target)
            else:
                install(target, args.skip_deps)
            print(f"{host}: {'removed' if args.uninstall else 'installed'} {target}")
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.exit(1, str(exc) + "\n")
    if not args.uninstall:
        print("Restart your agent session. Codex: $rawly | Claude Code: /rawly")


if __name__ == "__main__":
    main()
