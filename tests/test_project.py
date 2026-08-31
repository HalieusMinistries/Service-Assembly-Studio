import json
import tempfile
import unittest
from pathlib import Path

from src.models.project import PROJECT_EXTENSION, Project
from src.models.timeline_item import ItemType, TimelineItem
from src.services.ffmpeg_locator import FFmpegLocator
from src.services.export_service import ExportService
from src.services.media_probe import MediaProbe


class ProjectTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        item = TimelineItem(
            source_path="C:/videos/welcome.mp4",
            display_name="Welcome",
            item_type=ItemType.WORSHIP,
            trim_start=1.5,
            trim_end=30.0,
            duration=45.0,
        )
        project = Project(name="Sunday Service", items=[item], last_export_path="C:/out/service.mp4")

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / f"test{PROJECT_EXTENSION}"
            project.save(str(path))
            loaded = Project.load(str(path))

        self.assertEqual(loaded.name, "Sunday Service")
        self.assertEqual(len(loaded.items), 1)
        self.assertEqual(loaded.items[0].display_name, "Welcome")
        self.assertEqual(loaded.items[0].item_type, ItemType.WORSHIP)
        self.assertAlmostEqual(loaded.items[0].trim_start, 1.5)
        self.assertAlmostEqual(loaded.items[0].effective_duration, 28.5)


class ExportIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tools = FFmpegLocator.find()
        cls.probe = MediaProbe(cls.tools)
        cls.export = ExportService(cls.tools)
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.media_dir = Path(cls.temp_dir.name)

        cls.speech_path = cls.media_dir / "speech.mp4"
        cls.worship_path = cls.media_dir / "worship.mp4"

        import subprocess

        creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0

        subprocess.run(
            [
                cls.tools.ffmpeg,
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc=size=1280x720:rate=30",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=3",
                "-shortest",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                str(cls.speech_path),
            ],
            check=True,
            capture_output=True,
            creationflags=creationflags,
        )

        subprocess.run(
            [
                cls.tools.ffmpeg,
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc=size=720x1280:rate=25",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=880:duration=4",
                "-shortest",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                str(cls.worship_path),
            ],
            check=True,
            capture_output=True,
            creationflags=creationflags,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp_dir.cleanup()

    def test_probe_reads_duration(self) -> None:
        info = self.probe.probe(str(self.speech_path))
        self.assertTrue(info.has_video)
        self.assertTrue(info.has_audio)
        self.assertGreater(info.duration, 2.0)

    def test_export_joins_mixed_segments(self) -> None:
        speech = TimelineItem(
            source_path=str(self.speech_path),
            display_name="Announcements",
            item_type=ItemType.SPEECH,
            duration=self.probe.probe(str(self.speech_path)).duration,
            trim_end=2.0,
        )
        worship = TimelineItem(
            source_path=str(self.worship_path),
            display_name="Worship Song",
            item_type=ItemType.WORSHIP,
            duration=self.probe.probe(str(self.worship_path)).duration,
            trim_start=0.5,
            trim_end=3.0,
        )
        project = Project(name="Test Service", items=[speech, worship])
        output_path = self.media_dir / "export.mp4"

        progress_messages: list[str] = []

        def on_progress(pct: int, message: str) -> None:
            progress_messages.append(f"{pct}:{message}")

        result = self.export.export_project(project, str(output_path), on_progress)
        self.assertEqual(result, str(output_path))
        self.assertTrue(output_path.is_file())
        self.assertGreater(output_path.stat().st_size, 10_000)

        out_info = self.probe.probe(str(output_path))
        self.assertTrue(out_info.has_video)
        self.assertTrue(out_info.has_audio)
        self.assertEqual(out_info.width, 1920)
        self.assertEqual(out_info.height, 1080)
        self.assertGreater(out_info.duration, 3.0)
        self.assertTrue(progress_messages)


if __name__ == "__main__":
    unittest.main()
