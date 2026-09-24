"""Rawly command line: local processing, reusable JSON profiles and batch reports."""

import argparse
import asyncio
from datetime import datetime
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import uuid

PHOTO_EXT = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".heic",
    ".heif",
    ".avif",
    ".tif",
    ".tiff",
    ".bmp",
    ".gif",
}
MEDIA_EXT = {".mp4", ".mov", ".m4a"}


def write_json(path, data):
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".rawly-", dir=path.parent) as tmp:
        staged = Path(tmp) / "report.json"
        staged.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        os.link(staged, path)


def doctor():
    packages = {
        name: importlib.util.find_spec(name) is not None
        for name in ("PIL", "numpy", "cv2", "pillow_heif")
    }
    binaries = {name: shutil.which(name) for name in ("ffmpeg", "exiftool")}
    return {
        "ok": sys.version_info >= (3, 11)
        and all(packages.values())
        and all(binaries.values()),
        "python": sys.version.split()[0],
        "packages": packages,
        "binaries": binaries,
    }


def profile_data(config):
    from . import profiles

    if not isinstance(config, dict):
        raise ValueError("Profile must be a JSON object.")
    extra = set(config) - {"device", "city", "time", "datetime", "timezone"}
    if extra:
        raise ValueError("Unknown profile fields: " + ", ".join(sorted(extra)))
    device = config.get("device")
    if isinstance(device, str):
        if device not in profiles.DEVICES:
            raise ValueError("Unknown device ID. Run: rawly.py presets devices")
        device_json = None
        device_id = device
    elif isinstance(device, dict):
        device = dict(device)
        for key in ("make", "model", "software", "exif_version", "lens_model"):
            if not isinstance(device.get(key), str) or not 1 <= len(device[key]) <= 200:
                raise ValueError("Missing/invalid device field: " + key)
        device.setdefault("label", device["model"])
        if not isinstance(device["label"], str) or len(device["label"]) > 200:
            raise ValueError("Invalid device label.")
        for key in ("f_number", "focal_length", "focal_35mm"):
            value = device.get(key)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0 < value < 10000
            ):
                raise ValueError("Invalid device field: " + key)
        iso = device.get("iso_range")
        if (
            not isinstance(iso, list)
            or len(iso) != 2
            or any(type(v) is not int for v in iso)
            or not 1 <= iso[0] <= iso[1] <= 1_000_000
        ):
            raise ValueError("Invalid ISO range.")
        device_id = None
        device_json = json.dumps(device, ensure_ascii=False)
    else:
        raise ValueError("Choose a device ID or import a device from a photo.")
    city = config.get("city")
    if city is not None and (
        not isinstance(city, str) or city not in profiles.LOCATIONS
    ):
        raise ValueError("Unknown city ID.")
    mode = config.get("time", "current")
    if mode not in ("current", "random48", "fixed"):
        raise ValueError("Time must be current, random48 or fixed.")
    custom = config.get("datetime")
    if mode == "fixed":
        if not isinstance(custom, str):
            raise ValueError("Fixed time requires datetime: YYYY:MM:DD HH:MM:SS.")
        datetime.strptime(custom, "%Y:%m:%d %H:%M:%S")
    elif custom is not None:
        raise ValueError("datetime is only used with time=fixed.")
    zone = config.get("timezone")
    if zone is not None and (
        not isinstance(zone, str)
        or not re.fullmatch(r"[+-](?:0[0-9]|1[0-3]):[0-5][0-9]|[+-]14:00", zone)
    ):
        raise ValueError("Timezone must be a UTC offset, e.g. +03:00.")
    return {
        "device_id": device_id,
        "device_json": device_json,
        "loc_id": city,
        "loc_lat": None,
        "loc_lon": None,
        "loc_city": None,
        "loc_country": None,
        "loc_tz": None,
        "time_mode": {"current": "now", "fixed": "custom", "random48": "random48"}[
            mode
        ],
        "custom_time": custom,
        "timezone": zone,
    }


