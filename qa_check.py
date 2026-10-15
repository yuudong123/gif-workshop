# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 yuudong123
# See LICENSE for the full license text.

"""End-to-end checks with an actual encoded, numbered video and Qt window."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image, ImageDraw, ImageSequence
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app import MainWindow, STYLE
from gif_engine import Cancelled, ClipSettings, export_gif, extract_frames, ffmpeg, probe_video, process_options


ROOT = Path(__file__).resolve().parent / ".qa"
ROOT.mkdir(exist_ok=True)


def wait_for(app, condition, seconds=30):
    deadline = time.monotonic() + seconds
    while not condition():
        app.processEvents()
        QTest.qWait(20)
        if time.monotonic() > deadline:
            raise AssertionError("Qt operation timed out")
    app.processEvents()


def inspect_gif(path):
    with Image.open(path) as image:
        frames = [frame.convert("RGB").copy() for frame in ImageSequence.Iterator(image)]
        image.seek(0)
        durations = []
        for frame in ImageSequence.Iterator(image):
            durations.append(frame.info.get("duration", 0))
        return frames, durations, dict(image.info)


def main():
    input_dir = ROOT / "source"
    input_dir.mkdir(exist_ok=True)
    for i in range(40):
        image = Image.new("RGB", (160, 96), (20 + i * 5, 60, 100))
        draw = ImageDraw.Draw(image)
        draw.rectangle((8 + i * 3, 48, 18 + i * 3, 68), fill=(200, 225, 250))
        draw.text((8, 78), f"FRAME {i:02d}", fill="white")
        image.save(input_dir / f"frame-{i:06d}.png")
    source = ROOT / "검증 영상.mp4"
    subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-framerate", "10",
                    "-i", str(input_dir / "frame-%06d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    str(source)], check=True, **process_options())
    video = probe_video(source)
    assert abs(video.duration - 4) < 0.01 and video.width == 160 and video.height == 96
    cancel = threading.Event()
    silent = lambda *_: None
    config = ClipSettings(0.4, 2.4, 10, 128)
    previews = extract_frames(video, config, ROOT / "preview-10", cancel, silent, preview=True)
    assert len(previews) == 20, len(previews)
    kept = [i for i in range(20) if i not in {0, 5, 6, 19}]
    output = export_gif(video, config, kept, len(previews), ROOT / "프레임 제외.gif", True, cancel, silent)
    frames, durations, info = inspect_gif(output)
    assert len(frames) == 16, len(frames)
    assert frames[0].size == (128, 77), frames[0].size
    assert sum(durations) == 1600, durations
    assert info.get("loop") == 0, info
    for image, index in zip(frames, kept):
        expected_red = 20 + (index + 4) * 5
        assert abs(image.getpixel((20, 15))[0] - expected_red) <= 8, (index, image.getpixel((20, 15)), expected_red)

    config15 = ClipSettings(0, 1, 15, 320)
    previews15 = extract_frames(video, config15, ROOT / "preview-15", cancel, silent, preview=True)
    assert len(previews15) == 15
    keep15 = [i for i in range(15) if i not in {2, 6, 9}]
    gif15 = export_gif(video, config15, keep15, 15, ROOT / "15fps.gif", False, cancel, silent)
    frames15, delay15, info15 = inspect_gif(gif15)
    assert sum(delay15) == 800, delay15  # Duplicate samples may coalesce; duration must remain correct.
    assert frames15[0].size == (160, 96), frames15[0].size  # Never upscale.
    assert "loop" not in info15, info15

    single = export_gif(video, config15, [4], 15, ROOT / "single.gif", False, cancel, silent)
    single_frames, single_delay, _ = inspect_gif(single)
    assert len(single_frames) == 1 and sum(single_delay) == 70, single_delay

    existing = ROOT / "preserved.gif"
    original_bytes = output.read_bytes()
    existing.write_bytes(original_bytes)
    export_cancel = threading.Event()
    try:
        export_gif(video, config, kept, 20, existing, True, export_cancel,
                   lambda percent, _: export_cancel.set() if percent >= 55 else None)
        raise AssertionError("Cancellation did not propagate")
    except Cancelled:
        pass
    assert existing.read_bytes() == original_bytes
    assert not list(ROOT.glob(".gif-export-*"))
    for invalid in [ClipSettings(2, 1, 10, 128), ClipSettings(0, 61, 50, 128)]:
        try:
            invalid.validate()
            raise AssertionError("Invalid settings accepted")
        except ValueError:
            pass
    try:
        export_gif(video, config, [], 20, existing, True, cancel, silent)
        raise AssertionError("Empty selection accepted")
    except ValueError:
        pass
    assert existing.read_bytes() == original_bytes

    app = QApplication.instance() or QApplication([])
    # The Windows offscreen plugin has no system font database of its own.
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/malgun.ttf")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = MainWindow()
    window.show()
    errors = []
    window.job_failed = lambda message: errors.append(message)
    window.load_video(source)
    wait_for(app, lambda: window.worker is None and bool(window.frames))
    assert not errors, errors
    assert len(window.frames) == 60 and len(window.kept) == 60
    window.frame_list.setCurrentRow(3)
    window.change_selected(False)
    assert 3 not in window.kept and len(window.kept) == 59
    window.undo()
    assert len(window.kept) == 60
    item = window.frame_list.item(8)
    item.setCheckState(Qt.CheckState.Unchecked)
    assert 8 not in window.kept
    window.undo()
    assert 8 in window.kept
    window.toggle_play()
    assert window.timer.isActive()
    QTest.qWait(160)
    window.stop_play()
    assert window.current != 3
    window.start.setValue(0.5)
    assert window.dirty and not window.export_button.isEnabled()
    window.start.setValue(0)
    assert not window.dirty and window.export_button.isEnabled()
    window.width.setValue(96)
    assert not window.dirty and window.export_button.isEnabled()
    window.width.setValue(640)
    window.apply_changes([(i, False) for i in [5, 6, 7, 18, 19, 20, 37]])
    window.show_frame(18)
    app.processEvents()
    window.grab().save(str(ROOT / "app-preview.png"))
    window.resize(1000, 760)
    app.processEvents()
    window.grab().save(str(ROOT / "app-min-size.png"))
    window.restore_all()
    assert len(window.kept) == 60
    cache = window.cache
    window.close()
    app.processEvents()
    assert not cache.exists(), "Preview cache not cleaned up"

    report = {
        "source": "actual H.264 video, 4 seconds, 40 numbered frames",
        "trim_and_exclusion": {"source_range": [0.4, 2.4], "sampled": 20, "kept": 16,
                               "gif_frames": len(frames), "duration_ms": sum(durations), "size": [128, 77]},
        "fps15_duration_ms": sum(delay15),
        "single_frame_ms": sum(single_delay),
        "checks": ["frame identity and ordering", "loop on/off", "no upscale", "atomic cancellation",
                   "invalid settings", "all excluded", "Qt auto-load", "exclude/undo", "checkbox/undo",
                   "playback", "dirty settings block export", "width keeps selection", "cache cleanup"],
        "screenshots": ["app-preview.png", "app-min-size.png"],
    }
    (ROOT / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
