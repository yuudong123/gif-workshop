# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 yuudong123
# See LICENSE for the full license text.

"""Smoke-test the frozen app with Python/FFmpeg removed from PATH."""
import json
import os
from pathlib import Path
import subprocess
import sys

from PIL import Image, ImageSequence


root = Path(__file__).resolve().parent
executable = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else root / "GIF작업실.exe"
destination = root / ".qa" / "single-file"
destination.mkdir(exist_ok=True)
environment = dict(os.environ)
environment["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
for key in ("PYTHONPATH", "VIRTUAL_ENV", "IMAGEIO_FFMPEG_EXE", "QT_QPA_PLATFORM"):
    environment.pop(key, None)
subprocess.run([str(executable),
                "--verify", str(root / ".qa" / "검증 영상.mp4"), str(destination)],
               env=environment, cwd=executable.parent, timeout=90, check=True,
               creationflags=subprocess.CREATE_NO_WINDOW)
assert not (destination / "error.txt").exists(), (destination / "error.txt").read_text(encoding="utf-8")
report = json.loads((destination / "result.json").read_text(encoding="utf-8"))
assert report["frames"] == 60 and report["kept"] == 58, report
with Image.open(destination / "bundle.gif") as gif:
    duration = sum(frame.info["duration"] for frame in ImageSequence.Iterator(gif))
    assert gif.size == (160, 96)
    assert duration == 3870, duration
with Image.open(destination / "bundle-window.png") as screenshot:
    # Verify the final UI stylesheet survived packaging (visible purple save button).
    colors = screenshot.convert("RGB").getcolors(screenshot.width * screenshot.height)
    assert any(count > 1500 and color == (184, 170, 255) for count, color in colors)
report.update({"gif_duration_ms": duration, "python_and_ffmpeg_on_path": False, "native_ui": True})
(destination / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
