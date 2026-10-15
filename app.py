# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 yuudong123
# See LICENSE for the full license text.

from __future__ import annotations

import bisect
import math
from pathlib import Path
import shutil
import sys
import tempfile
import threading

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QSize, QUrl
from PySide6.QtGui import QAction, QColor, QDesktopServices, QIcon, QKeySequence, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDoubleSpinBox, QFileDialog, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QProgressBar, QPushButton, QSlider, QSpinBox, QSplitter, QVBoxLayout, QWidget,
    QAbstractItemView, QScrollArea,
)

from gif_engine import Cancelled, ClipSettings, MAX_FRAMES, export_gif, extract_frames, probe_video


def timestamp(seconds: float) -> str:
    total_ms = round(seconds * 1000)
    minutes, rest = divmod(total_ms, 60_000)
    secs, millis = divmod(rest, 1000)
    return f"{minutes:02d}:{secs:02d}.{millis:03d}"


class Worker(QThread):
    progress = Signal(int, str)
    result = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, job, parent=None):
        super().__init__(parent)
        self.job = job
        self.cancel_event = threading.Event()

    def run(self):
        try:
            value = self.job(self.cancel_event, self.progress.emit)
            if self.cancel_event.is_set():
                self.cancelled.emit()
            else:
                self.result.emit(value)
        except Cancelled:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(str(exc))


