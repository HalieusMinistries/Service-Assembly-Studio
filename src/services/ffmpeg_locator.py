from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FFmpegTools:
    ffmpeg: str
    ffprobe: str


class FFmpegLocator:
    """Locate FFmpeg and ffprobe on Windows without modifying originals."""

    @staticmethod
    def find() -> FFmpegTools:
        candidates: list[Path] = []

        env_path = os.environ.get("FFMPEG_PATH")
        if env_path:
            candidates.append(Path(env_path))

        if getattr(sys, "frozen", False):
            bundle_dir = Path(sys.executable).parent
            candidates.extend(
                [
                    bundle_dir / "ffmpeg" / "bin",
                    bundle_dir,
                ]
            )

        candidates.extend(
            [
                Path(r"C:\Users\user\ffmpeg\ffmpeg-8.1-essentials_build\bin"),
                Path(r"C:\ffmpeg\bin"),
                Path(r"C:\Program Files\ffmpeg\bin"),
            ]
        )

        for directory in candidates:
            ffmpeg = directory / "ffmpeg.exe"
            ffprobe = directory / "ffprobe.exe"
            if ffmpeg.is_file() and ffprobe.is_file():
                return FFmpegTools(str(ffmpeg), str(ffprobe))

        ffmpeg = shutil.which("ffmpeg")
        ffprobe = shutil.which("ffprobe")
        if ffmpeg and ffprobe:
            return FFmpegTools(ffmpeg, ffprobe)

        raise FileNotFoundError(
            "FFmpeg was not found. Install FFmpeg and ensure ffmpeg.exe and "
            "ffprobe.exe are on your PATH, or set the FFMPEG_PATH environment "
            "variable to the folder containing them."
        )
