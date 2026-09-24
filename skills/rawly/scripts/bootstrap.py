#!/usr/bin/env python3
"""Install Python dependencies into this skill's own virtual environment."""

from pathlib import Path
import os
import subprocess
import sys
import venv


def main():
    if sys.version_info < (3, 11):
        raise SystemExit("Rawly needs Python 3.11 or newer.")
    root = Path(__file__).resolve().parents[1]
    env = root / ".venv"
    if env.is_symlink():
        raise SystemExit("Refusing a symlinked virtual environment.")
    if not env.exists():
        venv.EnvBuilder(with_pip=True).create(env)
    python = env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-r",
            str(root / "requirements.txt"),
        ],
        check=True,
    )
    print("Ready:", python)
    print("Next:", python, root / "scripts/rawly.py", "doctor")


if __name__ == "__main__":
    main()
