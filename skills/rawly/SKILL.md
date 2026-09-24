---
name: rawly
description: >-
  Process local photos and videos with Rawly: D image processing, metadata cleanup, optional device profiles, and whole-folder batches. Use when the user asks to use Rawly, remove media metadata or AI provenance tags, apply a shooting profile, or process a media batch. Requires local files and a shell.
---

# Rawly

Use the bundled deterministic tool. Resolve paths relative to this `SKILL.md`,
not the current working directory. The runtime is `scripts/rawly.py`; Python is
`.venv/bin/python` on macOS/Linux or `.venv/Scripts/python.exe` on Windows.

## Run

1. Run `scripts/rawly.py doctor` using that interpreter. If its environment is
   missing, run `python3 scripts/bootstrap.py` (Windows: `py -3`). Install missing
   FFmpeg/ExifTool using [installation.md](references/installation.md). Package
   installation needs network access; processing itself is local.
2. Resolve the input files and a separate output folder from the user's request.
   Process a folder directly for a batch; add `--recursive` only for subfolders.
3. Run the tool once for the batch:

   ```text
   <python> <skill>/scripts/rawly.py process <file-or-folder> --output <folder>
   ```

4. Read the JSON result/report. Return output paths, succeeded/failed counts and
   the reason for any failure. Do not claim success for files marked `error`.

The default photo path is D, with a fixed seed of 8501 and a 24 MP memory limit.
It preserves framing and output dimensions, but changes fine detail and adds grain.
Videos use stream copying: audio/video are not re-encoded. Outputs never overwrite
existing files. A batch is sequential to bound memory. The local JSON report names
inputs and outputs; keep reports with the user's files, not in public issues.

## Optional shooting profile

Do not invent a camera, location or capture date. Apply a profile only when requested
or supplied by the user. Profiles are ordinary JSON files with no account or count limit.

```text
<python> <skill>/scripts/rawly.py presets devices --search iPhone
<python> <skill>/scripts/rawly.py presets cities --search Москва
<python> <skill>/scripts/rawly.py profile <profile.json> --device <id>
<python> <skill>/scripts/rawly.py profile <profile.json> --from-photo <reference.jpg>
<python> <skill>/scripts/rawly.py process <input> --output <folder> --profile <profile.json>
```

Read [profiles.md](references/profiles.md) for city, fixed time and UTC-offset options.
Read metadata without changing the file using `inspect <file>`.

## Interpret results

A removed provenance tag and a detector's pixel-based score are different observations.
The tool does not call a detector or upload media to a platform. Report only measured
results. If a score is requested, explain that an external test is separate and obtain
the user's authorization before uploading their files. Do not claim a file was captured
by the device merely because a profile was written. Do not regenerate, crop, denoise or
recompress results unless asked; these operations change the tested D recipe.
