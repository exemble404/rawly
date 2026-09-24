"""Synthetic integration tests: no private fixtures, model calls or remote services."""

import asyncio
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/rawly/scripts"
sys.path.insert(0, str(SCRIPTS))
from rawly_core import cli, images, media, profiles
from PIL import Image, ImageOps, PngImagePlugin
import numpy as np

spec = importlib.util.spec_from_file_location("installer", ROOT / "install.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def execute(*args):
    return subprocess.run(
        [str(a) for a in args], capture_output=True, check=True
    ).stdout


def packets(path):
    data = json.loads(
        execute(
            "ffprobe",
            "-v",
            "error",
            "-show_packets",
            "-show_data_hash",
            "sha256",
            "-of",
            "json",
            path,
        )
    )
    return [(p["stream_index"], p["data_hash"]) for p in data["packets"]]


class ImageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.src = self.root / "original.png"
        y, x = np.mgrid[:73, :111]
        Image.fromarray(
            np.stack((x * 2 % 256, y * 3 % 256, (x + y) % 256), axis=2).astype("uint8")
        ).save(self.src)

    def test_repeatable_full_frame_and_untouched_source(self):
        original = self.src.read_bytes()
        a, b = self.root / "a.png", self.root / "b.png"
        images.process_image(self.src, a)
        images.process_image(self.src, b)
        self.assertEqual(a.read_bytes(), b.read_bytes())
        self.assertEqual(self.src.read_bytes(), original)
        with Image.open(a) as output, Image.open(self.src) as source:
            self.assertEqual(source.size, output.size)
            self.assertNotEqual(source.tobytes(), output.tobytes())
            self.assertFalse(output.info)

    def test_orientation_applied_and_alpha_preserved(self):
        source = Image.new("RGBA", (21, 13), (60, 100, 140, 100))
        source.putpixel((1, 2), (230, 10, 90, 30))
        exif = Image.Exif()
        exif[274] = 6
        source.save(self.src, exif=exif)
        dst = self.root / "out.png"
        images.process_image(self.src, dst)
        with Image.open(self.src) as before, Image.open(dst) as after:
            oriented = ImageOps.exif_transpose(before)
            self.assertEqual(after.size, (13, 21))
            self.assertEqual(
                oriented.getchannel("A").tobytes(), after.getchannel("A").tobytes()
            )

    def test_no_overwrite(self):
        for path in (self.src, self.root / "existing.png"):
            if not path.exists():
                path.write_bytes(b"keep")
            original = path.read_bytes()
            with self.assertRaises(images.ProcessingError):
                images.process_image(self.src, path)
            self.assertEqual(path.read_bytes(), original)

    def test_limit_and_animation_rejected_before_output(self):
        output = self.root / "no.png"
        with self.assertRaises(images.ProcessingError):
            images.process_image(self.src, output, max_megapixels=0.001)
        self.assertFalse(output.exists())
        anim = self.root / "a.gif"
        Image.new("RGB", (8, 8), "red").save(
            anim,
            save_all=True,
            append_images=[Image.new("RGB", (8, 8), "blue")],
            duration=100,
        )
        with self.assertRaises(images.ProcessingError):
            images.process_image(anim, output)
        self.assertFalse(output.exists())

    def test_tiny_images(self):
        for index, size in enumerate(((1, 1), (1, 13), (13, 1), (3, 5))):
            Image.new("RGB", size, (70, 120, 180)).save(self.src)
            out = self.root / f"{index}.png"
            images.process_image(self.src, out)
            with Image.open(out) as image:
                self.assertEqual(image.size, size)

    @unittest.skipUnless(shutil.which("exiftool"), "ExifTool not installed")
    def test_profile_keeps_d_pixels_and_replaces_private_tags(self):
        execute(
            "exiftool",
            "-overwrite_original",
            "-Artist=private",
            "-Make=old",
            "-GPSLatitude=12",
            "-GPSLatitudeRef=N",
            self.src,
        )
        direct = self.root / "direct.png"
        out = self.root / "out.png"
        images.process_image(self.src, direct)
        profile = cli.profile_data(
            {
                "device": "apple_0",
                "time": "fixed",
                "datetime": "2026:09:24 12:00:00",
                "timezone": "+03:00",
            }
        )
        asyncio.run(cli.process_one(self.src, out, profile))
        with Image.open(out) as a, Image.open(direct) as b:
            self.assertEqual(a.tobytes(), b.tobytes())
        tags = json.loads(
            execute("exiftool", "-j", "-Make", "-Model", "-Artist", "-GPSLatitude", out)
        )[0]
        self.assertEqual(tags["Make"], "Apple")
        self.assertEqual(tags["Model"], profiles.DEVICES["apple_0"]["model"])
        self.assertNotIn("Artist", tags)
        self.assertNotIn("GPSLatitude", tags)

    @unittest.skipUnless(shutil.which("exiftool"), "ExifTool not installed")
    def test_no_profile_removes_provenance_text(self):
        info = PngImagePlugin.PngInfo()
        info.add_text("Software", "Synthetic generator")
        info.add_text("Author", "private")
        Image.new("RGB", (40, 30), "gray").save(self.src, pnginfo=info)
        out = self.root / "out.png"
        asyncio.run(cli.process_one(self.src, out))
        self.assertFalse(asyncio.run(media.inspect(out)))


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "in"
        self.source.mkdir()
        self.out = self.root / "out"

    def invoke(self, *args):
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "rawly.py"), *map(str, args)],
            capture_output=True,
            text=True,
        )
        return result, json.loads(result.stdout)

    def test_100_files_through_real_cli(self):
        for i in range(100):
            Image.new("RGB", (8, 8), (70, 110, 140)).save(self.source / f"{i:03}.png")
        response, result = self.invoke("process", self.source, "--output", self.out)
        self.assertEqual(response.returncode, 0, response.stderr)
        self.assertEqual(len(result["files"]), 100)
        self.assertTrue(all(row["status"] == "ok" for row in result["files"]))
        self.assertTrue(Path(result["report"]).exists())
        self.assertEqual(len(list(self.source.glob("*.png"))), 100)
        self.assertEqual(len(list(self.out.glob("*.png"))), 100)
        again, repeated = self.invoke("process", self.source, "--output", self.out)
        self.assertEqual(again.returncode, 1)
        self.assertTrue(all(row["status"] == "error" for row in repeated["files"]))

    def test_failed_file_does_not_abort_or_publish_partial(self):
        (self.source / "bad.jpg").write_bytes(b"broken")
        Image.new("RGB", (8, 8)).save(self.source / "good.png")
        response, result = self.invoke("process", self.source, "--output", self.out)
        self.assertEqual(response.returncode, 1)
        self.assertEqual([row["status"] for row in result["files"]], ["error", "ok"])
        self.assertFalse((self.out / "bad.jpg.rawly.png").exists())
        self.assertFalse(list(self.out.glob(".rawly-*")))

    def test_nested_outputs_not_reprocessed_and_duplicates_not_overwritten(self):
        Image.new("RGB", (8, 8)).save(self.source / "same.jpg")
        Image.new("RGB", (8, 8)).save(self.source / "same.png")
        output = self.source / "output"
        output.mkdir()
        Image.new("RGB", (8, 8)).save(output / "old.png")
        jobs = cli.plan_files([self.source], output, True)
        self.assertEqual(len(jobs), 2)
        self.assertEqual(len({dst for _, dst in jobs}), 2)
        self.assertEqual(
            len(cli.plan_files([self.source / "same.jpg"] * 2, self.out)), 1
        )
        with self.assertRaises(ValueError):
            cli.plan_files([self.source], self.source)

    def test_invalid_profile_and_report_fail_before_writing(self):
        Image.new("RGB", (8, 8)).save(self.source / "photo.png")
        profile = self.root / "profile.json"
        profile.write_text("{}")
        response, result = self.invoke(
            "process", self.source, "--output", self.out, "--profile", profile
        )
        self.assertEqual(response.returncode, 2)
        self.assertFalse(self.out.exists())
        report = self.root / "report.json"
        report.write_text("keep")
        response, _ = self.invoke(
            "process", self.source, "--output", self.out, "--report", report
        )
        self.assertEqual(response.returncode, 2)
        self.assertFalse(self.out.exists())
        self.assertEqual(report.read_text(), "keep")

    def test_empty_missing_and_unsupported_input_are_errors(self):
        for source in (self.source, self.root / "missing", self.root / "text.txt"):
            if source.suffix == ".txt":
                source.write_text("test")
            with self.assertRaises(ValueError):
                cli.plan_files([source], self.out)

    def test_profile_file_and_doctor(self):
        path = self.root / "profile.json"
        response, result = self.invoke("profile", path, "--device", "apple_0")
        self.assertEqual(response.returncode, 0, response.stderr)
        self.assertEqual(cli.load_profile(path)["device_id"], "apple_0")
        again, _ = self.invoke("profile", path, "--device", "apple_0")
        self.assertEqual(again.returncode, 2)
        response, result = self.invoke("doctor")
        self.assertIn("packages", result)


