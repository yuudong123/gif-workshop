# GIF Workshop

A small Windows desktop app for turning a selected video range into a GIF. Adjust the frame rate, remove individual frames, preview the result, and export. No video effects or audio editing.

[한국어 사용법](docs/README.ko.md)

![GIF Workshop interface](docs/images/screenshot.png)

The interface currently uses Korean labels. The guide below includes the corresponding button names.

## Features

- Open a video with the file picker or drag and drop.
- Set the start/end time using numeric fields or draggable range handles.
- Choose the sampling rate: **1–50 FPS**.
- Select one or several frames to exclude, restore them, or undo the change.
- Preview the retained frames in playback order.
- Set the output width: **64–1920 px**, preserving the frame proportions without upscaling.
- Save a looping or non-looping GIF, with progress reporting and cancellation.

## Run

### Portable executable

If you have a built copy, double-click **`GIF작업실.exe`**. The executable includes the runtime and FFmpeg, so no Python installation or separate FFmpeg setup is needed. You can move the executable to another folder by itself.

This repository contains the source and build scripts. Generated executables are excluded from Git; use the build instructions below to create your own copy.

### From source

Requirements: **Windows x64** and **Python 3.11 or newer**.

```powershell
git clone https://github.com/yuudong123/gif-workshop.git
cd gif-workshop
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

FFmpeg is supplied by `imageio-ffmpeg`; no system-wide FFmpeg installation is required.

## Usage

1. Click **Open video** (`영상 열기`) or drop a video file onto the window. The app automatically prepares the first **up to 5 seconds**.
2. Set **Start** (`시작`) and **End** (`끝`) in seconds, or drag the two handles on the range bar.
3. Set **FPS**, then click **Load frames** (`프레임 불러오기`). Changing the range or FPS requires rebuilding the frame list. Rebuilding resets exclusions; the app asks before discarding existing exclusions.
4. Click a thumbnail to inspect a frame. Use **Ctrl** or **Shift** to select multiple frames, then click **Exclude selected** (`선택 제외`) or press **Delete**. Checkboxes and double-clicking also toggle whether a frame is included.
5. Use **Restore selected** (`선택 복원`), **Restore all** (`전체 복원`), or **Ctrl+Z** to undo an exclusion. Playback skips excluded frames.
6. Set **Width** (`너비`) and **Loop GIF** (`GIF 반복 재생`), then click **Save GIF** (`GIF 저장하기`). Choose an output filename.

Excluded frames also lose their time in the exported GIF: keeping 16 frames at 10 FPS produces approximately 1.6 seconds. Changing only the output width preserves your frame selections.

## Keyboard shortcuts

| Shortcut | Action |
| --- | --- |
| Ctrl+O | Open a video |
| Ctrl+S | Save a GIF |
| Space | Play / pause preview |
| Delete | Exclude selected frames |
| Ctrl+Z | Undo the last inclusion/exclusion change |

## Limits and behavior

- A clip can contain at most **3,000 sampled frames**. Shorten the range or lower the FPS for longer videos.
- Common video containers such as MP4, MOV, MKV, AVI, and WEBM are handled through FFmpeg. Actual support depends on the codec and the condition of the file.
- GIF timing is stored in **10 ms increments**. The encoder distributes frame delays to approximate the selected FPS; playback can vary between viewers.
- GIF output has no audio. Preview frames are limited to 640 px in width; export re-extracts the selected frames from the original video at the requested output size.
- The app uses temporary disk space for frames. Higher resolutions and longer clips require more space and processing time.
- The input video is never modified. Failed or cancelled exports preserve an existing destination GIF.

## Build a single executable

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe build_app.py
```

Output: **`GIF작업실.exe`** in the project directory. The build includes FFmpeg, documentation, and license notices. DLL discovery is restricted during packaging to avoid collecting incompatible libraries from unrelated tools.

## Verification

```powershell
.\.venv\Scripts\python.exe qa_check.py
.\.venv\Scripts\python.exe verify_bundle.py
```

`qa_check.py` generates an actual H.264 test video and checks trimming, frame identity/order, exclusions, timing, loop settings, cancellation, and editor behavior. It also saves screenshots and a report under `.qa/`.

`verify_bundle.py` runs the built executable with Python and FFmpeg removed from `PATH`, then verifies a GIF export. It briefly opens the app and closes it when the check finishes. These checks use generated test footage; they do not establish compatibility with every video codec or viewer.

## License

Copyright © 2026 yuudong123. This project's original source is licensed under **GPL-3.0-or-later**. See [LICENSE](LICENSE).

Dependencies retain their own licenses. See [third-party notices](THIRD_PARTY_NOTICES.txt) for Qt/PySide6, Pillow, imageio-ffmpeg, and FFmpeg details, including requirements for redistributing binary builds.