def load_profile(path):
    path = Path(path)
    if path.stat().st_size > 65536:
        raise ValueError("Profile JSON must be smaller than 64 KiB.")
    return profile_data(json.loads(path.read_text(encoding="utf-8")))


def plan_files(inputs, output, recursive=False):
    output = Path(output).resolve()
    jobs = []
    seen = set()
    targets = set()
    for raw in inputs:
        root = Path(raw).expanduser().resolve()
        if not root.exists():
            raise ValueError(f"Input does not exist: {root}")
        if root == output:
            raise ValueError("Output must be different from the input directory.")
        is_dir = root.is_dir()
        candidates = (
            sorted(root.rglob("*") if recursive else root.iterdir())
            if is_dir
            else [root]
        )
        for src in candidates:
            if is_dir and src.is_symlink():
                continue
            src = src.resolve()
            if src == output or output in src.parents:
                continue
            if not src.is_file():
                continue
            if src.suffix.lower() not in PHOTO_EXT | MEDIA_EXT:
                if not is_dir:
                    raise ValueError("Unsupported file: " + str(src))
                continue
            if src in seen:
                continue
            seen.add(src)
            relative = src.relative_to(root) if is_dir else Path(src.name)
            if is_dir and len(inputs) > 1:
                relative = Path(root.name) / relative
            suffix = ".png" if src.suffix.lower() in PHOTO_EXT else src.suffix
            dest = output / relative.parent / (relative.name + ".rawly" + suffix)
            if dest in targets:
                raise ValueError(
                    "Output name collision. Process the containing folders separately: "
                    + dest.name
                )
            targets.add(dest)
            jobs.append((src, dest))
    if not jobs:
        raise ValueError("No supported files found.")
    return jobs