class ProfileTests(unittest.TestCase):
    def test_invalid_values_rejected(self):
        for config in (
            {"device": "unknown"},
            {"device": "apple_0", "city": []},
            {"device": "apple_0", "time": "never"},
            {"device": "apple_0", "timezone": "+25:00"},
            {"device": "apple_0", "time": "fixed"},
            {"device": "apple_0", "extra": "argument"},
            [],
            {"device": {"make": "Apple"}},
        ):
            with (
                self.subTest(config=config),
                self.assertRaises((ValueError, TypeError)),
            ):
                cli.profile_data(config)

    def test_gps_time_is_utc_with_date_rollover(self):
        from datetime import datetime

        fields = profiles._exif_args(
            profiles.DEVICES["apple_0"],
            datetime(2026, 9, 24, 1, 0),
            "+03:00",
            {"lat": 0, "lon": 0},
        )
        self.assertIn("-GPSTimeStamp=22:00:00", fields)
        self.assertIn("-GPSDateStamp=2026:09:23", fields)

    def test_explicit_offset_overrides_city(self):
        profile = cli.profile_data(
            {
                "device": "apple_0",
                "city": "c_Россия_Москва",
                "timezone": "+09:00",
                "time": "fixed",
                "datetime": "2026:09:24 10:00:00",
            }
        )
        when, zone = profiles._shot_time(profile)
        self.assertEqual(zone, "+09:00")
        self.assertEqual(when.hour, 10)

    def test_hostile_custom_device_not_shell_code(self):
        config = {
            "device": dict(profiles.DEVICES["apple_0"], model="x; touch /tmp/not-run")
        }
        result = cli.profile_data(config)
        self.assertIn(
            "x; touch", result["device_json"]
        )  # Metadata string, never a shell command.


