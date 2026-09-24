"""Замена метаданных фото без перекодирования; видео через ffmpeg."""

import asyncio
import json
import os
import random
import shutil
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path


PRESETS = Path(__file__).parent / "presets"
DEVICES = {}
LOCATIONS = {}
for _d in json.loads((PRESETS / "devices.json").read_text("utf-8"))["devices"]:
    DEVICES[_d["id"]] = _d
for _c in json.loads((PRESETS / "locations.json").read_text("utf-8"))["cities"]:
    LOCATIONS[_c["id"]] = _c

EXIFTOOL = shutil.which("exiftool") or "exiftool"
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"


class CleanError(Exception):
    pass


async def _run(*args: str) -> tuple[int, str]:
    p = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    try:
        out, _ = await asyncio.wait_for(p.communicate(), timeout=180)
        return p.returncode, out.decode(errors="replace")
    except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
        if p.returncode is None:
            p.kill()
        await p.communicate()
        if isinstance(exc, asyncio.CancelledError):
            raise
        return 124, "Media tool exceeded the 180-second timeout."


# --- генераторы правдоподобных величин ----------------------------------------


def _dms(deg: float) -> str:
    deg = abs(deg)
    d = int(deg)
    m = int((deg - d) * 60)
    s = (deg - d - m / 60) * 3600
    return f"{d} deg {m}' {s:.2f}\""


def _exif_time(dt: datetime) -> str:
    return dt.strftime("%Y:%m:%d %H:%M:%S")


def _pick_time(mode: str, custom: str | None) -> datetime:
    """now — с ±5 c, чтобы не было «ровного» времени; random48 — за последние двое суток."""
    if mode == "custom" and custom:
        return datetime.strptime(custom, "%Y:%m:%d %H:%M:%S")
    now = datetime.now()
    if mode == "random48":
        return now - timedelta(seconds=random.uniform(0, 48 * 3600))
    return now - timedelta(seconds=random.randint(0, 5))


def _tz_now() -> str:
    """Local UTC offset used when no profile city or offset is selected."""
    off = int(datetime.now().astimezone().utcoffset().total_seconds())
    sign = "+" if off >= 0 else "-"
    return f"{sign}{abs(off) // 3600:02d}:{abs(off) % 3600 // 60:02d}"


def _shot_time(u) -> tuple[datetime, str]:
    """(момент съёмки, tz-пояс) с учётом локации юзера."""
    loc = _user_loc(u)
    tz = u.get("timezone") or (loc["tz_offset"] if loc else _tz_now())
    if u["time_mode"] == "custom" and u["custom_time"]:
        return _pick_time("custom", u["custom_time"]), tz
    sign = -1 if tz.startswith("-") else 1
    hours, minutes = map(int, tz.lstrip("+-").split(":"))
    zone = timezone(sign * timedelta(hours=hours, minutes=minutes))
    when = datetime.now(zone).replace(tzinfo=None)
    seconds = (
        random.uniform(0, 48 * 3600)
        if u["time_mode"] == "random48"
        else random.randint(0, 5)
    )
    return when - timedelta(seconds=seconds), tz


def _user_loc(u):
    """Локация юзера: пресет-город или своя точка (город текстом / геопин)."""
    if u["loc_id"] and u["loc_id"] in LOCATIONS:
        return LOCATIONS[u["loc_id"]]
    if u["loc_lat"] is not None and u["loc_lon"] is not None:
        return {
            "city": u["loc_city"] or "точка",
            "country": u["loc_country"] or "",
            "lat": u["loc_lat"],
            "lon": u["loc_lon"],
            "tz_offset": u["loc_tz"] or _tz_by_lon(u["loc_lon"]),
        }
    return None


def _tz_by_lon(lon: float) -> str:
    off = round(lon / 15)
    sign = "+" if off >= 0 else "-"
    return f"{sign}{abs(off):02d}:00"


