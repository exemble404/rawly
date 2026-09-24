"""Local media I/O. External tools run with argument arrays, never a shell."""

import asyncio
import json
from pathlib import Path
from .images import IMAGE_EXT, process_image

LEAKY = {
    "Make": "Производитель",
    "Model": "Модель",
    "LensModel": "Объектив",
    "Software": "Софт",
    "CreatorTool": "Программа",
    "Creator": "Автор",
    "Artist": "Автор (EXIF)",
    "OwnerName": "Владелец",
    "SerialNumber": "Серийный номер",
    "DateTimeOriginal": "Снято",
    "CreateDate": "Создано",
    "GPSPosition": "Координаты",
    "GPSLatitude": "Широта",
    "GPSLongitude": "Долгота",
    "DigitalSourceType": "Источник",
    "Comment": "Комментарий",
    "UserComment": "Комментарий (EXIF)",
    "Description": "Описание",
}

AI_SOURCE_TYPES = {
    "trainedAlgorithmicMedia": "В файле указана генерация ИИ",
    "compositeWithTrainedAlgorithmicMedia": "В файле указано редактирование с ИИ",
}


def metadata_findings(tags: dict) -> dict[str, str]:
    """Readable claims from tags, not signature validation or pixel detection."""
    found = {}
    for key, value in tags.items():
        name = key.rsplit(":", 1)[-1]
        if name in LEAKY and value not in (None, ""):
            found[LEAKY[name]] = str(value)[:80]
    c2pa = any(
        "c2pa" in key.lower()
        or (key.rsplit(":", 1)[-1] == "JUMDLabel" and "c2pa" in str(value).lower())
        for key, value in tags.items()
    )
    if c2pa:
        found["Данные происхождения"] = "Встроены Content Credentials (C2PA)"
    claims = []
    for key, value in tags.items():
        if key.rsplit(":", 1)[-1].lower() != "aigc":
            continue
        found["AI-метаданные AIGC"] = "В файле есть метка AIGC"
        try:
            label = (json.loads(value) if isinstance(value, str) else value).get(
                "Label"
            )
            if str(label) == "1":
                claims.append("В файле указана генерация ИИ (AIGC Label=1)")
        except (ValueError, TypeError, AttributeError):
            pass
    for key, value in tags.items():
        if key.rsplit(":", 1)[-1] not in (
            "DigitalSourceType",
            "ActionsDigitalSourceType",
        ):
            continue
        for source in value if isinstance(value, list) else [value]:
            code = str(source).rstrip("/").rsplit("/", 1)[-1]
            if code in AI_SOURCE_TYPES and AI_SOURCE_TYPES[code] not in claims:
                claims.append(AI_SOURCE_TYPES[code])
    if claims:
        found["AI в метаданных"] = "; ".join(claims)
    return found


class CleanError(Exception):
    pass


async def _run(*args):
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(), 180)
        return process.returncode, output.decode(errors="replace")
    except (asyncio.TimeoutError, asyncio.CancelledError):
        if process.returncode is None:
            process.kill()
        await process.communicate()
        raise


async def clean(src, dst, *, max_megapixels=24, seed=8501):
    src, dst = Path(src), Path(dst)
    if src.suffix.lower() in IMAGE_EXT:
        await asyncio.to_thread(
            process_image, src, dst, max_megapixels=max_megapixels, seed=seed
        )
        return
    if src.resolve() == dst.resolve() or dst.exists():
        raise CleanError("Output already exists; original was not changed.")
    code, output = await _run(
        "ffmpeg",
        "-n",
        "-loglevel",
        "error",
        "-i",
        str(src),
        "-map",
        "0",
        "-c",
        "copy",
        "-dn",
        "-ignore_unknown",
        "-map_metadata",
        "-1",
        "-map_metadata:s",
        "-1",
        "-map_chapters",
        "-1",
        "-fflags",
        "+bitexact",
        "-movflags",
        "+faststart",
        str(dst),
    )
    if code or not dst.exists() or not dst.stat().st_size:
        raise CleanError(output.strip()[-500:] or "Empty media output.")


async def inspect(src):
    code, output = await _run(
        "exiftool", "-j", "-G1", "-s", "-GPSPosition", "-all", str(Path(src).resolve())
    )
    if code:
        raise CleanError(output.strip()[-500:] or "Could not read metadata.")
    tags = json.loads(output)[0]
    if any(key.rsplit(":", 1)[-1] == "Error" for key in tags):
        raise CleanError("Could not read metadata.")
    return metadata_findings(tags)