async def process_one(src, dest, profile=None, *, seed=8501, max_megapixels=24):
    from . import media, profiles

    if dest.exists():
        raise ValueError("Output exists; skipped without overwriting.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".rawly-", dir=dest.parent) as tmp:
        staged = Path(tmp) / ("result" + dest.suffix)
        if src.suffix.lower() in PHOTO_EXT:
            if profile:
                pixels = Path(tmp) / "pixels.png"
                await media.clean(src, pixels, seed=seed, max_megapixels=max_megapixels)
                await profiles.mimic_image(pixels, staged, profile)
            else:
                await media.clean(src, staged, seed=seed, max_megapixels=max_megapixels)
        elif profile:
            await profiles.mimic_video(src, staged, profile)
        else:
            await media.clean(src, staged)
        # Publish only a complete file; an existing file or racing writer always wins.
        os.link(staged, dest)
    return dest


async def run(args):
    if args.command == "doctor":
        return doctor()
    from . import profiles, media
    import cv2

    cv2.setNumThreads(1)
    if args.command == "inspect":
        return {
            "file": str(args.input.resolve()),
            "metadata": await media.inspect(args.input),
        }
    if args.command == "presets":
        source = profiles.DEVICES if args.kind == "devices" else profiles.LOCATIONS
        records = [
            {
                "id": k,
                "name": v["label"]
                if args.kind == "devices"
                else f"{v['city']}, {v['country']}",
            }
            for k, v in source.items()
        ]
        return [
            r
            for r in records
            if not args.search
            or args.search.casefold() in json.dumps(r, ensure_ascii=False).casefold()
        ]
    if args.command == "profile":
        if args.from_photo:
            if args.from_photo.stat().st_size > 100 * 1024 * 1024:
                raise ValueError("Profile source is larger than 100 MiB.")
            device = await profiles.sniff_profile(args.from_photo.read_bytes())
            if not device:
                raise ValueError("No camera make/model found. Choose a preset instead.")
        else:
            device = args.device
        config = {"device": device, "city": args.city, "time": args.time}
        if args.datetime:
            config["datetime"] = args.datetime
        if args.timezone:
            config["timezone"] = args.timezone
        profile_data(config)
        write_json(args.output, config)
        return {"profile": str(args.output.resolve())}
    if not 0 < args.max_megapixels <= 300:
        raise ValueError("Megapixel limit must be between 0 and 300.")
    profile = load_profile(args.profile) if args.profile else None
    output = args.output.expanduser().resolve()
    jobs = plan_files(args.inputs, output, args.recursive)
    report = (
        args.report.expanduser().resolve()
        if args.report
        else output / f"rawly-report-{uuid.uuid4().hex[:12]}.json"
    )
    if report.exists() or report in {dest for _, dest in jobs}:
        raise ValueError("Report path already exists or conflicts with an output.")
    # Check dependencies once, before processing a batch.
    required = (
        ["ffmpeg"] if any(src.suffix.lower() in MEDIA_EXT for src, _ in jobs) else []
    )
    if profile:
        required.append("exiftool")
    missing = [name for name in required if not shutil.which(name)]
    if missing:
        raise ValueError("Install required tools: " + ", ".join(missing))
    result = {
        "version": "1.0.0",
        "seed": args.seed,
        "profile_applied": profile is not None,
        "files": [],
    }
    for index, (src, dest) in enumerate(jobs, 1):
        entry = {"input": str(src), "output": str(dest)}
        try:
            await process_one(
                src, dest, profile, seed=args.seed, max_megapixels=args.max_megapixels
            )
            entry.update(status="ok", bytes=dest.stat().st_size)
        except Exception as exc:
            entry.update(status="error", error=str(exc) or type(exc).__name__)
        result["files"].append(entry)
        print(f"[{index}/{len(jobs)}] {entry['status']}: {src.name}", file=sys.stderr)
    result["ok"] = all(row["status"] == "ok" for row in result["files"])
    result["report"] = str(report)
    write_json(report, result)
    return result


def parser():
    p = argparse.ArgumentParser(
        description="Local photo processing and media metadata cleanup for Codex and Claude Code."
    )
    p.add_argument("--version", action="version", version="rawly 1.0.0")
    commands = p.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Check Python packages and external tools.")
    inspect = commands.add_parser(
        "inspect", help="Read metadata; no pixel detector calls."
    )
    inspect.add_argument("input", type=Path)
    presets = commands.add_parser("presets", help="List bundled device/city templates.")
    presets.add_argument("kind", choices=["devices", "cities"])
    presets.add_argument("--search")
    profile = commands.add_parser("profile", help="Create a reusable JSON profile.")
    profile.add_argument("output", type=Path)
    source = profile.add_mutually_exclusive_group(required=True)
    source.add_argument("--device")
    source.add_argument("--from-photo", type=Path)
    profile.add_argument("--city")
    profile.add_argument(
        "--time", choices=["current", "random48", "fixed"], default="current"
    )
    profile.add_argument("--datetime")
    profile.add_argument("--timezone")
    process = commands.add_parser(
        "process",
        help="Process files or folders sequentially; originals stay untouched.",
    )
    process.add_argument("inputs", nargs="+")
    process.add_argument("--output", required=True, type=Path)
    process.add_argument("--profile", type=Path)
    process.add_argument("--recursive", action="store_true")
    process.add_argument("--seed", type=int, default=8501)
    process.add_argument("--max-megapixels", type=float, default=24)
    process.add_argument("--report", type=Path)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        result = asyncio.run(run(args))
    except KeyboardInterrupt:
        print(
            "Interrupted. Completed outputs are kept; originals are unchanged.",
            file=sys.stderr,
        )
        return 130
    except ImportError as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": f"Missing dependency: {exc}. Run scripts/bootstrap.py.",
                }
            )
        )
        return 2
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not isinstance(result, dict) or result.get("ok", True) else 1
