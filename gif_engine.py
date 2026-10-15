# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 yuudong123
# See LICENSE for the full license text.

"""Video sampling and GIF encoding, independent of the desktop UI."""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Callable

import imageio_ffmpeg

MAX_FRAMES = 3000
Progress = Callable[[int, str], None]


class Cancelled(Exception):
    pass


@contextmanager
def temporary_directory(prefix: str):
    directory = Path(tempfile.mkdtemp(prefix=prefix)).resolve()
    try:
        yield directory
    finally:
        # Windows can briefly retain a terminated encoder's file handles.
        # Restrict cleanup to the exact task-created directory under the temp root.
        if directory.parent != Path(tempfile.gettempdir()).resolve() or not directory.name.startswith("gif-"):
            raise RuntimeError("임시 폴더 경로를 확인하지 못했어요.")
        for attempt in range(20):
            try:
                shutil.rmtree(directory)
                break
            except FileNotFoundError:
                break
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.1)


@dataclass(frozen=True)
class VideoInfo:
    path: Path
    duration: float
    width: int
    height: int
    fps: float


@dataclass(frozen=True)
class ClipSettings:
    start: float
    end: float
    fps: int
    width: int

    @property
    def duration(self) -> float:
        return self.end - self.start

    def validate(self) -> None:
        if self.start < 0 or self.duration <= 0:
            raise ValueError("끝 시간은 시작 시간보다 뒤여야 해요.")
        if not 1 <= self.fps <= 50:
            raise ValueError("FPS는 1~50 사이로 설정해 주세요.")
        if not 64 <= self.width <= 1920:
            raise ValueError("출력 너비는 64~1920px 사이로 설정해 주세요.")
        if self.duration * self.fps > MAX_FRAMES:
            raise ValueError(f"한 번에 {MAX_FRAMES:,}프레임까지 편집할 수 있어요. 구간이나 FPS를 줄여 주세요.")


def ffmpeg() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


def process_options() -> dict:
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def probe_video(path: Path) -> VideoInfo:
    result = subprocess.run(
        [ffmpeg(), "-hide_banner", "-nostdin", "-i", str(path)],
        capture_output=True, encoding="utf-8", errors="replace", timeout=30,
        **process_options(),
    )
    duration = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
    stream = next((line for line in result.stderr.splitlines()
                   if "Video:" in line and "attached pic" not in line), "")
    dimensions = re.search(r"\b(\d{2,6})x(\d{2,6})\b", stream)
    rate = re.search(r"([\d.]+) fps", stream)
    if not duration or not dimensions:
        raise ValueError("영상 정보를 읽지 못했어요. 재생 가능한 영상 파일을 선택해 주세요.")
    hours, minutes, seconds = map(float, duration.groups())
    length = hours * 3600 + minutes * 60 + seconds
    if length <= 0:
        raise ValueError("길이가 0인 영상은 열 수 없어요.")
    return VideoInfo(path.resolve(), length, int(dimensions[1]), int(dimensions[2]),
                     float(rate[1]) if rate else 0.0)


def run_ffmpeg(args: list[str], cancel: threading.Event, progress: Progress,
               duration: float, base: int, span: int, label: str) -> None:
    """File-backed logs avoid pipe deadlocks; cancellation also works without output."""
    with temporary_directory(prefix="gif-process-") as temp:
        log_path = Path(temp) / "error.log"
        progress_path = Path(temp) / "progress.log"
        with log_path.open("wb") as log, progress_path.open("wb") as report:
            process = subprocess.Popen(
                [ffmpeg(), "-hide_banner", "-nostdin", "-loglevel", "error",
                 "-y", "-progress", "pipe:1", "-nostats", *args],
                stdout=report, stderr=log, **process_options(),
            )
            try:
                progress(base, label)
                while process.poll() is None:
                    if cancel.wait(0.1):
                        raise Cancelled()
                    # FFmpeg emits a small progress report roughly twice per second.
                    data = progress_path.read_text(encoding="utf-8", errors="replace")
                    times = re.findall(r"out_time_us=(\d+)", data)
                    if times and duration > 0:
                        ratio = min(1.0, int(times[-1]) / 1_000_000 / duration)
                        progress(base + int(span * ratio), label)
                if cancel.is_set():
                    raise Cancelled()
                if process.returncode:
                    log.flush()
                    detail = log_path.read_text(encoding="utf-8", errors="replace")[-1600:]
                    raise RuntimeError(f"영상 처리에 실패했어요.\n{detail}")
                progress(base + span, label)
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()