def _user_device(u):
    """Устройство юзера: снятый со своего фото профиль или пресет."""
    if u["device_json"]:
        try:
            return json.loads(u["device_json"])
        except json.JSONDecodeError:
            pass
    if u["device_id"] and u["device_id"] in DEVICES:
        return DEVICES[u["device_id"]]
    return None


def location_label(u) -> str:
    l = _user_loc(u)
    if not l:
        return "не выбрана"
    return f"{l['city']}, {l['country']}" if l.get("country") else l["city"]


# --- метаданные ---------------------------------------------------------------


def _exif_args(device: dict, when: datetime, tz: str, loc: dict | None) -> list[str]:
    make = device["make"]
    model = device["model"]
    iso = random.randint(device["iso_range"][0], device["iso_range"][1])
    exp = random.choice([60, 80, 100, 120, 125, 160, 200, 250])
    f = device["f_number"]
    args = [
        "-overwrite_original",
        f"-Make={make}",
        f"-Model={model}",
        f"-Software={device['software']}",
        f"-HostComputer={model}",
        f"-ExifVersion={device['exif_version']}",
        "-FlashpixVersion=0100",
        f"-DateTimeOriginal={_exif_time(when)}",
        f"-CreateDate={_exif_time(when)}",
        f"-ModifyDate={_exif_time(when)}",
        f"-OffsetTimeOriginal={tz}",
        f"-OffsetTime={tz}",
        f"-SubSecTimeOriginal={random.randint(100, 999):03d}",
        f"-SubSecTime={random.randint(100, 999):03d}",
        f"-ISO={iso}",
        f"-ExposureTime=1/{exp}",
        f"-FNumber={f}",
        f"-ApertureValue={f}",
        f"-ShutterSpeedValue=1/{exp}",
        f"-BrightnessValue={random.uniform(4.5, 9.0):.2f}",
        "-ExposureBiasValue=0",
        f"-MaxApertureValue={f}",
        "-MeteringMode=Pattern",
        "-WhiteBalance=Auto",
        "-Flash=16",
        f"-FocalLength={device['focal_length']}",
        f"-FocalLengthIn35mmFormat={device['focal_35mm']}",
        f"-LensMake={make}",
        f"-LensModel={device['lens_model']}",
        f"-LensSpecification={device['focal_length']}-{device['focal_length']}/{f}-{f}",
        "-SensingMethod=One-chip color area sensor",
        f"-ColorSpace={'65535' if make == 'Apple' else '1'}",
        f"-PhotographicSensitivity={iso}",
        "-SensitivityType=Standard Output Sensitivity",
        f"-RecommendedExposureIndex={iso}",
        "-CustomRendered=Normal process",
        "-DigitalZoomRatio=1",
        "-SceneCaptureType=Standard",
        "-SceneType=Directly photographed",
        "-ExposureMode=Auto",
        "-ExposureProgram=Program AE",
        "-Orientation=Horizontal (normal)",
        "-XResolution=72",
        "-YResolution=72",
        "-ResolutionUnit=inches",
        "-YCbCrPositioning=Centered",
    ]
    if make == "Apple":
        args += [
            f"-ContentIdentifier={str(uuid.uuid4()).upper()}",
            "-AppleIRCamera=48",
            "-HDRImageType=1",
        ]
    if loc:
        sign = -1 if tz.startswith("-") else 1
        hours, minutes = map(int, tz.lstrip("+-").split(":"))
        utc = when - sign * timedelta(hours=hours, minutes=minutes)
        lat, lon = loc["lat"], loc["lon"]
        args += [
            f"-GPSLatitude={_dms(lat)}",
            f"-GPSLatitudeRef={'North' if lat >= 0 else 'South'}",
            f"-GPSLongitude={_dms(lon)}",
            f"-GPSLongitudeRef={'East' if lon >= 0 else 'West'}",
            f"-GPSAltitude={random.uniform(20, 350):.1f}",
            "-GPSAltitudeRef=Above Sea Level",
            f"-GPSImgDirection={random.uniform(0, 360):.1f}",
            "-GPSImgDirectionRef=True North",
            f"-GPSHPositioningError={random.uniform(3, 15):.1f}",
            f"-GPSSpeed={random.uniform(0, 0.5):.2f}",
            "-GPSSpeedRef=km/h",
            f"-GPSTimeStamp={utc.strftime('%H:%M:%S')}",
            f"-GPSDateStamp={utc.strftime('%Y:%m:%d')}",
            "-GPSVersionID=2.3.0.0",
        ]
    return args


