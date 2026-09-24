<div align="center">

<img src="assets/rawly-hero.svg" width="100%" alt="Rawly — local media processing for Codex and Claude Code">

<h3>Clean metadata · Process images · Keep control</h3>

<p><strong>Read this in other languages</strong><br>
<a href="README.md">🇺🇸 English</a> · <a href="README.ru.md">🇷🇺 Русский</a></p>

<p>
<a href="LICENSE"><img alt="MIT license" src="https://img.shields.io/badge/license-MIT-67CEB7?style=flat-square"></a>
<img alt="Python 3.11 or newer" src="https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&amp;logo=python&amp;logoColor=white">
<img alt="Codex and Claude Code" src="https://img.shields.io/badge/skills-Codex_%C2%B7_Claude_Code-2279FF?style=flat-square">
<img alt="Local processing" src="https://img.shields.io/badge/processing-local-2DBFD4?style=flat-square">
<a href="https://github.com/exemble404/rawly/actions/workflows/ci.yml"><img alt="Tests" src="https://github.com/exemble404/rawly/actions/workflows/ci.yml/badge.svg"></a>
</p>

<p><strong>Your media. Your machine. Your workflow.</strong><br>
A local photo and video toolkit, packaged as a skill for Codex and Claude Code.<br>
Process a single file or a whole folder. Keep every original.</p>

<p><a href="#capabilities">Capabilities</a> · <a href="#how-it-works">How it works</a> · <a href="#install">Install</a> · <a href="#use-it">Use it</a> · <a href="#architecture">Architecture</a></p>
</div>

---

## Why Rawly exists

Media files carry more than an image: camera fields, locations, software tags and
provenance metadata. Rawly puts the processing workflow on your own machine, with
one reusable skill and an inspectable Python implementation.

The photo pipeline grew out of experiments with AI-image detectors. The open-source
version includes the accepted **D** recipe, metadata cleanup and optional shooting
profiles. There is no hosted backend, account, subscription, model download or
external detector call. Agent/model access is provided by your own Codex or Claude setup.

## Capabilities

| Capability | What it does | Implementation |
|---|---|---|
| Full-frame photo processing | D recipe; preserves framing, dimensions and transparency | Pillow + NumPy + OpenCV |
| Video cleanup | Removes container metadata with audio/video stream copying | FFmpeg |
| Shooting profiles | Adds an optional device, location and capture time | ExifTool + reusable JSON |
| Profile from a photo | Reuses camera fields without copying its GPS or capture date | ExifTool |
| Folder batches | Sequential processing, per-file failures and a JSON report | Python stdlib |
| Original protection | Writes separate outputs; refuses to overwrite existing files | Staging + atomic publication |
| Metadata inspection | Shows personal/provenance metadata without editing the file | ExifTool |
| Native agent skills | `$rawly` in Codex, `/rawly` in Claude Code | One self-contained `SKILL.md` |

## How it works

```text
Files / folder
      │
      ├── Photo ──► orientation + sRGB ──► D processing ──► fresh PNG
      │                                                        │
      └── Video ──► metadata cleanup + stream copy ─────────────┤
                                                               ▼
                                                  optional shooting profile
                                                               │
                                                               ▼
                                                   output folder + report
```

**Photos:** Lanczos down to 50% of each dimension, back to the original dimensions,
then correlated monochrome grain with adaptive strength 4–7. Seed: `8501`.
The image keeps its dimensions; fine detail changes and grain is visible.

**Video:** the compressed audio/video streams are copied. Container metadata,
chapters and data streams are removed. The visual content is not regenerated.

## Install

### 1. System tools

Python **3.11+**, FFmpeg and ExifTool are required for the complete toolkit.

<details>
<summary><strong>macOS</strong></summary>

```bash
brew install python ffmpeg exiftool
```
</details>

<details>
<summary><strong>Ubuntu / Debian</strong></summary>

```bash
sudo apt-get update
sudo apt-get install python3 python3-venv ffmpeg libimage-exiftool-perl
```
</details>

### 2. Install the skill

```bash
git clone https://github.com/exemble404/rawly.git
cd rawly
python3 install.py --host both
```

Choose `--host codex` or `--host claude` to install only one. The installer creates
an isolated Python environment for each installed skill. It does not edit agent
settings or register background hooks. Updates use the same command.

