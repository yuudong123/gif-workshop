# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 yuudong123
# See LICENSE for the full license text.

"""Bundle the app and FFmpeg so users need neither Python nor a separate codec install."""
from pathlib import Path
import os
import shutil
import subprocess
import sys

import imageio_ffmpeg


def main():
    root = Path(__file__).resolve().parent
    binary = Path(imageio_ffmpeg.get_ffmpeg_exe())
    licenses = root / "build" / "licenses"
    licenses.mkdir(parents=True, exist_ok=True)
    for package in ("PySide6", "shiboken6", "Pillow", "imageio_ffmpeg"):
        from importlib.metadata import distribution
        dist = distribution(package)
        for entry in dist.files or []:
            if "license" in str(entry).lower() or "copying" in str(entry).lower():
                source = Path(dist.locate_file(entry))
                if source.is_file():
                    target = licenses / package / Path(str(entry))
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    ffmpeg_license = subprocess.run([str(binary), "-L"], capture_output=True,
                                    encoding="utf-8", errors="replace", check=True)
    (licenses / "FFmpeg-build-license-and-version.txt").write_text(
        ffmpeg_license.stdout + ffmpeg_license.stderr, encoding="utf-8")
    # Keep unrelated tools (e.g. Poppler's incompatible ICU DLL) out of DLL discovery.
    build_environment = dict(os.environ)
    windows = Path(os.environ["SystemRoot"])
    build_environment["PATH"] = os.pathsep.join([
        str(Path(sys.executable).parent), str(windows / "System32"), str(windows),
    ])
    for key in ("QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QT_QPA_PLATFORM"):
        build_environment.pop(key, None)
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
        "--onefile", "--name", "GIF작업실", "--distpath", str(root),
        "--collect-data", "imageio_ffmpeg",
        "--add-binary", f"{binary};imageio_ffmpeg/binaries",
        "--add-data", f"{licenses};licenses",
        "--add-data", f"{root / 'README.md'};.",
        "--add-data", f"{root / 'THIRD_PARTY_NOTICES.txt'};.",
        "--add-data", f"{root / 'LICENSE'};.",
        "--add-data", f"{root / 'docs'};docs",
        "--exclude-module", "PySide6.QtWebEngineCore", "--exclude-module", "PySide6.QtWebEngineWidgets",
        "--exclude-module", "PySide6.QtQml", "--exclude-module", "PySide6.QtQuick",
        "--exclude-module", "cv2", "--exclude-module", "numpy", "--exclude-module", "matplotlib",
        "--exclude-module", "tkinter", str(root / "app.py"),
    ], cwd=root, env=build_environment, check=True)
    print(f"Ready: {root / 'GIF작업실.exe'}")


if __name__ == "__main__":
    main()
