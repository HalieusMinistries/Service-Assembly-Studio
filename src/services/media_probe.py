from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass

from .ffmpeg_locator import FFmpegTools


@dataclass
class MediaInfo:
    path: str
    duration: float
    width: int
    height: int
    fps: float
    has_video: bool
    has_audio: bool
    video_codec: str | None = None
    audio_codec: str | None = None


class MediaProbe:
    def __init__(self, tools: FFmpegTools) -> None:
        self._tools = tools

    def probe(self, path: str) -> MediaInfo:
        command = [
            self._tools.ffprobe,
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            path,
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=True,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.strip() if exc.stderr else "Unknown ffprobe error"
            raise RuntimeError(f"Could not read media file: {stderr}") from exc
        except FileNotFoundError as exc:
            raise RuntimeError("ffprobe executable was not found.") from exc

        payload = json.loads(result.stdout or "{}")
        streams = payload.get("streams", [])
        fmt = payload.get("format", {})

        video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

        duration = float(fmt.get("duration") or 0.0)
        if duration <= 0 and video_stream and video_stream.get("duration"):
            duration = float(video_stream["duration"])

        width = int(video_stream.get("width", 0)) if video_stream else 0
        height = int(video_stream.get("height", 0)) if video_stream else 0
        fps = _parse_fps(video_stream.get("avg_frame_rate", "0/1") if video_stream else "0/1")

        return MediaInfo(
            path=path,
            duration=duration,
            width=width,
            height=height,
            fps=fps,
            has_video=video_stream is not None,
            has_audio=audio_stream is not None,
            video_codec=video_stream.get("codec_name") if video_stream else None,
            audio_codec=audio_stream.get("codec_name") if audio_stream else None,
        )


def _parse_fps(value: str) -> float:
    if not value or value == "0/0":
        return 0.0
    if "/" in value:
        num, den = value.split("/", 1)
        try:
            denominator = float(den)
            if denominator == 0:
                return 0.0
            return float(num) / denominator
        except ValueError:
            return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0
