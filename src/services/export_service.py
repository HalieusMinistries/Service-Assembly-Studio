from __future__ import annotations

import re
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Callable

from src.models.project import Project
from src.models.timeline_item import ItemType, TimelineItem
from src.services.ffmpeg_locator import FFmpegTools
from src.services.media_probe import MediaProbe

ProgressCallback = Callable[[int, str], None]

# YouTube-friendly 1080p output
OUTPUT_WIDTH = 1920
OUTPUT_HEIGHT = 1080
OUTPUT_FPS = 30

VIDEO_FILTER = (
    f"scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:force_original_aspect_ratio=decrease,"
    f"pad={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,"
    f"fps={OUTPUT_FPS},format=yuv420p"
)

SPEECH_AUDIO_FILTER = (
    "highpass=f=80,"
    "acompressor=threshold=-20dB:ratio=2.5:attack=5:release=80:makeup=2,"
    "loudnorm=I=-16:TP=-1.5:LRA=11"
)

WORSHIP_AUDIO_FILTER = "loudnorm=I=-16:TP=-1.5:LRA=11"

FINAL_AUDIO_FILTER = "loudnorm=I=-16:TP=-1.5:LRA=11"


class ExportService:
    def __init__(self, tools: FFmpegTools) -> None:
        self._tools = tools
        self._probe = MediaProbe(tools)
        self._cancel_requested = False

    def cancel(self) -> None:
        self._cancel_requested = True

    def export_project(
        self,
        project: Project,
        output_path: str,
        progress: ProgressCallback | None = None,
    ) -> str:
        self._cancel_requested = False

        if not project.items:
            raise ValueError("Add at least one section before exporting.")

        missing = project.missing_sources()
        if missing:
            names = ", ".join(item.display_name for item in missing[:3])
            extra = f" (+{len(missing) - 3} more)" if len(missing) > 3 else ""
            raise FileNotFoundError(f"Missing source files: {names}{extra}")

        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        total_duration = sum(item.effective_duration for item in project.items)
        if total_duration <= 0:
            raise ValueError("Total duration is zero. Check trim settings.")

        def report(pct: int, message: str) -> None:
            if progress:
                progress(max(0, min(100, pct)), message)

        report(0, "Preparing export…")

        with tempfile.TemporaryDirectory(prefix="sas_export_") as temp_dir:
            temp_path = Path(temp_dir)
            segment_paths: list[Path] = []

            for index, item in enumerate(project.items):
                if self._cancel_requested:
                    raise RuntimeError("Export cancelled.")

                segment_name = f"segment_{index:03d}.mp4"
                segment_file = temp_path / segment_name
                label = f"Processing {index + 1}/{len(project.items)}: {item.display_name}"

                base_pct = int((index / len(project.items)) * 85)
                report(base_pct, label)

                self._render_segment(
                    item=item,
                    output_file=segment_file,
                    progress=lambda local_pct, msg: report(
                        base_pct + int(local_pct * (85 / len(project.items)) / 100),
                        msg or label,
                    ),
                )
                segment_paths.append(segment_file)

            if self._cancel_requested:
                raise RuntimeError("Export cancelled.")

            report(88, "Joining sections…")
            joined_file = temp_path / "joined.mp4"
            self._concat_segments(segment_paths, joined_file)

            if self._cancel_requested:
                raise RuntimeError("Export cancelled.")

            report(94, "Final audio balance…")
            self._final_pass(joined_file, output, total_duration, report)

        report(100, "Export complete.")
        return str(output)

    def _render_segment(
        self,
        item: TimelineItem,
        output_file: Path,
        progress: ProgressCallback | None = None,
    ) -> None:
        info = self._probe.probe(item.source_path)
        if not info.has_video:
            raise RuntimeError(f"{item.display_name} does not contain a video track.")

        end_time = item.trim_end if item.trim_end is not None else info.duration
        if end_time <= item.trim_start:
            raise RuntimeError(
                f"{item.display_name}: trim end must be after trim start."
            )

        audio_filter = (
            WORSHIP_AUDIO_FILTER if item.item_type == ItemType.WORSHIP else SPEECH_AUDIO_FILTER
        )

        command: list[str] = [
            self._tools.ffmpeg,
            "-y",
            "-ss",
            f"{item.trim_start:.3f}",
            "-to",
            f"{end_time:.3f}",
            "-i",
            item.source_path,
            "-vf",
            VIDEO_FILTER,
        ]

        if info.has_audio:
            command.extend(["-af", audio_filter, "-c:a", "aac", "-b:a", "192k"])
        else:
            command.extend(["-an"])

        command.extend(
            [
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                "-progress",
                "pipe:1",
                "-nostats",
                str(output_file),
            ]
        )

        duration = end_time - item.trim_start
        self._run_ffmpeg(command, duration, progress)

    def _concat_segments(self, segments: list[Path], output_file: Path) -> None:
        list_file = output_file.with_suffix(".txt")
        lines = [f"file '{path.as_posix()}'" for path in segments]
        list_file.write_text("\n".join(lines), encoding="utf-8")

        command = [
            self._tools.ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c",
            "copy",
            str(output_file),
        ]
        self._run_ffmpeg(command, total_duration=None, progress=None)

    def _final_pass(
        self,
        input_file: Path,
        output_file: Path,
        total_duration: float,
        progress: ProgressCallback | None = None,
    ) -> None:
        command = [
            self._tools.ffmpeg,
            "-y",
            "-i",
            str(input_file),
            "-af",
            FINAL_AUDIO_FILTER,
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            "-progress",
            "pipe:1",
            "-nostats",
            str(output_file),
        ]
        self._run_ffmpeg(command, total_duration, progress)

    def _run_ffmpeg(
        self,
        command: list[str],
        total_duration: float | None,
        progress: ProgressCallback | None,
    ) -> None:
        creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=creationflags,
        )

        stderr_chunks: list[str] = []

        def _read_stderr() -> None:
            if process.stderr is not None:
                stderr_chunks.append(process.stderr.read())

        stderr_thread = threading.Thread(target=_read_stderr, daemon=True)
        stderr_thread.start()

        assert process.stdout is not None
        time_re = re.compile(r"out_time_ms=(\d+)")
        last_pct = -1

        for line in process.stdout:
            if self._cancel_requested:
                process.terminate()
                raise RuntimeError("Export cancelled.")

            match = time_re.search(line)
            if match and total_duration and progress:
                seconds = int(match.group(1)) / 1_000_000
                pct = int(min(99, (seconds / total_duration) * 100))
                if pct != last_pct:
                    last_pct = pct
                    progress(pct, "Processing…")

        stderr_thread.join()
        stderr = stderr_chunks[0] if stderr_chunks else ""
        return_code = process.wait()

        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()

        if return_code != 0:
            message = _extract_ffmpeg_error(stderr)
            raise RuntimeError(message)

    @staticmethod
    def default_output_path(project: Project) -> str:
        if project.last_export_path:
            return project.last_export_path
        safe_name = "".join(c if c.isalnum() or c in " -_" else "_" for c in project.name)
        return str(Path.home() / "Videos" / f"{safe_name.strip() or 'service'}.mp4")


def _extract_ffmpeg_error(stderr: str) -> str:
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    for line in reversed(lines):
        if any(
            token in line.lower()
            for token in ("error", "invalid", "no such file", "does not contain", "failed")
        ):
            return line
    if lines:
        return lines[-1]
    return "FFmpeg failed with an unknown error."
