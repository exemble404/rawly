# Installation

Python 3.11+ and a shell are required. Python packages: Pillow, NumPy, OpenCV and
pillow-heif. FFmpeg handles video; ExifTool reads and writes metadata.

macOS:
```bash
brew install python ffmpeg exiftool
```
Ubuntu/Debian:
```bash
sudo apt-get update
sudo apt-get install python3 python3-venv ffmpeg libimage-exiftool-perl
```

The repository installer copies a self-contained skill and creates its virtual environment:
```bash
python3 install.py --host codex
python3 install.py --host claude
# Or both:
python3 install.py --host both
```

Codex user path: `~/.agents/skills/rawly`.
Claude Code user path: `~/.claude/skills/rawly`.
It does not edit agent settings, register hooks, or start a background service.
Restart the agent session after installation.

If a generic skill installer copied this skill without dependencies, run
`python3 <skill>/scripts/bootstrap.py`, then use `<skill>/.venv/bin/python`.
On Windows the interpreter is `<skill>/.venv/Scripts/python.exe`; install Python,
FFmpeg and ExifTool and make the executables available on PATH. Native Windows media
processing is not yet validated; macOS and Linux are the primary targets.

Uninstall from the source checkout:
```bash
python3 install.py --host both --uninstall
```

Sources for native discovery: [Codex](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills)
and [Claude Code](https://code.claude.com/docs/en/skills#where-skills-live).