class RangeBar(QWidget):
    """Two draggable handles; the numeric fields also allow precise/keyboard edits."""
    changed = Signal(float, float)

    def __init__(self):
        super().__init__()
        self.duration = 1.0
        self.start = 0.0
        self.end = 1.0
        self.drag_handle = None
        self.setMinimumHeight(42)
        self.setToolTip("양쪽 손잡이를 드래그해서 영상 구간을 정하세요.")

    def set_range(self, duration, start, end):
        self.duration = max(0.001, duration)
        self.start, self.end = start, end
        self.update()

    def x_at(self, time):
        return 12 + (self.width() - 24) * time / self.duration

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        y = self.height() / 2
        painter.setPen(QPen(QColor("#333747"), 8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(12, round(y), self.width() - 12, round(y))
        painter.setPen(QPen(QColor("#a395ff"), 8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(round(self.x_at(self.start)), round(y), round(self.x_at(self.end)), round(y))
        painter.setPen(QPen(QColor("#bdb3ff"), 2))
        painter.setBrush(QColor("#eeeaff"))
        for value in (self.start, self.end):
            painter.drawRoundedRect(round(self.x_at(value)) - 5, round(y) - 11, 10, 22, 4, 4)

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        x = event.position().x()
        self.drag_handle = "start" if abs(x - self.x_at(self.start)) <= abs(x - self.x_at(self.end)) else "end"
        self.mouseMoveEvent(event)

    def mouseMoveEvent(self, event):
        if not self.drag_handle:
            return
        value = max(0.0, min(self.duration, (event.position().x() - 12) / max(1, self.width() - 24) * self.duration))
        gap = min(0.01, self.duration)
        if self.drag_handle == "start":
            self.start = min(value, self.end - gap)
        else:
            self.end = max(value, self.start + gap)
        self.changed.emit(round(self.start, 3), round(self.end, 3))
        self.update()

    def mouseReleaseEvent(self, event):
        self.drag_handle = None


class Preview(QLabel):
    def __init__(self):
        super().__init__()
        self.original = QPixmap()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(320, 210)
        self.setObjectName("preview")
        self.setText("영상을 여기로 놓아 주세요\n\n또는 위의 ‘영상 열기’를 눌러 시작해요")

    def set_frame(self, path):
        self.original = QPixmap(str(path))
        self.refresh()

    def refresh(self):
        if not self.original.isNull():
            self.setPixmap(self.original.scaled(self.size() - QSize(24, 24),
                           Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.refresh()


STYLE = """
QWidget { background: #15171e; color: #e8e9f0; font-family: 'Malgun Gothic'; font-size: 12px; }
QMainWindow { background: #15171e; }
QLabel#title { font-size: 23px; font-weight: 700; }
QLabel#brand { background: #b8aaff; color: #221b40; font-size: 25px; font-weight: 800; border-radius: 13px; }
QLabel#muted, QLabel#subtitle { color: #9299af; }
QLabel#section { font-size: 14px; font-weight: 700; }
QFrame#card { background: #1d202a; border: 1px solid #2c3040; border-radius: 12px; }
QFrame#card QLabel { background: transparent; }
QWidget#settingsContent, QWidget#settingsViewport, QWidget#exportArea { background: transparent; }
QLabel#preview { background: #0d0f15; border: 1px solid #2c3040; border-radius: 12px; color: #8f96ac; font-size: 15px; }
QScrollArea#settingsScroll { background: transparent; border: none; }
QPushButton { background: #2a2e3d; border: 1px solid #3b4054; border-radius: 7px; padding: 9px 13px; font-weight: 600; }
QPushButton:hover { background: #373c50; border-color: #8070c9; }
QPushButton:pressed { background: #44405e; }
QPushButton:disabled { background: #21242e; color: #646a7c; border-color: #2c3040; }
QPushButton#primary { background: #b8aaff; color: #221b40; border-color: #b8aaff; }
QPushButton#primary:hover { background: #cec3ff; }
QPushButton#primary:disabled { background: #48415e; border-color: #48415e; color: #8b839f; }
QPushButton#small { padding: 6px 10px; }
QSpinBox, QDoubleSpinBox { background: #12151d; border: 1px solid #3b4054; border-radius: 7px; padding: 7px 9px; min-height: 22px; }
QSpinBox:focus, QDoubleSpinBox:focus { border-color: #b8aaff; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #656b80; border-radius: 4px; background: #191c25; }
QCheckBox::indicator:checked { background: #b8aaff; border: 2px solid #e1d9ff; }
QListWidget { background: #11141c; border: 1px solid #303545; border-radius: 9px; padding: 7px; }
QListWidget::item { border-radius: 6px; padding: 4px; color: #c6cbda; }
QListWidget::item:selected { background: #413858; border: 1px solid #b8aaff; }
QListWidget::item:hover { background: #292d3c; }
QListWidget::indicator { width: 15px; height: 15px; }
QSlider::groove:horizontal { background: #333848; height: 5px; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #b8aaff; border-radius: 2px; }
QSlider::handle:horizontal { background: #e9e2ff; width: 12px; margin: -5px 0; border-radius: 6px; }
QProgressBar { border: none; background: #292d3b; border-radius: 3px; height: 6px; }
QProgressBar::chunk { background: #b8aaff; border-radius: 3px; }
QScrollBar:vertical { background: #191c25; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #494d60; border-radius: 4px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QSplitter::handle { background: #15171e; height: 10px; }
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GIF 작업실")
        self.resize(1280, 920)
        self.setMinimumSize(1000, 760)
        self.setAcceptDrops(True)
        self.video = None
        self.frames = []
        self.kept = []
        self.preview_settings = None
        self.cache = None
        self.pending_cache = None
        self.worker = None
        self.dirty = False
        self.current = 0
        self.last_output = None
        self.undo_stack = []
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.advance)
        self._build_ui()
        self._shortcuts()
        self.refresh_controls()

    @staticmethod
    def label(text, kind=None):
        label = QLabel(text)
        if kind:
            label.setObjectName(kind)
        return label

    @staticmethod
    def button(text, handler, kind=None):
        button = QPushButton(text)
        button.clicked.connect(handler)
        if kind:
            button.setObjectName(kind)
        return button

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        main = QVBoxLayout(root)
        main.setContentsMargins(24, 22, 24, 18)
        main.setSpacing(18)
        header = QHBoxLayout()
        brand = self.label("G", "brand")
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
        brand.setFixedSize(50, 50)
        header.addWidget(brand)
        heading = QVBoxLayout()
        heading.setSpacing(3)
        heading.addWidget(self.label("GIF 작업실", "title"))
        heading.addWidget(self.label("필요한 순간, 필요한 프레임만.", "subtitle"))
        header.addLayout(heading)
        header.addStretch()
        self.open_button = self.button("＋  영상 열기", self.choose_video)
        header.addWidget(self.open_button)
        main.addLayout(header)

        splitter = QSplitter(Qt.Orientation.Vertical)
        upper = QWidget()
        content = QHBoxLayout(upper)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(18)
        self.sidebar = QFrame()
        self.sidebar.setObjectName("card")
        self.sidebar.setFixedWidth(308)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)
        settings_scroll = QScrollArea()
        settings_scroll.setObjectName("settingsScroll")
        settings_scroll.setWidgetResizable(True)
        settings_scroll.viewport().setObjectName("settingsViewport")
        settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        settings_widget = QWidget()
        settings_widget.setObjectName("settingsContent")
        settings = QVBoxLayout(settings_widget)
        settings_scroll.setWidget(settings_widget)
        sidebar_layout.addWidget(settings_scroll, 1)
        settings.setContentsMargins(18, 18, 18, 18)
        settings.setSpacing(10)
        settings.addWidget(self.label("01  영상과 구간", "section"))
        self.file_label = self.label("아직 불러온 영상이 없어요")
        self.file_label.setWordWrap(True)
        settings.addWidget(self.file_label)
        self.info_label = self.label("MP4 · MOV · MKV · AVI · WEBM", "muted")
        self.info_label.setWordWrap(True)
        settings.addWidget(self.info_label)
        self.range_bar = RangeBar()
        self.range_bar.changed.connect(self.range_changed)
        settings.addWidget(self.range_bar)
        grid = QGridLayout()
        grid.addWidget(self.label("시작 (초)", "muted"), 0, 0)
        grid.addWidget(self.label("끝 (초)", "muted"), 0, 1)
        self.start = QDoubleSpinBox()
        self.end = QDoubleSpinBox()
        for spin in (self.start, self.end):
            spin.setDecimals(3)
            spin.setSingleStep(0.1)
            spin.setRange(0, 86_400)
            spin.valueChanged.connect(self.settings_changed)
        grid.addWidget(self.start, 1, 0)
        grid.addWidget(self.end, 1, 1)
        settings.addLayout(grid)
        settings.addWidget(self.label("02  프레임과 크기", "section"))
        grid2 = QGridLayout()
        grid2.addWidget(self.label("FPS · 초당 프레임", "muted"), 0, 0)
        grid2.addWidget(self.label("너비 (px)", "muted"), 0, 1)
        self.fps = QSpinBox()
        self.fps.setRange(1, 50)
        self.fps.setValue(15)
        self.fps.valueChanged.connect(self.settings_changed)
        self.width = QSpinBox()
        self.width.setRange(64, 1920)
        self.width.setValue(640)
        self.width.setSingleStep(64)
        self.width.valueChanged.connect(self.update_summary)
        grid2.addWidget(self.fps, 1, 0)
        grid2.addWidget(self.width, 1, 1)
        settings.addLayout(grid2)
        note = self.label("비율은 자동 유지 · 원본보다 확대하지 않아요", "muted")
        note.setWordWrap(True)
        settings.addWidget(note)
        self.loop = QCheckBox("GIF 반복 재생")
        self.loop.setChecked(True)
        settings.addWidget(self.loop)
        self.generate_button = self.button("프레임 불러오기", self.generate_frames)
        settings.addWidget(self.generate_button)
        self.summary = self.label("영상을 열면 프레임을 확인할 수 있어요", "muted")
        self.summary.setWordWrap(True)
        settings.addWidget(self.summary)
        settings.addStretch()
        self.export_button = self.button("GIF 저장하기  →", self.save_gif, "primary")
        self.export_button.setMinimumHeight(44)
        export_area = QWidget()
        export_area.setObjectName("exportArea")
        export_layout = QVBoxLayout(export_area)
        export_layout.setContentsMargins(18, 10, 18, 18)
        export_layout.addWidget(self.export_button)
        sidebar_layout.addWidget(export_area)
        content.addWidget(self.sidebar)

        preview_area = QVBoxLayout()
        preview_area.setSpacing(10)
        preview_header = QHBoxLayout()
        preview_header.addWidget(self.label("미리보기", "section"))
        preview_header.addStretch()
        self.preview_tag = self.label("선택한 구간의 프레임", "muted")
        preview_header.addWidget(self.preview_tag)
        preview_area.addLayout(preview_header)
        self.preview = Preview()
        preview_area.addWidget(self.preview, 1)
        controls = QHBoxLayout()
        self.prev_button = self.button("◀", lambda: self.step(-1), "small")
        self.play_button = self.button("▶  재생", self.toggle_play, "small")
        self.next_button = self.button("▶", lambda: self.step(1), "small")
        controls.addWidget(self.prev_button)
        controls.addWidget(self.play_button)
        controls.addWidget(self.next_button)
        self.scrubber = QSlider(Qt.Orientation.Horizontal)
        self.scrubber.valueChanged.connect(self.seek)
        controls.addWidget(self.scrubber, 1)
        self.position_label = self.label("00:00.000", "muted")
        self.position_label.setMinimumWidth(85)
        controls.addWidget(self.position_label)
        preview_area.addLayout(controls)
        content.addLayout(preview_area, 1)
        splitter.addWidget(upper)

        lower = QWidget()
        editor = QVBoxLayout(lower)
        editor.setContentsMargins(0, 0, 0, 0)
        editor.setSpacing(9)
        editor_header = QHBoxLayout()
        editor_header.addWidget(self.label("03  프레임 고르기", "section"))
        self.count_label = self.label("0 프레임", "muted")
        editor_header.addWidget(self.count_label)
        editor_header.addStretch()
        self.exclude_button = self.button("선택 제외", lambda: self.change_selected(False), "small")
        self.restore_button = self.button("선택 복원", lambda: self.change_selected(True), "small")
        self.all_button = self.button("전체 복원", self.restore_all, "small")
        editor_header.addWidget(self.exclude_button)
        editor_header.addWidget(self.restore_button)
        editor_header.addWidget(self.all_button)
        editor.addLayout(editor_header)
        self.frame_list = QListWidget()
        self.frame_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.frame_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.frame_list.setMovement(QListWidget.Movement.Static)
        self.frame_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.frame_list.setIconSize(QSize(140, 80))
        self.frame_list.setGridSize(QSize(164, 130))
        self.frame_list.setSpacing(3)
        self.frame_list.setUniformItemSizes(True)
        self.frame_list.setMinimumHeight(160)
        self.frame_list.currentRowChanged.connect(self.show_frame)
        self.frame_list.itemChanged.connect(self.item_changed)
        self.frame_list.itemDoubleClicked.connect(self.toggle_item)
        editor.addWidget(self.frame_list, 1)
        editor.addWidget(self.label("클릭으로 확인 · Ctrl / Shift로 여러 장 선택 · Delete로 제외 · Ctrl+Z로 되돌리기", "muted"))
        splitter.addWidget(lower)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([530, 245])
        main.addWidget(splitter, 1)

        footer = QHBoxLayout()
        self.status = self.label("영상 파일을 열거나 창에 드래그해 주세요.", "muted")
        footer.addWidget(self.status, 1)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedWidth(180)
        self.progress.hide()
        footer.addWidget(self.progress)
        self.cancel_button = self.button("취소", self.cancel_job, "small")
        self.cancel_button.hide()
        footer.addWidget(self.cancel_button)
        self.folder_button = self.button("저장 폴더 열기", self.open_output_folder, "small")
        self.folder_button.hide()
        footer.addWidget(self.folder_button)
        main.addLayout(footer)

    def _shortcuts(self):
        for keys, handler in [("Ctrl+O", self.choose_video), ("Ctrl+S", self.save_gif),
                              ("Delete", lambda: self.change_selected(False)),
                              ("Ctrl+Z", self.undo), ("Space", self.toggle_play)]:
            action = QAction(self)
            action.setShortcut(QKeySequence(keys))
            action.triggered.connect(handler)
            self.addAction(action)

    def settings(self):
        return ClipSettings(self.start.value(), self.end.value(), self.fps.value(), self.width.value())

    def refresh_controls(self):
        busy = self.worker is not None
        loaded = self.video is not None
        playable = bool(self.frames) and not busy and not self.dirty
        self.open_button.setEnabled(not busy)
        for control in (self.start, self.end, self.range_bar, self.fps, self.width, self.loop):
            control.setEnabled(loaded and not busy)
        self.generate_button.setEnabled(loaded and not busy)
        self.export_button.setEnabled(playable and bool(self.kept))
        for control in (self.prev_button, self.next_button, self.scrubber, self.exclude_button,
                        self.restore_button, self.all_button, self.frame_list):
            control.setEnabled(playable)
        self.play_button.setEnabled(playable and bool(self.kept))
        self.progress.setVisible(busy)
        self.cancel_button.setVisible(busy)

    def launch_job(self, job, callback, status):
        if self.worker:
            return
        self.stop_play()
        self.status.setText(status)
        self.progress.setValue(0)
        worker = Worker(job, self)
        self.worker = worker
        worker.progress.connect(self.job_progress)
        worker.result.connect(callback)
        worker.failed.connect(self.job_failed)
        worker.cancelled.connect(lambda: self.status.setText("작업을 취소했어요."))
        worker.finished.connect(self.job_finished)
        self.refresh_controls()
        worker.start()

    def job_progress(self, percent, text):
        self.progress.setValue(percent)
        self.status.setText(f"{text}  {percent}%")

    def job_failed(self, message):
        self.status.setText("처리하지 못했어요. 설정이나 영상 파일을 확인해 주세요.")
        QMessageBox.warning(self, "처리 실패", message)

    def job_finished(self):
        worker = self.worker
        self.worker = None
        if worker:
            worker.deleteLater()
        if self.pending_cache:
            shutil.rmtree(self.pending_cache, ignore_errors=True)
            self.pending_cache = None
        self.refresh_controls()
        if getattr(self, "auto_generate", False):
            self.auto_generate = False
            QTimer.singleShot(0, self.generate_frames)

    def cancel_job(self):
        if self.worker:
            self.worker.cancel_event.set()
            self.cancel_button.setEnabled(False)
            self.status.setText("취소하는 중…")

    def choose_video(self):
        if self.worker:
            return
        path, _ = QFileDialog.getOpenFileName(self, "영상 열기", "",
                "영상 (*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.wmv *.mpeg *.mpg *.ts *.gif);;모든 파일 (*)")
        if path:
            self.load_video(Path(path))

    def load_video(self, path):
        if self.worker:
            return
        if not path.is_file():
            QMessageBox.warning(self, "파일 없음", "영상 파일을 찾을 수 없어요.")
            return
        self.cancel_button.setEnabled(True)
        self.launch_job(lambda cancel, progress: probe_video(path), self.video_loaded, "영상 정보 읽는 중…")

    def video_loaded(self, video):
        self.clear_frames()
        self.video = video
        self.file_label.setText(video.path.name)
        self.file_label.setToolTip(str(video.path))
        self.info_label.setText(f"{video.width} × {video.height}  ·  {video.fps:g} FPS\n길이 {timestamp(video.duration)}")
        for spin in (self.start, self.end):
            spin.blockSignals(True)
            spin.setMaximum(video.duration)
        self.start.setValue(0)
        self.end.setValue(min(video.duration, 5))
        for spin in (self.start, self.end):
            spin.blockSignals(False)
        self.range_bar.set_range(video.duration, 0, self.end.value())
        self.status.setText("영상을 불러왔어요. 처음 5초의 프레임을 준비할게요.")
        self.auto_generate = True
        self.update_summary()

    def range_changed(self, start, end):
        self.start.blockSignals(True)
        self.end.blockSignals(True)
        self.start.setValue(start)
        self.end.setValue(end)
        self.start.blockSignals(False)
        self.end.blockSignals(False)
        self.settings_changed()

    def settings_changed(self):
        self.stop_play()
        if self.video:
            self.range_bar.set_range(self.video.duration, self.start.value(), self.end.value())
        current = self.settings()
        old = self.preview_settings
        self.dirty = bool(self.frames) and bool(old) and (current.start, current.end, current.fps) != (old.start, old.end, old.fps)
        self.update_summary()
        if self.frames and not self.dirty:
            self.show_frame(self.current)
        self.refresh_controls()

    def update_summary(self):
        if not self.video:
            return
        config = self.settings()
        estimate = max(0, math.ceil(config.duration * config.fps))
        if self.dirty:
            self.summary.setText(f"설정이 바뀌었어요 · 약 {estimate:,}프레임\n‘프레임 불러오기’를 눌러 적용해 주세요.")
            self.preview_tag.setText("설정 변경됨 · 목록을 다시 불러와 주세요")
        elif self.frames:
            count = len(self.kept)
            self.summary.setText(f"{count:,}프레임 · GIF 약 {count / config.fps:.2f}초\n출력 너비 최대 {config.width}px")
        else:
            self.summary.setText(f"선택 구간 {max(0, config.duration):.2f}초 · 약 {estimate:,}프레임\n최대 {MAX_FRAMES:,}프레임까지 편집 가능")

    def generate_frames(self):
        if self.worker or not self.video:
            return
        config = self.settings()
        try:
            config.validate()
        except ValueError as exc:
            QMessageBox.information(self, "구간 확인", str(exc))
            return
        if any(self.frame_list.item(i).checkState() == Qt.CheckState.Unchecked for i in range(len(self.frames))):
            answer = QMessageBox.question(self, "프레임 다시 불러오기", "프레임 목록을 다시 만들면 제외한 프레임이 초기화돼요. 계속할까요?")
            if answer != QMessageBox.StandardButton.Yes:
                return
        directory = Path(tempfile.mkdtemp(prefix="gif-preview-"))
        self.pending_cache = directory
        video = self.video
        self.cancel_button.setEnabled(True)
        self.launch_job(lambda cancel, progress: (extract_frames(video, config, directory, cancel, progress, preview=True), config, directory),
                        self.frames_loaded, "프레임 불러오는 중…")

    def frames_loaded(self, result):
        frames, config, directory = result
        self.clear_frames()
        self.cache = directory
        self.pending_cache = None
        self.frames = frames
        self.preview_settings = config
        self.dirty = False
        self.frame_list.blockSignals(True)
        for index, path in enumerate(frames):
            pixmap = QPixmap(str(path)).scaled(140, 80, Qt.AspectRatioMode.KeepAspectRatio,
                                              Qt.TransformationMode.SmoothTransformation)
            item = QListWidgetItem(QIcon(pixmap), self.item_text(index, True))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setToolTip(f"원본 {timestamp(config.start + index / config.fps)}\n체크 해제 또는 Delete로 제외")
            self.frame_list.addItem(item)
        self.frame_list.blockSignals(False)
        self.scrubber.setRange(0, len(frames) - 1)
        self.update_kept()
        self.frame_list.setCurrentRow(0)
        self.show_frame(0)
        self.status.setText(f"{len(frames):,}프레임 준비 완료. 빼고 싶은 프레임을 선택해 주세요.")

    def item_text(self, index, enabled):
        config = self.preview_settings
        return f"{index + 1:04d} · {timestamp(config.start + index / config.fps)}\n{'사용' if enabled else '× 제외'}"

    def item_changed(self, item):
        index = item.data(Qt.ItemDataRole.UserRole)
        enabled = item.checkState() == Qt.CheckState.Checked
        self.undo_stack.append([(index, not enabled)])
        self.frame_list.blockSignals(True)
        self.decorate_item(item)
        self.frame_list.blockSignals(False)
        self.update_kept()

    def decorate_item(self, item):
        enabled = item.checkState() == Qt.CheckState.Checked
        item.setText(self.item_text(item.data(Qt.ItemDataRole.UserRole), enabled))
        item.setForeground(QColor("#c6cbda" if enabled else "#ee9aaa"))

    def apply_changes(self, changes, record=True):
        previous = []
        self.frame_list.blockSignals(True)
        for index, enabled in changes:
            item = self.frame_list.item(index)
            old = item.checkState() == Qt.CheckState.Checked
            if old == enabled:
                continue
            previous.append((index, old))
            item.setCheckState(Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked)
            self.decorate_item(item)
        self.frame_list.blockSignals(False)
        if previous and record:
            self.undo_stack.append(previous)
        self.update_kept()

    def change_selected(self, enabled):
        if self.worker or self.dirty:
            return
        self.apply_changes([(item.data(Qt.ItemDataRole.UserRole), enabled) for item in self.frame_list.selectedItems()])

    def restore_all(self):
        if not self.worker and not self.dirty:
            self.apply_changes([(i, True) for i in range(len(self.frames))])

    def toggle_item(self, item):
        self.apply_changes([(item.data(Qt.ItemDataRole.UserRole), item.checkState() != Qt.CheckState.Checked)])

    def undo(self):
        if not self.worker and not self.dirty and self.undo_stack:
            self.apply_changes(self.undo_stack.pop(), record=False)

    def update_kept(self):
        self.kept = [i for i in range(len(self.frames)) if self.frame_list.item(i).checkState() == Qt.CheckState.Checked]
        self.count_label.setText(f"전체 {len(self.frames):,}  ·  사용 {len(self.kept):,}  ·  제외 {len(self.frames) - len(self.kept):,}")
        self.update_summary()
        if self.frames:
            self.show_frame(self.current)
        if not self.kept:
            self.stop_play()
        self.refresh_controls()

    def show_frame(self, index):
        if not 0 <= index < len(self.frames):
            return
        self.current = index
        self.preview.set_frame(self.frames[index])
        self.scrubber.blockSignals(True)
        self.scrubber.setValue(index)
        self.scrubber.blockSignals(False)
        config = self.preview_settings
        self.position_label.setText(timestamp(config.start + index / config.fps))
        excluded = self.frame_list.item(index).checkState() == Qt.CheckState.Unchecked
        if not self.dirty:
            self.preview_tag.setText(f"{index + 1:,} / {len(self.frames):,} 프레임{'  ·  제외됨' if excluded else ''}")

    def seek(self, index):
        self.stop_play()
        self.frame_list.setCurrentRow(index)
        self.show_frame(index)

    def step(self, direction):
        if not self.frames or self.worker or self.dirty:
            return
        self.seek(max(0, min(len(self.frames) - 1, self.current + direction)))

    def stop_play(self):
        self.timer.stop()
        self.play_button.setText("▶  재생")

    def toggle_play(self):
        if not self.kept or self.worker or self.dirty:
            return
        if self.timer.isActive():
            self.stop_play()
        else:
            if self.current not in self.kept:
                position = bisect.bisect_left(self.kept, self.current)
                self.show_frame(self.kept[position % len(self.kept)])
            self.timer.start(round(1000 / self.preview_settings.fps))
            self.play_button.setText("Ⅱ  일시정지")

    def advance(self):
        if not self.kept:
            self.stop_play()
            return
        position = bisect.bisect_right(self.kept, self.current)
        if position == len(self.kept) and not self.loop.isChecked():
            self.stop_play()
            return
        self.show_frame(self.kept[position % len(self.kept)])

    def save_gif(self):
        if self.worker or self.dirty or not self.kept or not self.video:
            return
        default = str(self.video.path.with_name(self.video.path.stem + "_gif.gif"))
        dialog = QFileDialog(self, "GIF 저장", default, "GIF 이미지 (*.gif)")
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.setDefaultSuffix("gif")
        if dialog.exec() != QFileDialog.DialogCode.Accepted:
            return
        target = Path(dialog.selectedFiles()[0])
        if target.suffix.lower() != ".gif":
            target = Path(str(target) + ".gif")
        if target.resolve() == self.video.path.resolve():
            QMessageBox.warning(self, "저장 경로 확인", "원본 영상과 다른 이름으로 저장해 주세요.")
            return
        config, video = self.settings(), self.video
        kept, count, loop = list(self.kept), len(self.frames), self.loop.isChecked()
        self.folder_button.hide()
        self.cancel_button.setEnabled(True)
        self.launch_job(lambda cancel, progress: export_gif(video, config, kept, count, target, loop, cancel, progress),
                        self.gif_saved, "GIF 저장 중…")

    def gif_saved(self, path):
        self.last_output = path
        size = path.stat().st_size / 1024 / 1024
        self.status.setText(f"저장 완료 · {path.name} · {size:.2f} MB")
        self.status.setToolTip(str(path))
        self.folder_button.show()

    def open_output_folder(self):
        if self.last_output:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_output.parent)))

    def clear_frames(self):
        self.stop_play()
        self.frame_list.blockSignals(True)
        self.frame_list.clear()
        self.frame_list.blockSignals(False)
        self.frames = []
        self.kept = []
        self.undo_stack = []
        self.preview_settings = None
        self.dirty = False
        self.preview.original = QPixmap()
        self.preview.clear()
        self.preview.setText("프레임을 준비하고 있어요…")
        if self.cache:
            shutil.rmtree(self.cache, ignore_errors=True)
            self.cache = None

    def dragEnterEvent(self, event):
        if not self.worker and event.mimeData().hasUrls() and any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        if self.worker:
            return
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.load_video(Path(url.toLocalFile()))
                event.acceptProposedAction()
                break

    def closeEvent(self, event):
        if self.worker:
            self.worker.cancel_event.set()
            self.worker.wait()
        if self.pending_cache:
            shutil.rmtree(self.pending_cache, ignore_errors=True)
        self.clear_frames()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("GIF 작업실")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = MainWindow()
    window.show()
    if len(sys.argv) == 4 and sys.argv[1] == "--verify":
        # Exercise the same workers and encoder from the frozen executable.
        import json
        destination = Path(sys.argv[3]).resolve()
        destination.mkdir(parents=True, exist_ok=True)
        stage = {"value": "load", "ticks": 0}
        verification_timer = QTimer(window)

        def fail(message):
            (destination / "error.txt").write_text(message, encoding="utf-8")
            app.exit(1)

        window.job_failed = fail

        def verify():
            stage["ticks"] += 1
            if stage["ticks"] > 600:
                fail("Bundle verification timed out")
                return
            if window.worker:
                return
            if stage["value"] == "load" and window.frames:
                window.apply_changes([(1, False), (3, False)])
                window.grab().save(str(destination / "bundle-window.png"))
                config = window.settings()
                kept = list(window.kept)
                count = len(window.frames)
                video = window.video
                stage["value"] = "export"
                window.launch_job(lambda cancel, progress: export_gif(video, config, kept, count,
                                  destination / "bundle.gif", True, cancel, progress),
                                  window.gif_saved, "실행 파일 확인 중…")
            elif stage["value"] == "export" and window.last_output:
                (destination / "result.json").write_text(json.dumps({
                    "frames": len(window.frames), "kept": len(window.kept),
                    "gif": str(window.last_output), "ffmpeg": "bundled",
                }), encoding="utf-8")
                verification_timer.stop()
                window.close()
                app.quit()

        verification_timer.timeout.connect(verify)
        verification_timer.start(100)
        window.load_video(Path(sys.argv[2]))
        sys.exit(app.exec())
    if len(sys.argv) > 1:
        QTimer.singleShot(0, lambda: window.load_video(Path(sys.argv[1])))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