async def mimic_image(src: Path, dst: Path, u) -> dict:
    """Копия в исходном формате: заменить метаданные, не декодируя пиксели."""
    src, dst = Path(src), Path(dst)
    if src.resolve() == dst.resolve() or dst.exists():
        raise CleanError("Output already exists; original was not changed.")
    if src.suffix.lower() != dst.suffix.lower():
        raise CleanError(
            "Metadata writing requires matching source and output formats."
        )
    device = _user_device(u)
    if not device:
        raise CleanError("No device selected.")
    when, tz = _shot_time(u)
    loc = _user_loc(u)
    try:
        with tempfile.TemporaryDirectory(prefix=".rawly-meta-", dir=dst.parent) as tmp:
            staged = Path(tmp) / ("image" + src.suffix)
            await asyncio.to_thread(shutil.copyfile, src, staged)
            # Поворот и цветовой профиль нужны для прежнего отображения.
            # Их берём из исходника, а не из пресета телефона.
            args = [
                arg
                for arg in _exif_args(device, when, tz, loc)
                if not arg.startswith(
                    (
                        "-Orientation=",
                        "-ColorSpace=",
                        "-XResolution=",
                        "-YResolution=",
                        "-ResolutionUnit=",
                        "-YCbCrPositioning=",
                    )
                )
            ]
            code, out = await _run(
                EXIFTOOL,
                "-all=",
                *args,
                "-tagsFromFile",
                str(src),
                "-ICC_Profile",
                "-EXIF:Orientation",
                "-XMP-tiff:Orientation",
                "-EXIF:ColorSpace",
                "-PNG:Gamma",
                "-PNG:SRGBRendering",
                "-EXIF:XResolution",
                "-EXIF:YResolution",
                "-EXIF:ResolutionUnit",
                str(staged),
            )
            if code != 0:
                raise CleanError(out.strip()[-300:] or "exiftool")
            # Некоторые форматы читаются, но не поддерживают запись EXIF.
            code, out = await _run(
                EXIFTOOL, "-j", "-EXIF:Make", "-EXIF:Model", str(staged)
            )
            tags = json.loads(out)[0] if code == 0 else {}
            if (
                tags.get("Make") != device["make"]
                or tags.get("Model") != device["model"]
            ):
                raise CleanError(
                    "This format does not support profile writing without conversion."
                )
            os.link(staged, dst)
    except (OSError, ValueError, IndexError) as exc:
        raise CleanError(str(exc)) from exc
    return {
        "device": device["label"],
        "city": location_label(u),
        "when": _exif_time(when) + tz,
        "apple": device["make"] == "Apple",
    }


# --- видео --------------------------------------------------------------------


