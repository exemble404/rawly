"""Full-frame D processing: orientation, sRGB, half-size roundtrip and adaptive grain."""

import io
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageCms, ImageOps

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass

IMAGE_EXT = {
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


class ProcessingError(ValueError):
    pass


def _read_image(src: Path, max_megapixels: float) -> Image.Image:
    with Image.open(src) as source:
        if source.width * source.height > max_megapixels * 1_000_000:
            raise ProcessingError(
                f"Image exceeds the {max_megapixels:g} megapixel limit."
            )
        if getattr(source, "n_frames", 1) != 1:
            raise ProcessingError(
                "Animated or multipage images are unsupported; use a static image."
            )
        # Поворот применяем к пикселям до удаления EXIF Orientation.
        oriented = ImageOps.exif_transpose(source)
        alpha = (
            oriented.convert("RGBA").getchannel("A")
            if ("A" in oriented.getbands() or "transparency" in oriented.info)
            else None
        )
        profile = oriented.info.get("icc_profile")
        if profile:
            # Переводим цвета в sRGB прежде, чем удалить исходный ICC-профиль.
            color = (
                oriented
                if oriented.mode in {"RGB", "CMYK", "LAB"}
                else oriented.convert("RGB")
            )
            color = ImageCms.profileToProfile(
                color,
                ImageCms.ImageCmsProfile(io.BytesIO(profile)),
                ImageCms.createProfile("sRGB"),
                outputMode="RGB",
            )
        else:
            color = oriented.convert("RGB")
        if alpha is not None:
            color.putalpha(alpha)
        color.load()
        return color


# Frozen D parameters. A fixed seed makes retries and repeat uploads reproducible.
D_NOISE_SEED = 8501


def _unit_std(field):
    centered = field - field.mean(axis=(0, 1), keepdims=True)
    deviation = centered.std(axis=(0, 1), keepdims=True)
    return centered / np.where(deviation > 0, deviation, 1.0)


def adaptive_grain_d(image: Image.Image, *, seed: int = D_NOISE_SEED) -> Image.Image:
    """Accepted D: half-size roundtrip, correlated monochrome grain, strength 4–7.

    Seed is exposed for reproducing historical experiments; production uses one
    fixed seed for every input. Detector scores depend on the source image and the detector.
    """
    w, h = image.size
    base = image.resize(
        (max(1, round(w * 0.5)), max(1, round(h * 0.5))), Image.Resampling.LANCZOS
    ).resize((w, h), Image.Resampling.LANCZOS)
    rgb = np.asarray(base).astype(np.float32)
    y = rgb @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    del rgb
    mean = cv2.GaussianBlur(y, (0, 0), 2, borderType=cv2.BORDER_REFLECT_101)
    second = cv2.GaussianBlur(y * y, (0, 0), 2, borderType=cv2.BORDER_REFLECT_101)
    weight = np.clip(np.sqrt(np.maximum(second - mean * mean, 0)) / 12.0, 0, 1)
    del y, mean, second
    weight = np.clip(
        cv2.GaussianBlur(weight, (0, 0), 3, borderType=cv2.BORDER_REFLECT_101), 0, 1
    )
    amplitude = 4 + 3 * weight.astype(np.float64)
    del weight
    standard = np.random.default_rng(seed).standard_normal((h, w, 3))
    field = cv2.GaussianBlur(standard, (0, 0), 0.5, borderType=cv2.BORDER_REFLECT_101)
    del standard
    field = _unit_std(field)
    gray = field.mean(axis=2, keepdims=True)
    monochrome = _unit_std(gray + 0.0 * (field - gray))
    del field, gray
    noise = monochrome * amplitude[:, :, None]
    del monochrome, amplitude
    raw = np.asarray(base).astype(np.float64) + noise
    del noise
    return Image.fromarray(np.rint(np.clip(raw, 0, 255)).astype("uint8"))


def process_image(src: Path, dst: Path, *, max_megapixels=24, seed=D_NOISE_SEED):
    """Write a new PNG. The caller stages and publishes the output atomically."""
    src, dst = Path(src), Path(dst)
    if src.resolve() == dst.resolve() or dst.exists():
        raise ProcessingError("Output already exists; original was not changed.")
    if dst.suffix.lower() != ".png":
        raise ProcessingError("Photo output must be PNG.")
    if not 0 < max_megapixels <= 300:
        raise ProcessingError("Megapixel limit must be between 0 and 300.")
    image = _read_image(src, max_megapixels)
    alpha = image.getchannel("A") if image.mode == "RGBA" else None
    image = adaptive_grain_d(image.convert("RGB"), seed=seed)
    if alpha is not None:
        image.putalpha(alpha)
    output = Image.frombytes(image.mode, image.size, image.tobytes())
    with dst.open("xb") as stream:
        output.save(stream, format="PNG", optimize=True)