@unittest.skipUnless(
    all(shutil.which(x) for x in ("ffmpeg", "ffprobe", "exiftool")),
    "Media tools not installed",
)
class VideoTests(unittest.TestCase):
    def test_clean_and_profile_preserve_encoded_packets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "source.mp4"
            execute(
                "ffmpeg",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=64x48:rate=10",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=400:sample_rate=8000",
                "-t",
                "0.3",
                "-c:v",
                "libx264",
                "-c:a",
                "aac",
                "-metadata",
                "artist=private",
                "-movflags",
                "use_metadata_tags",
                "-metadata",
                'AIGC={"Label":"1"}',
                src,
            )
            original = src.read_bytes()
            self.assertIn("AIGC", execute("exiftool", "-j", "-AIGC", src).decode())
            for index, profile in enumerate(
                (None, cli.profile_data({"device": "apple_0"}))
            ):
                out = root / f"out{index}.mp4"
                asyncio.run(cli.process_one(src, out, profile))
                self.assertEqual(packets(src), packets(out))
                tags = json.loads(execute("exiftool", "-j", "-Artist", "-AIGC", out))[0]
                self.assertNotIn("Artist", tags)
                self.assertNotIn("AIGC", tags)
            self.assertEqual(src.read_bytes(), original)

    def test_failed_profile_write_never_publishes_output(self):
        async def fails(src, dst, profile):
            dst.write_bytes(b"partial")
            raise profiles.CleanError("write failed")

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(profiles, "mimic_video", side_effect=fails),
        ):
            src = Path(tmp) / "a.mp4"
            out = Path(tmp) / "b.mp4"
            src.write_bytes(b"original")
            with self.assertRaises(profiles.CleanError):
                asyncio.run(cli.process_one(src, out, {"device": "x"}))
            self.assertFalse(out.exists())
            self.assertEqual(src.read_bytes(), b"original")


class InstallerTests(unittest.TestCase):
    def test_install_both_update_uninstall_preserves_other_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            for host, target in installer.targets(home, "both"):
                other = target.parent / "other"
                other.mkdir(parents=True)
                (other / "SKILL.md").write_text("keep")
                installer.install(target, skip_deps=True)
                self.assertTrue((target / "scripts/rawly_core/images.py").exists())
                self.assertTrue((target / "SKILL.md").exists())
                (target / "custom-note.txt").write_text("mine")
                installer.install(target, skip_deps=True)
                result = subprocess.run(
                    [sys.executable, str(target / "scripts/rawly.py"), "--help"],
                    capture_output=True,
                )
                self.assertEqual(result.returncode, 0)
                installer.uninstall(target)
                self.assertEqual((other / "SKILL.md").read_text(), "keep")
                self.assertEqual((target / "custom-note.txt").read_text(), "mine")
                self.assertFalse((target / "scripts/rawly.py").exists())

    def test_unknown_skill_and_symlink_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            foreign = root / "foreign"
            foreign.mkdir()
            (foreign / "SKILL.md").write_text("keep")
            with self.assertRaises(ValueError):
                installer.install(foreign, skip_deps=True)
            with self.assertRaises(ValueError):
                installer.uninstall(foreign)
            link = root / "link"
            link.symlink_to(foreign, target_is_directory=True)
            with self.assertRaises(ValueError):
                installer.install(link, skip_deps=True)
            self.assertEqual((foreign / "SKILL.md").read_text(), "keep")

    def test_manifest_cannot_escape_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "rawly"
            installer.install(target, True)
            outside = root / "keep"
            outside.write_text("private")
            marker = target / installer.MARKER
            data = json.loads(marker.read_text())
            data["files"].append("../keep")
            marker.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                installer.uninstall(target)
            self.assertEqual(outside.read_text(), "private")


if __name__ == "__main__":
    unittest.main()