def extract_frames(video: VideoInfo, settings: ClipSettings, directory: Path,
                   cancel: threading.Event, progress: Progress,
                   preview: bool = False, base: int = 0, span: int = 100) -> list[Path]:
    settings.validate()
    directory.mkdir(parents=True, exist_ok=True)
    width = min(settings.width, 640) if preview else settings.width
    suffix = "jpg" if preview else "png"
    filters = f"fps={settings.fps}:start_time=0,scale=w='min(iw,{width})':h=-1:flags=lanczos,setsar=1"
    args = ["-ss", f"{settings.start:.6f}", "-i", str(video.path),
            "-t", f"{settings.duration:.6f}", "-map", "0:V:0", "-an",
            "-vf", filters, "-frames:v", str(MAX_FRAMES + 1),
            "-fps_mode", "passthrough"]
    if preview:
        args += ["-q:v", "3"]
    args += [str(directory / f"frame-%06d.{suffix}")]
    run_ffmpeg(args, cancel, progress, settings.duration, base, span,
               "프레임 불러오는 중…" if preview else "원본에서 프레임 추출 중…")
    frames = sorted(directory.glob(f"frame-*.{suffix}"))
    if not frames:
        raise ValueError("선택한 구간에 프레임이 없어요. 구간을 조금 늘려 주세요.")
    if len(frames) > MAX_FRAMES:
        raise ValueError("프레임이 너무 많아요. 구간이나 FPS를 줄여 주세요.")
    return frames


def export_gif(video: VideoInfo, settings: ClipSettings, kept: list[int],
               expected_count: int, target: Path, loop: bool,
               cancel: threading.Event, progress: Progress) -> Path:
    if not kept:
        raise ValueError("저장할 프레임을 한 장 이상 남겨 주세요.")
    settings.validate()
    if kept != sorted(set(kept)) or kept[0] < 0 or kept[-1] >= expected_count:
        raise ValueError("프레임 선택 정보가 올바르지 않아요. 목록을 다시 생성해 주세요.")
    target = target.resolve()
    # Encode beside the destination, then replace atomically. Existing GIFs survive errors/cancel.
    handle, output_name = tempfile.mkstemp(prefix=".gif-export-", suffix=".gif", dir=target.parent)
    os.close(handle)
    pending = Path(output_name)
    try:
        with temporary_directory(prefix="gif-export-") as temp:
            directory = Path(temp)
            frames = extract_frames(video, settings, directory / "frames", cancel,
                                    progress, base=0, span=55)
            if len(frames) != expected_count:
                raise ValueError("영상의 프레임 수가 달라졌어요. 프레임 목록을 다시 생성해 주세요.")
            # ffconcat's default image time base is 25fps. Set each input to 100fps
            # so GIF's centisecond timestamps survive arbitrary FPS and exclusions.
            manifest = directory / "kept.ffconcat"
            lines = ["ffconcat version 1.0"]
            for position, index in enumerate(kept):
                if cancel.is_set():
                    raise Cancelled()
                relative = frames[index].relative_to(directory).as_posix()
                delay = max(1, round((position + 1) * 100 / settings.fps)
                            - round(position * 100 / settings.fps))
                lines += [f"file '{relative}'", "option framerate 100", f"duration {delay / 100:.2f}"]
            manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
            length = len(kept) / settings.fps
            palette = directory / "palette.png"
            concat = ["-f", "concat", "-safe", "0", "-i", str(manifest)]
            run_ffmpeg([*concat, "-vf", "palettegen=stats_mode=diff", "-frames:v", "1", str(palette)],
                       cancel, progress, length, 55, 20, "GIF 색상 준비 중…")
            final_delay = max(1, round(len(kept) * 100 / settings.fps)
                              - round((len(kept) - 1) * 100 / settings.fps))
            run_ffmpeg([*concat, "-i", str(palette), "-lavfi", "paletteuse=dither=sierra2_4a",
                        "-fps_mode", "passthrough", "-loop", "0" if loop else "-1",
                        "-final_delay", str(final_delay), str(pending)],
                       cancel, progress, length, 75, 25, "GIF 저장 중…")
            if cancel.is_set():
                raise Cancelled()
            os.replace(pending, target)
        return target
    finally:
        pending.unlink(missing_ok=True)