| Host | Installed skill | Invocation |
|---|---|---|
| Codex | `~/.agents/skills/rawly` | `$rawly` |
| Claude Code | `~/.claude/skills/rawly` | `/rawly` |

Restart the agent session after installation. A generic skill installer can also
install [`skills/rawly`](skills/rawly); the skill explains how to bootstrap its dependencies.

## Use it

In **Codex**:

```text
$rawly Process the photos in ./input into ./output. Keep the originals.
```

In **Claude Code**:

```text
/rawly Process ./input into ./output using my ./studio.json profile.
```

Or tell either agent what you want in your own language. Profiles are optional;
without one, Rawly does not invent camera or location tags.

### Standalone CLI

No agent is required:

```bash
python3 skills/rawly/scripts/bootstrap.py
skills/rawly/.venv/bin/python skills/rawly/scripts/rawly.py doctor
skills/rawly/.venv/bin/python skills/rawly/scripts/rawly.py process ./input --output ./output
```

Add `--recursive` for subfolders. Files are processed one at a time; there is no
Telegram file-size cap or paid tier. The default photo limit is **24 megapixels**
to bound RAM use. Output names retain the original filename, for example
`photo.jpg.rawly.png`. Existing output files are skipped with an error in the report.

### Shooting profiles

```bash
skills/rawly/.venv/bin/python skills/rawly/scripts/rawly.py presets devices --search iPhone
skills/rawly/.venv/bin/python skills/rawly/scripts/rawly.py profile studio.json --device apple_0
skills/rawly/.venv/bin/python skills/rawly/scripts/rawly.py process ./input --output ./output --profile studio.json
```

Profiles are ordinary JSON files, with no count limit. See the
[profile reference](skills/rawly/references/profiles.md) for cities, explicit time,
UTC offsets and importing device fields from your own reference photo.

## What the results mean

Removing metadata and changing a detector's pixel-based score are separate operations.
Rawly does not measure detector scores, upload files or certify camera provenance.
Historical user tests reported 0–1% for two photos and 99% for five other illustrations
with D; those observations are not a general accuracy benchmark. A video test on one
platform is not evidence for every platform or upload.

Supported inputs: static JPEG, PNG, WebP, HEIC/HEIF, AVIF, TIFF, BMP and GIF; media
containers MP4, MOV and M4A. Animated/multipage images are rejected. Video metadata
cleanup is not a forensic erasure of information embedded in the compressed streams.
macOS and Linux are the primary targets; native Windows media processing is unvalidated.

## Architecture

```text
rawly/
├── skills/rawly/
│   ├── SKILL.md                  # shared Codex / Claude instructions
│   ├── agents/openai.yaml        # Codex display metadata
│   ├── scripts/
│   │   ├── rawly.py              # CLI entry point
│   │   ├── bootstrap.py          # isolated dependency installation
│   │   └── rawly_core/           # D, metadata, profiles, batch orchestration
│   ├── references/               # installation and profile details
│   └── requirements.txt          # four pinned Python dependencies
├── assets/rawly-hero.svg          # repository artwork
├── tests/                        # synthetic media and integration tests
├── install.py                    # native skill installation / removal
└── .github/workflows/ci.yml       # automated checks
```

The installed skill carries its own runtime. No server, database, bot token or
external service is required. Processing code is shared by both agents and the CLI.

## Development

```bash
python3 skills/rawly/scripts/bootstrap.py
skills/rawly/.venv/bin/python -m unittest discover -s tests -v
```

Tests generate their own media. Private photos, keys, logs and old bot data are not
part of this repository. Read [CONTRIBUTING.md](CONTRIBUTING.md) before changing the D recipe.

## Uninstall

```bash
python3 install.py --host both --uninstall
```

This removes installer-owned skills and their environments. Output media and profiles
outside the skill folders are left in place.

## License & credits

[MIT](LICENSE). Built with [Pillow](https://python-pillow.org/),
[NumPy](https://numpy.org/), [OpenCV](https://opencv.org/),
[FFmpeg](https://ffmpeg.org/) and [ExifTool](https://exiftool.org/).
README presentation inspired by [Z.A.E.B.A.L.](https://github.com/howdeploy/Z.A.E.B.A.L).
Rawly's artwork and implementation are maintained in this repository.