async def mimic_video(src: Path, dst: Path, u) -> dict:
    device = _user_device(u)
    if not device:
        raise CleanError("No device selected.")
    when, tz = _shot_time(u)
    loc = _user_loc(u)
    if src.suffix.lower() not in {".mp4", ".mov", ".m4a"}:
        raise CleanError(
            "Profile writing without re-encoding supports MP4, MOV and M4A. "
            "Unsupported media container."
        )
    if src.suffix.lower() != dst.suffix.lower():
        raise CleanError("Source and output media formats must match.")
    from . import media

    try:
        await media.clean(src, dst)
    except media.CleanError as exc:
        raise CleanError(str(exc)) from exc
    # Метаданные в Apple-стиле: iPhone пишет их в QuickTime Keys
    # (com.apple.quicktime.*), а не в XMP — инспекторы читают Keys.
    meta = [
        "-overwrite_original",
        # Keys — то, что показывает «снято на iPhone»: модель, софт, GPS, время
        f"-Keys:Make={device['make']}",
        f"-Keys:Model={device['model']}",
        f"-Keys:Software={device['software']}",
        f"-Keys:CreationDate={_exif_time(when)}{tz}",
        # UserData — дубль make/model, его тоже читают старые инспекторы
        f"-UserData:Make={device['make']}",
        f"-UserData:Model={device['model']}",
        # структурные даты QuickTime: без них время «висит» в 1970-м
        f"-QuickTime:MediaCreateDate={_exif_time(when)}{tz}",
        f"-QuickTime:TrackCreateDate={_exif_time(when)}{tz}",
    ]
    if loc:
        # ISO 6709 (+49.9+073.1+150.5/) — единственный формат GPS для Keys;
        # «lat,lon» и отдельные GPSLatitude/Altitude exiftool уводит в XMP,
        # а Keys:GPSAltitude вовсе не существует как writable-тег
        iso = (
            f"{'+' if loc['lat'] >= 0 else '-'}{abs(loc['lat']):.6f}"
            f"{'+' if loc['lon'] >= 0 else '-'}{abs(loc['lon']):06.6f}"
            f"+{random.uniform(20, 350):.1f}/"
        )
        meta += [
            f"-Keys:GPSCoordinates={iso}",
        ]
    code, out = await _run(EXIFTOOL, *meta, str(dst))
    if code != 0:
        raise CleanError(out.strip()[-300:] or "exiftool video")
    return {
        "device": device["label"],
        "city": location_label(u),
        "when": _exif_time(when) + tz,
        "apple": device["make"] == "Apple",
    }


# --- профиль со своего фото ------------------------------------------------------


async def sniff_profile(data: bytes) -> dict | None:
    """EXIF исходного фото → профиль устройства. None — данных камеры нет."""
    with tempfile.NamedTemporaryFile(delete=False) as tf:
        tf.write(data)
        p = Path(tf.name)
    try:
        code, out = await _run(
            EXIFTOOL,
            "-j",
            "-Make",
            "-Model",
            "-Software",
            "-ExifVersion",
            "-LensModel",
            "-FNumber",
            "-FocalLength",
            "-FocalLengthIn35mmFormat",
            "-ISO",
            str(p),
        )
        if code != 0:
            return None
        try:
            tags = json.loads(out)[0]
        except (json.JSONDecodeError, IndexError):
            return None
    finally:
        p.unlink(missing_ok=True)
    make = (tags.get("Make") or "").strip()
    model = (tags.get("Model") or "").strip()
    if not make or not model:
        return None

    def num(v, default):
        try:
            return float(str(v).split()[0].replace(",", "."))
        except (ValueError, IndexError):
            return default

    iso = int(num(tags.get("ISO"), 125)) or 125
    apple = make.lower() == "apple"
    return {
        "id": "custom",
        "label": model if apple else f"{make} {model}",
        "make": make,
        "model": model,
        "software": (tags.get("Software") or "").strip() or "1.0",
        "exif_version": (tags.get("ExifVersion") or "").strip() or "0232",
        "lens_model": (tags.get("LensModel") or "").strip() or f"{model} camera",
        "f_number": round(num(tags.get("FNumber"), 1.78), 2),
        "focal_length": round(num(tags.get("FocalLength"), 6.86), 2),
        "focal_35mm": int(num(tags.get("FocalLengthIn35mmFormat"), 0)) or 24,
        "iso_range": [max(40, int(iso * 0.4)), max(iso * 2, 400)],
        "color_space": 65535 if apple else 1,
        "jpeg_quality": 92,
        "mpf": apple,
        "video": {"codec": "hvc1" if apple else "avc1"},
    }
