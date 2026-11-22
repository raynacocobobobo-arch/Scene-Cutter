#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""镜头切片 第3.4版 — 居中截图灵敏度与清晰的手动截图操作。"""
from __future__ import annotations

import sys
import os
import threading
from pathlib import Path

# Use Qt's default multimedia backend. In 3.1 a forced macOS `darwin`
# backend could produce a black viewer for some codecs; the reported app-exit
# crash was in QPushButton destruction and did not implicate playback.
# For a machine that prefers AVFoundation, set QT_MEDIA_BACKEND=darwin in the
# shell before launching. Frame extraction always uses standalone FFmpeg.

from PySide6.QtCore import Qt, QSize, QThread, Signal, QUrl, QTimer, QCoreApplication, QEvent
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QImageReader, QPainter, QPen, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from shot_wall import ShotWallDialog
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFrame,
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QSlider, QSplitter,
    QVBoxLayout, QWidget,
)

from scene_engine import (
    ExtractionCancelled, ExtractionResult, SessionStore, Shot,
    capture_manual_frame, collect_videos, exclude_shot, export_contact_sheets,
    extract_scenes, find_program, format_time, pending_jobs,
    restore_last_excluded, remove_duplicate_existing_shots, video_fingerprint,
    prune_completed_queue, plan_reimport,
)
from crashlog import install_crash_logging, log_exception, log_event, log_path

PREVIEW_PER_PAGE = 48


def application_icon_path() -> Path:
    """macOS 应用图标：开发运行和 PyInstaller .app 使用相同 PNG 资源。"""
    return Path(__file__).resolve().parent / 'assets' / 'app_icon.png'


STYLE = """
QMainWindow, QWidget#root { background-color: #F7F5F0; }
QWidget { color: #151515; font-family: 'Helvetica Neue', 'PingFang SC', sans-serif; font-size: 12px; }
QLabel#title { font-family: 'PingFang SC', 'Heiti SC', sans-serif; font-size: 29px; font-weight: 800; }
QLabel#version { font-size: 11px; border: 1px solid #1B1B1B; padding: 2px 5px; }
QLabel#sectionTitle { font-size: 14px; font-weight: 750; }
QLabel#sensitivityTitle { font-size: 23px; font-weight: 800; color: #111111; }
QLabel#sensitivityValue { font-size: 19px; font-weight: 800; color: #111111; }
QLabel#muted { color: #575650; font-size: 12px; }
QLabel#dim { color: #696861; font-size: 11px; }
QLabel#value { font-weight: 700; font-size: 15px; }
QFrame#hairline { background-color: #111111; border: none; }
QFrame#fineLine { background-color: #ADA9A1; border: none; }
QFrame#dropArea { background-color: transparent; border: 1px dashed #77736D; }
QFrame#dropArea[active="true"] { background-color: #E5E2DA; border: 2px dashed #191919; }
QFrame#videoStage { background-color: #090909; border: 1px solid #111111; }
QPushButton { border: 1px solid #292929; border-radius: 0px; padding: 6px 10px;
              background-color: transparent; font-weight: 550; min-height: 16px; }
QPushButton:hover:enabled { background-color: #E8E4DA; }
QPushButton:pressed:enabled { background-color: #D8D4CA; }
QPushButton#primary { background-color: #168640; color: #FFFFFF; border: 2px solid #0E7432; font-size: 16px; font-weight: 800; min-height: 43px; min-width: 172px; }
QPushButton#primary:hover:enabled { background-color: #0E7334; border: 2px solid #075828; }
QPushButton#primary:pressed:enabled { background-color: #095C29; }
QPushButton#primary:disabled { background-color: #C4D7C9; color: #527A5E; border-color: #B2C6B7; }
QPushButton#setup { background-color: #111111; color: white; border: 1px solid #111111; font-weight: 700; }
QPushButton#setup:hover:enabled { background-color: #333333; }
QPushButton#quiet { border: none; background: transparent; }
QPushButton#capture { color: #FFFFFF; background-color: #181818; border: 1px solid #181818; font-size: 14px; font-weight: 700; min-height: 30px; }
QPushButton#capture:hover:enabled { background-color: #383838; }
QPushButton#capture:pressed:enabled { background-color: #080808; }
QPushButton:disabled { color: #A5A198; border-color: #C6C2B9; }
QListWidget { background-color: transparent; border: 0px; outline: none; }
QListWidget::item { border: 1px solid transparent; padding: 4px 6px; margin: 2px 0px; }
QListWidget::item:selected { background-color: #171717; color: #FFFFFF; }
QListWidget::item:hover { border: 1px solid #959087; }
QSlider::groove:horizontal { height: 3px; background: #B9B6AF; }
QSlider::handle:horizontal { width: 10px; background: #111111; margin: -6px 0; border-radius: 0px; }
QProgressBar { border: 1px solid #B6B2A9; border-radius: 0px; text-align: center;
               background-color: #E8E5DE; min-height: 12px; color: #111111; font-size: 10px; }
QProgressBar::chunk { background-color: #6C6B65; }
QDoubleSpinBox, QComboBox { background-color: transparent; border: 1px solid #8D8981;
                             border-radius: 0px; padding: 5px 6px; }
QComboBox::drop-down { border: none; width: 24px; }
QCheckBox { color: #575650; font-size: 11px; spacing: 6px; }
QSplitter#mainSplitter::handle { background-color: #AAA69C; margin: 6px 4px; }
QScrollBar:vertical { background: #F7F5F0; width: 7px; }
QScrollBar::handle:vertical { background: #AAA69D; min-height: 35px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
"""


def label(text: str, kind: str = '') -> QLabel:
    obj = QLabel(text)
    obj.setTextFormat(Qt.TextFormat.PlainText)
    if kind:
        obj.setObjectName(kind)
    return obj


def card() -> tuple[QFrame, QVBoxLayout]:
    box = QFrame()
    box.setObjectName('card')
    layout = QVBoxLayout(box)
    layout.setContentsMargins(15, 13, 15, 13)
    layout.setSpacing(9)
    return box, layout


class InkFigureLabel(QLabel):
    """Decorative ink figure: intentionally static, without click-to-enlarge."""

    def __init__(self, path: str):
        super().__init__()
        # An illustration is not an interactive control: no hand pointer,
        # tooltip, mouse handler, preview dialog or accidental click action.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        source = QPixmap(path)
        if not source.isNull():
            # 2x physical pixel density for Retina; render from the HD source.
            pix = source.scaledToHeight(320, Qt.TransformationMode.SmoothTransformation)
            pix.setDevicePixelRatio(2.0)
            self.setPixmap(pix)


class DropPanel(QFrame):
    paths_dropped = Signal(list)

    def __init__(self):
        super().__init__()
        self.setObjectName('dropArea')
        self.setAcceptDrops(True)
        self.setMinimumHeight(88)
        self.setMaximumHeight(105)
        pane = QVBoxLayout(self)
        big = label('拖入视频或整个文件夹')
        big.setAlignment(Qt.AlignmentFlag.AlignCenter)
        big.setStyleSheet('font-size: 15px; font-weight: 650;')
        small = label('支持常见视频格式 · 可重复导入已处理视频', 'dim')
        small.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pane.addStretch()
        pane.addWidget(big)
        pane.addWidget(small)
        pane.addStretch()

    def _active(self, active: bool) -> None:
        self.setProperty('active', 'true' if active else 'false')
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._active(True)
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._active(False)
        event.accept()

    def dropEvent(self, event):
        self._active(False)
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.paths_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            event.ignore()


class MarkerSlider(QSlider):
    """Seek bar with clickable position and detected-cut markers."""

    jumped = Signal(int)

    def __init__(self):
        super().__init__(Qt.Orientation.Horizontal)
        self.points: list[float] = []

    def set_markers(self, positions: list[float]) -> None:
        self.points = positions
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.points or self.maximum() <= 0:
            return
        painter = QPainter(self)
        painter.setPen(QPen(QColor('#121212'), 1))
        max_v = self.maximum()
        # Avoid painting exactly over the slider handle at the edges.
        usable = max(1, self.width() - 18)
        for p in self.points:
            x = 9 + int(usable * max(0.0, min(1.0, p / max_v)))
            painter.drawLine(x, 1, x, 8)
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            ratio = max(0.0, min(1.0, (event.position().x() - 9) / max(1, self.width() - 18)))
            value = int(self.minimum() + ratio * (self.maximum() - self.minimum()))
            self.setValue(value)
            self.jumped.emit(value)
        super().mousePressEvent(event)


class BatchWorker(QThread):
    started_video = Signal(int)
    progress_video = Signal(int, float)
    completed_video = Signal(int, object)
    failed_video = Signal(int, str)
    batch_done = Signal(bool)

    def __init__(self, jobs: list[tuple[int, Path]], sensitivity: float,
                 output_root: Path | None):
        super().__init__()
        self.jobs = jobs
        self.sensitivity = sensitivity
        self.output_root = output_root
        self.cancel_event = threading.Event()

    def cancel(self) -> None:
        self.cancel_event.set()

    def run(self) -> None:
        cancelled = False
        for index, video in self.jobs:
            if self.cancel_event.is_set():
                cancelled = True
                break
            self.started_video.emit(index)
            try:
                result = extract_scenes(
                    video, self.sensitivity,
                    on_progress=lambda value, idx=index: self.progress_video.emit(idx, value),
                    cancel=self.cancel_event, output_root=self.output_root,
                )
                self.completed_video.emit(index, result)
            except ExtractionCancelled:
                cancelled = True
                break
            except Exception as exc:
                self.failed_video.emit(index, str(exc))
        self.batch_done.emit(cancelled or self.cancel_event.is_set())


class SceneCutterWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('镜头切片 第3.4版 — 视频截图')
        self.resize(1560, 930)
        self.setMinimumSize(1140, 730)
        self.store = SessionStore()
        self.files, self.states, self.results, settings = self.store.restored()
        self.history, self.history_order = self.store.restored_history(settings, self.results)
        self.results.update(self.history)
        self.auto_clear_completed = bool(settings.get('auto_clear_completed', True))
        self.current_view_path: Path | None = None
        configured_root = settings.get('output_root')
        self.output_root: Path | None = Path(configured_root) if configured_root else None
        self.sensitivity = max(0, min(100, int(settings.get('sensitivity', 75))))
        self.worker: BatchWorker | None = None
        self.close_after_stop = False
        self.active_jobs: list[tuple[int, Path]] = []
        self.job_positions: dict[int, int] = {}
        self.batch_ok = 0
        self.batch_errors = 0
        self.current_index = -1
        self.loaded_video: Path | None = None
        self.preview_page = 0
        self._slider_dragging = False
        self._preview_maximized = False
        self._build_ui()
        if self.output_root and self.output_root.is_dir():
            self.top_output.setText('更改截图保存位置')
            self.status.setText(f'已就绪 · 截图保存至：{self.output_root}')
        self._fill_queue()
        self._refresh_history_combo()
        if self.history_order:
            # Restart with the latest screenshot preview visible, even when
            # pending queue items were saved in the prior session.
            self._show_result(self.history_order[-1])
        elif self.files:
            self.queue_list.setCurrentRow(0)
        self._refresh_buttons()

    def _build_ui(self) -> None:
        outer = QWidget()
        outer.setObjectName('root')
        self.setCentralWidget(outer)
        root = QVBoxLayout(outer)
        root.setContentsMargins(22, 12, 22, 14)
        root.setSpacing(12)

        # Editorial, ink-and-paper masthead. The viewer—not the illustration—is
        # the focal point, and screenshot colors are never altered.
        top = QHBoxLayout()
        top.setSpacing(12)
        top.addWidget(label('镜头切片', 'title'))
        top.addWidget(label('第3.4版', 'version'))
        top.addSpacing(14)
        top.addWidget(label('视频截图 / 画面预览 / 手动补图', 'muted'))
        top.addStretch()
        self.open_log = QPushButton('运行日志')
        self.open_log.setObjectName('quiet')
        self.open_log.setToolTip(f'运行记录位置：{log_path()}')
        self.open_log.clicked.connect(self._open_log)
        top.addWidget(self.open_log)
        self.top_output = QPushButton('设置截图保存位置')
        self.top_output.setObjectName('setup')
        self.top_output.setToolTip('所有视频的 JPG 集中保存到这里；软件会记住选择')
        self.top_output.clicked.connect(self._choose_output)
        top.addWidget(self.top_output)
        root.addLayout(top)
        line = QFrame()
        line.setObjectName('hairline')
        line.setFixedHeight(2)
        root.addWidget(line)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName('mainSplitter')
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(9)
        root.addWidget(splitter, 1)

        # QUEUE — narrow, airy; the tiny figure stays at the bottom of the
        # column and never competes with the actual video preview.
        left = QWidget()
        left.setMinimumWidth(190)
        left.setMaximumWidth(295)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 6, 5, 0)
        ll.setSpacing(11)
        ll.addWidget(label('视频队列', 'sectionTitle'))
        tools = QHBoxLayout()
        self.add_video = QPushButton('＋ 视频')
        self.add_folder = QPushButton('＋ 文件夹')
        self.add_video.clicked.connect(self._choose_files)
        self.add_folder.clicked.connect(self._choose_folder)
        tools.addWidget(self.add_video)
        tools.addWidget(self.add_folder)
        ll.addLayout(tools)
        self.drop = DropPanel()
        self.drop.paths_dropped.connect(self._add_paths)
        ll.addWidget(self.drop)
        self.queue_count = label('队列 0 个 · 待办 0 个', 'dim')
        ll.addWidget(self.queue_count)
        self.queue_list = QListWidget()
        self.queue_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.queue_list.setMaximumHeight(280)
        self.queue_list.setMinimumHeight(90)
        self.queue_list.currentRowChanged.connect(self._on_queue_changed)
        ll.addWidget(self.queue_list)
        controls = QHBoxLayout()
        self.remove_video = QPushButton('移除队列项')
        self.remove_video.clicked.connect(self._remove_queue_selected)
        self.clear_queue = QPushButton('清空队列')
        self.clear_queue.clicked.connect(self._clear_queue)
        controls.addWidget(self.remove_video)
        controls.addWidget(self.clear_queue)
        ll.addLayout(controls)
        self.retry_video = QPushButton('重新处理选中视频')
        self.retry_video.clicked.connect(self._retry_selected)
        ll.addWidget(self.retry_video)
        ll.addStretch(1)
        figure_path = Path(__file__).resolve().parent / 'assets' / 'ink_figure_hd.png'
        if figure_path.is_file():
            fig = InkFigureLabel(str(figure_path))
            fig.setFixedHeight(166)
            fig.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)
            ll.addWidget(fig)
        ll.addWidget(label('仅在本机处理 · 不上传视频', 'dim'))
        splitter.addWidget(left)

        # VIEWER — intentionally much larger than the utility columns.
        center = QWidget()
        center.setMinimumWidth(510)
        cl = QVBoxLayout(center)
        cl.setContentsMargins(9, 6, 9, 0)
        cl.setSpacing(9)
        heading = QHBoxLayout()
        heading.addWidget(label('视频预览', 'sectionTitle'))
        heading.addStretch()
        self.enlarge = QPushButton('⛶ 放大播放器')
        self.enlarge.setObjectName('quiet')
        self.enlarge.clicked.connect(self._toggle_preview_size)
        heading.addWidget(self.enlarge)
        cl.addLayout(heading)

        # Sensitivity belongs immediately above the video stage. Use a
        # prominent centered heading and center the entire slider control.
        sensitivity_heading = label('截图灵敏度', 'sensitivityTitle')
        sensitivity_heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(sensitivity_heading)
        sensitivity_row = QHBoxLayout()
        sensitivity_row.setSpacing(13)
        sensitivity_row.addStretch(1)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(self.sensitivity)
        self.slider.setMinimumWidth(250)
        self.slider.setMaximumWidth(510)
        self.slider.setToolTip('向右拖动，尽可能识别更多画面切换；过高可能增加重复截图')
        self.slider.valueChanged.connect(self._sensitivity_changed)
        sensitivity_row.addWidget(self.slider, 5)
        self.sensitivity_value = label(f'{self.sensitivity}%', 'sensitivityValue')
        self.sensitivity_value.setMinimumWidth(51)
        sensitivity_row.addWidget(self.sensitivity_value)
        sensitivity_row.addStretch(1)
        cl.addLayout(sensitivity_row)

        stage = QFrame()
        stage.setObjectName('videoStage')
        stage_layout = QVBoxLayout(stage)
        stage_layout.setContentsMargins(0, 0, 0, 0)
        self.video = QVideoWidget()
        self.video.setMinimumHeight(280)
        self.video.setStyleSheet('background: #080808;')
        self.video.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        stage_layout.addWidget(self.video, 1)
        cl.addWidget(stage, 1)
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(0.25)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        self.player.positionChanged.connect(self._position_changed)
        self.player.durationChanged.connect(self._duration_changed)
        self.player.playbackStateChanged.connect(self._playback_changed)
        self.player.errorOccurred.connect(self._player_error)
        player_controls = QHBoxLayout()
        self.play = QPushButton('▶ 播放')
        self.play.clicked.connect(self._toggle_play)
        self.seek = MarkerSlider()
        self.seek.setRange(0, 1)
        self.seek.jumped.connect(self._jump_to)
        self.seek.sliderPressed.connect(self._seek_pressed)
        self.seek.sliderReleased.connect(self._seek_released)
        self.clock = label('00:00:00.000 / 00:00:00.000', 'dim')
        player_controls.addWidget(self.play)
        player_controls.addWidget(self.seek, 1)
        player_controls.addWidget(self.clock)
        cl.addLayout(player_controls)

        # Manual capture sits immediately below playback and the seek bar.
        # The time box follows player position, while remaining editable.
        manual = QHBoxLayout()
        manual.setSpacing(9)
        manual.addWidget(label('截图时间（秒）', 'dim'))
        self.manual_time = QDoubleSpinBox()
        self.manual_time.setRange(0, 86_400)
        self.manual_time.setDecimals(3)
        self.manual_time.setSingleStep(0.1)
        self.manual_time.setMinimumWidth(100)
        self.manual_time.setToolTip('播放或拖动进度条后自动更新，也可以手动输入秒数')
        manual.addWidget(self.manual_time)
        self.capture = QPushButton('截取当前画面')
        self.capture.setObjectName('capture')
        self.capture.setToolTip('把播放器当前时间点的画面保存为高质量 JPG')
        self.capture.clicked.connect(self._capture_frame)
        manual.addWidget(self.capture, 1)
        cl.addLayout(manual)

        section_line = QFrame()
        section_line.setObjectName('fineLine')
        section_line.setFixedHeight(1)
        cl.addWidget(section_line)

        # Green batch action remains prominent without duplicating the slider.
        processing_row = QHBoxLayout()
        processing_row.addStretch(1)
        self.start = QPushButton('▶  开始解析视频')
        self.start.setObjectName('primary')
        self.start.clicked.connect(self._start_batch)
        processing_row.addWidget(self.start)
        self.stop = QPushButton('停止')
        self.stop.clicked.connect(self._stop_batch)
        processing_row.addWidget(self.stop)
        cl.addLayout(processing_row)
        output_row = QHBoxLayout()
        self.output_label = label(self._output_text(), 'dim')
        self.output_label.setToolTip(self._output_text())
        self.output_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        output_row.addWidget(self.output_label, 1)
        self.choose_output = QPushButton('更改保存位置…')
        self.choose_output.clicked.connect(self._choose_output)
        output_row.addWidget(self.choose_output)
        cl.addLayout(output_row)
        self.auto_clear_check = QCheckBox('导入新视频时自动清理已完成队列（不删除 JPG）')
        self.auto_clear_check.setChecked(self.auto_clear_completed)
        self.auto_clear_check.toggled.connect(self._auto_clear_changed)
        cl.addWidget(self.auto_clear_check)
        self.status = label('就绪 · 请先选择统一截图保存目录', 'muted')
        self.status.setWordWrap(True)
        cl.addWidget(self.status)
        progress_row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setFormat('当前 · %p%')
        self.total_progress = QProgressBar()
        self.total_progress.setRange(0, 100)
        self.total_progress.setFormat('本批 · %p%')
        progress_row.addWidget(self.progress, 3)
        progress_row.addWidget(self.total_progress, 2)
        cl.addLayout(progress_row)
        splitter.addWidget(center)

        # FRAMES — a persistent history selector ensures the gallery survives
        # auto-pruning completed jobs from the active queue.
        gallery_side = QWidget()
        gallery_side.setMinimumWidth(305)
        gl = QVBoxLayout(gallery_side)
        gl.setContentsMargins(9, 6, 0, 0)
        gl.setSpacing(8)
        gh = QHBoxLayout()
        gh.addWidget(label('镜头截图', 'sectionTitle'))
        gh.addStretch()
        self.gallery_count = label('0 张', 'dim')
        gh.addWidget(self.gallery_count)
        self.wall_button = QPushButton('查看全部大图')
        self.wall_button.setToolTip('在一张可滚动的镜头墙里看所有截图，不用逐张打开文件')
        self.wall_button.clicked.connect(self._open_shot_wall)
        gh.addWidget(self.wall_button)
        gl.addLayout(gh)
        self.history_combo = QComboBox()
        self.history_combo.setToolTip('已完成结果独立于待处理队列保存；清空队列也能在这里查看')
        self.history_combo.currentIndexChanged.connect(self._history_changed)
        gl.addWidget(self.history_combo)
        self.gallery_name = label('选择视频或历史结果查看截图。', 'muted')
        self.gallery_name.setWordWrap(True)
        self.gallery_name.setMaximumHeight(34)
        gl.addWidget(self.gallery_name)
        self.gallery = QListWidget()
        self.gallery.setViewMode(QListWidget.ViewMode.IconMode)
        self.gallery.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.gallery.setMovement(QListWidget.Movement.Static)
        self.gallery.setWrapping(True)
        self.gallery.setSpacing(4)
        self.gallery.setIconSize(QSize(139, 79))
        self.gallery.setGridSize(QSize(149, 105))
        self.gallery.setWordWrap(True)
        self.gallery.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.gallery.itemSelectionChanged.connect(self._gallery_selection_changed)
        self.gallery.itemDoubleClicked.connect(self._open_image)
        gl.addWidget(self.gallery, 1)
        pages = QHBoxLayout()
        self.prev_page = QPushButton('‹ 上一页')
        self.prev_page.clicked.connect(lambda: self._change_page(-1))
        self.page_status = label('0 / 0', 'dim')
        self.next_page = QPushButton('下一页 ›')
        self.next_page.clicked.connect(lambda: self._change_page(1))
        pages.addWidget(self.prev_page)
        pages.addStretch()
        pages.addWidget(self.page_status)
        pages.addStretch()
        pages.addWidget(self.next_page)
        gl.addLayout(pages)
        line1 = QHBoxLayout()
        self.exclude = QPushButton('移除选中')
        self.exclude.clicked.connect(self._exclude_shots)
        self.restore = QPushButton('恢复上一张')
        self.restore.clicked.connect(self._restore_shot)
        line1.addWidget(self.exclude)
        line1.addWidget(self.restore)
        gl.addLayout(line1)
        line2 = QHBoxLayout()
        self.clean_duplicates = QPushButton('去重复')
        self.clean_duplicates.clicked.connect(self._clean_duplicates)
        self.overview = QPushButton('导出总览图')
        self.overview.clicked.connect(self._contact_sheet)
        line2.addWidget(self.clean_duplicates)
        line2.addWidget(self.overview)
        gl.addLayout(line2)
        line3 = QHBoxLayout()
        self.retry_history = QPushButton('重新处理历史视频')
        self.retry_history.clicked.connect(self._retry_history)
        self.open_folder = QPushButton('打开结果文件夹')
        self.open_folder.clicked.connect(self._open_output)
        line3.addWidget(self.retry_history)
        line3.addWidget(self.open_folder)
        gl.addLayout(line3)
        splitter.addWidget(gallery_side)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([238, 950, 365])
        self.workspace = splitter
        self.gallery_card = gallery_side

        bottom_line = QFrame()
        bottom_line.setObjectName('fineLine')
        bottom_line.setFixedHeight(1)
        root.addWidget(bottom_line)
        bottom = QHBoxLayout()
        bottom.addWidget(label('镜头切片 · 第3.4版', 'dim'))
        bottom.addStretch()
        bottom.addWidget(label('所有截图本地保存 · 清理队列不会删除文件', 'dim'))
        root.addLayout(bottom)

    def _open_log(self) -> None:
        path = log_path()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))

    def _toggle_preview_size(self) -> None:
        self._preview_maximized = not self._preview_maximized
        self.gallery_card.setVisible(not self._preview_maximized)
        self.enlarge.setText('恢复截图侧栏' if self._preview_maximized else '放大播放器')
        if not self._preview_maximized:
            self.workspace.setSizes([235, 970, 355])

    def _output_text(self) -> str:
        return (f'统一保存：{self.output_root}' if self.output_root
                else '尚未选择截图保存位置 · 请点击右侧设置')

    def _prompt_first_output_folder(self) -> None:
        # Called after the main window becomes visible; user can defer, but
        # actual processing remains blocked until an output directory is set.
        if self.output_root and self.output_root.is_dir():
            return
        box = QMessageBox(self)
        box.setWindowTitle('首次使用 · 选择截图保存位置')
        box.setIcon(QMessageBox.Icon.Information)
        box.setText('请先选择统一的截图保存文件夹')
        box.setInformativeText(
            '处理后的高清 JPG 将集中保存到这个文件夹中，每个视频有独立子文件夹。\n'
            '设置只需要一次，以后自动记住；重复处理也不会覆盖旧图。'
        )
        select = box.addButton('现在选择文件夹', QMessageBox.ButtonRole.AcceptRole)
        box.addButton('稍后设置', QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is select:
            self._choose_output()
        elif self.output_root is None:
            self.status.setText('尚未设置保存文件夹。点击右上角“设置截图保存位置”后可开始处理。')

    def _choose_output(self) -> bool:
        current = str(self.output_root or Path.home() / 'Movies')
        folder = QFileDialog.getExistingDirectory(self, '选择镜头截图保存文件夹', current)
        if not folder:
            return False
        try:
            root = Path(folder).expanduser().resolve()
            root.mkdir(parents=True, exist_ok=True)
            # A real write probe catches sandbox and read-only disk cases.
            import tempfile
            with tempfile.TemporaryFile(dir=root):
                pass
        except OSError as exc:
            QMessageBox.warning(self, '输出位置无法写入', f'无法保存到所选目录：\n{exc}')
            return False
        self.output_root = root
        self.output_label.setText(self._output_text())
        self.output_label.setToolTip(self._output_text())
        self.top_output.setText('更改截图保存位置')
        self.status.setText(f'已设置统一保存位置：{root}')
        self._save_session()
        return True

    def _auto_clear_changed(self, checked: bool) -> None:
        self.auto_clear_completed = bool(checked)
        self._save_session()

    def _save_session(self) -> None:
        try:
            self.store.save(self.files, self.states, self.results,
                            self.output_root, self.slider.value(),
                            auto_clear_completed=self.auto_clear_completed,
                            history=self.history, history_order=self.history_order)
        except OSError as exc:
            self.status.setText(f'警告：保存任务记录失败：{exc}')

    def _refresh_history_combo(self) -> None:
        current = self.current_view_path
        self.history_combo.blockSignals(True)
        self.history_combo.clear()
        self.history_combo.addItem('历史结果 · 请选择', None)
        # Most recently completed first; browsing stays available after queue cleanup.
        for path in reversed(self.history_order):
            result = self.history.get(path)
            if result is not None:
                self.history_combo.addItem(f'{path.name}  ·  {len(result.shots)} 张', str(path))
                self.history_combo.setItemData(self.history_combo.count() - 1,
                                               str(result.output_dir), Qt.ItemDataRole.ToolTipRole)
        if current in self.history:
            target = self.history_combo.findData(str(current))
            self.history_combo.setCurrentIndex(max(0, target))
        self.history_combo.blockSignals(False)

    def _show_result(self, video: Path) -> None:
        self.current_view_path = video
        if video != self.loaded_video:
            self.player.pause()
            self.loaded_video = video if video.is_file() else None
            self.player.setSource(QUrl.fromLocalFile(str(video)) if video.is_file() else QUrl())
            self.manual_time.setValue(0.0)
        self.preview_page = 0
        self._refresh_history_combo()
        self._refresh_gallery()

    def _history_changed(self, index: int) -> None:
        raw = self.history_combo.itemData(index)
        if not raw:
            return
        video = Path(raw)
        if video in self.history:
            self.queue_list.blockSignals(True)
            self.queue_list.setCurrentRow(-1)
            self.queue_list.blockSignals(False)
            self._show_result(video)

    def _retry_history(self) -> None:
        result = self._selected_result()
        if result is None or self._is_running():
            return
        video = result.video
        if not video.is_file():
            QMessageBox.warning(self, '找不到视频', '原视频已移动或删除，但保存的 JPG 仍可查看。')
            return
        if video not in self.files:
            self.files.append(video)
        self.states[video] = 'pending'
        self._fill_queue()
        self.queue_list.setCurrentRow(self.files.index(video))
        self.status.setText('历史视频已重新加入待办；再次处理将生成新目录，不覆盖原 JPG。')
        self._save_session()
        self._refresh_buttons()

    def _status_for(self, video: Path) -> str:
        state = self.states.get(video, 'pending')
        if state == 'done' and video in self.results:
            return f'完成 · {len(self.results[video].shots)} 张'
        return {'pending': '待处理', 'running': '处理中…',
                'failed': '失败 · 可手动重试'}.get(state, '待处理')

    def _add_queue_item(self, video: Path) -> None:
        item = QListWidgetItem(f'{video.name}\n{self._status_for(video)}')
        item.setToolTip(str(video))
        self.queue_list.addItem(item)

    def _fill_queue(self) -> None:
        self.queue_list.blockSignals(True)
        self.queue_list.clear()
        for p in self.files:
            self._add_queue_item(p)
        self.queue_list.blockSignals(False)
        self.queue_count.setText(f'队列 {len(self.files)} 个 · 待办 {len(pending_jobs(self.files, self.states))} 个')

    def _set_item(self, index: int) -> None:
        if 0 <= index < len(self.files):
            self.queue_list.item(index).setText(f'{self.files[index].name}\n{self._status_for(self.files[index])}')
        self.queue_count.setText(f'队列 {len(self.files)} 个 · 待办 {len(pending_jobs(self.files, self.states))} 个')

    def _is_running(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def _selected_result(self) -> ExtractionResult | None:
        # Result browsing is independent of active queue membership.
        return self.results.get(self.current_view_path) if self.current_view_path else None

    def _refresh_buttons(self) -> None:
        busy = self._is_running()
        selected = self.queue_list.currentRow()
        selected_ok = 0 <= selected < len(self.files)
        result = self._selected_result()
        for button in (self.add_video, self.add_folder, self.remove_video,
                       self.clear_queue, self.retry_video, self.choose_output,
                       self.retry_history, self.capture, self.exclude, self.restore,
                       self.clean_duplicates, self.overview, self.open_folder):
            button.setEnabled(not busy)
        self.drop.setEnabled(not busy)
        self.slider.setEnabled(not busy)
        self.auto_clear_check.setEnabled(not busy)
        self.history_combo.setEnabled(not busy)
        pending_count = len(pending_jobs(self.files, self.states))
        self.start.setEnabled(not busy and pending_count > 0)
        self.start.setText(f'▶  开始解析（{pending_count}）' if not busy else '正在解析视频…')
        self.stop.setEnabled(busy and bool(self.worker) and not self.worker.cancel_event.is_set())
        self.remove_video.setEnabled(not busy and selected_ok)
        self.clear_queue.setEnabled(not busy and bool(self.files))
        self.retry_video.setEnabled(not busy and selected_ok and
                                    self.states.get(self.files[selected]) in ('done', 'failed'))
        self.retry_history.setEnabled(not busy and result is not None and result.video.is_file())
        self.capture.setEnabled(not busy and result is not None and result.video.is_file())
        self.exclude.setEnabled(not busy and result is not None and bool(self.gallery.selectedItems()))
        self.restore.setEnabled(not busy and result is not None and bool(result.removed))
        self.overview.setEnabled(not busy and result is not None and bool(result.shots))
        self.wall_button.setEnabled(not busy and result is not None and bool(result.shots))
        self.clean_duplicates.setEnabled(not busy and result is not None and len(result.shots) > 1)
        self.open_folder.setEnabled(result is not None)
        self.play.setEnabled(self.loaded_video is not None and self.loaded_video.is_file())

    def _choose_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, '选择视频', str(Path.home()),
            '视频文件 (*.mp4 *.mov *.mkv *.avi *.flv *.webm *.m4v *.ts *.wmv *.mpg *.mpeg *.3gp *.rmvb *.m2ts);;所有文件 (*)')
        if paths:
            self._add_paths(paths)

    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, '选择视频文件夹', str(Path.home()))
        if folder:
            self._add_paths([folder])

    def _add_paths(self, paths: list[str]) -> None:
        if self._is_running():
            return
        discovered = collect_videos(paths)
        incoming, requeued, already_pending = plan_reimport(discovered, self.files, self.states)
        if not incoming and not requeued:
            if already_pending:
                self.status.setText('视频已经在待处理队列中，无需重复添加；点击绿色按钮开始解析。')
                self.queue_list.setCurrentRow(self.files.index(already_pending[0]))
            else:
                QMessageBox.information(self, '未找到视频', '没有找到可处理的视频。')
            return

        # Automatically clear only *completed queue entries*; keep JPGs,
        # manifests, history, and the currently displayed screenshots intact.
        # A previously completed item that was dropped again must be requeued
        # before pruning, or it would silently disappear.
        for video in requeued:
            self.states[video] = 'pending'
        removed: list[Path] = []
        if self.auto_clear_completed:
            retained, removed = prune_completed_queue(self.files, self.states)
            self.files = retained
            for old in removed:
                self.states.pop(old, None)
        self.files.extend(incoming)
        for video in incoming:
            self.states[video] = 'pending'
        self._fill_queue()
        next_task = requeued[0] if requeued else incoming[0]
        if self.current_view_path is None or self._selected_result() is None:
            self.queue_list.setCurrentRow(self.files.index(next_task))
        else:
            # Keep the previous screenshot gallery visible while adding jobs.
            self.queue_list.blockSignals(True)
            self.queue_list.setCurrentRow(-1)
            self.queue_list.blockSignals(False)
            self._refresh_gallery()
        self.status.setText(
            f'新增 {len(incoming)} 个视频，重新解析 {len(requeued)} 个旧视频，'
            f'清理 {len(removed)} 个已完成队列项。点击绿色按钮开始；旧 JPG 保留。')
        self._save_session()
        self._refresh_buttons()

    def _remove_queue_selected(self) -> None:
        i = self.queue_list.currentRow()
        if not 0 <= i < len(self.files):
            return
        video = self.files.pop(i)
        self.states.pop(video, None)
        # Do not remove result or history. A removed task can still be browsed.
        self._fill_queue()
        if video in self.results:
            self._show_result(video)
        elif self.files:
            self.queue_list.setCurrentRow(min(i, len(self.files) - 1))
        self._save_session()
        self._refresh_buttons()

    def _clear_queue(self) -> None:
        if not self.files:
            return
        self.files.clear()
        self.states.clear()
        self._fill_queue()
        # The selected result and its JPGs remain available in history.
        if self.current_view_path in self.results:
            self._show_result(self.current_view_path)
        elif self.history_order:
            self._show_result(self.history_order[-1])
        else:
            self.current_view_path = None
            self.loaded_video = None
            self.player.stop()
            self.player.setSource(QUrl())
            self._refresh_gallery()
        self.status.setText('队列已清空；历史结果和 JPG 均未删除。')
        self._save_session()
        self._refresh_buttons()

    def _retry_selected(self) -> None:
        i = self.queue_list.currentRow()
        if not 0 <= i < len(self.files):
            return
        video = self.files[i]
        if self.states.get(video) not in ('done', 'failed'):
            return
        self.states[video] = 'pending'
        # Existing results stay selectable until new extraction completes.
        self._set_item(i)
        self.status.setText('已加入待办队列；上次截图仍保留，处理成功后生成新目录。')
        self._save_session()
        self._refresh_buttons()

    def _sensitivity_changed(self, amount: int) -> None:
        self.sensitivity_value.setText(f'{amount}%')
        self._save_session()

    def _start_batch(self) -> None:
        if self._is_running():
            return
        # A completed source modified while this window stayed open must not be
        # silently considered complete or associated with old screenshots.
        for idx, path in enumerate(self.files):
            result = self.results.get(path)
            if self.states.get(path) == 'done' and result and result.source_fingerprint:
                try:
                    changed = video_fingerprint(path) != result.source_fingerprint
                except OSError:
                    changed = True
                if changed:
                    self.states[path] = 'pending'
                    self._set_item(idx)
        jobs = pending_jobs(self.files, self.states)
        if not jobs:
            self.status.setText('目前没有待处理的视频。')
            return
        if self.output_root is None:
            if not self._choose_output():
                self.status.setText('未选择输出目录，任务未启动；不会写入原视频文件夹。')
                return
        if not self.output_root.is_dir():
            QMessageBox.warning(self, '输出目录失效', '原设置的输出目录不可用，请重新选择。')
            if not self._choose_output():
                return
        if not find_program('ffmpeg'):
            QMessageBox.critical(self, '缺少 FFmpeg', '请安装 FFmpeg：brew install ffmpeg')
            return
        self.active_jobs = jobs
        self.job_positions = {idx: pos for pos, (idx, _) in enumerate(jobs)}
        self.batch_ok = self.batch_errors = 0
        self.progress.setValue(0)
        self.total_progress.setValue(0)
        self.worker = BatchWorker(jobs, self.slider.value() / 100.0, self.output_root)
        self.worker.started_video.connect(self._on_started)
        self.worker.progress_video.connect(self._on_progress)
        self.worker.completed_video.connect(self._on_complete)
        self.worker.failed_video.connect(self._on_failure)
        self.worker.batch_done.connect(self._on_batch_done)
        self.worker.finished.connect(self._on_worker_finished)
        self.worker.start()
        self.status.setText(f'开始处理 {len(jobs)} 个待办视频；完成过的不会重复处理。')
        self._refresh_buttons()

    def _on_started(self, index: int) -> None:
        self.current_index = index
        p = self.files[index]
        self.states[p] = 'running'
        self._set_item(index)
        self.queue_list.setCurrentRow(index)
        self.progress.setValue(0)
        self.status.setText(f'处理中 · {self.job_positions[index]+1}/{len(self.active_jobs)} · {p.name}')
        self._save_session()

    def _on_progress(self, index: int, progress: float) -> None:
        if index == self.current_index:
            self.progress.setValue(max(0, min(100, int(progress * 100))))
        if index in self.job_positions and self.active_jobs:
            self.total_progress.setValue(round(100 * (self.job_positions[index] + progress) / len(self.active_jobs)))

    def _on_complete(self, index: int, result: ExtractionResult) -> None:
        self.results[result.video] = result
        self.history[result.video] = result
        if result.video in self.history_order:
            self.history_order.remove(result.video)
        self.history_order.append(result.video)
        self.states[result.video] = 'done'
        self.batch_ok += 1
        self._refresh_history_combo()
        self._set_item(index)
        self.progress.setValue(100)
        self.status.setText(f'完成：{result.video.name} · {len(result.shots)} 张 · 可预览或补图')
        if self.queue_list.currentRow() == index:
            self._show_result(result.video)
        self._save_session()

    def _on_failure(self, index: int, reason: str) -> None:
        p = self.files[index]
        log_event(f'处理失败: {p}: {reason}')
        self.states[p] = 'failed'
        self.batch_errors += 1
        self._set_item(index)
        self.queue_list.item(index).setToolTip(f'{p}\n{reason}')
        self.status.setText(f'失败：{p.name} · {reason.splitlines()[0][:110]}')
        self._save_session()

    def _on_batch_done(self, cancelled: bool) -> None:
        for idx, p in self.active_jobs:
            if self.states.get(p) == 'running':
                self.states[p] = 'pending'
                self._set_item(idx)
        if cancelled:
            self.status.setText(f'已停止。本批成功 {self.batch_ok} 个、失败 {self.batch_errors} 个；未完成任务保留。')
        else:
            self.total_progress.setValue(100)
            self.status.setText(f'本批完成：成功 {self.batch_ok} 个，失败 {self.batch_errors} 个。')
        self._save_session()
        self._refresh_buttons()

    def _on_worker_finished(self) -> None:
        log_event('批量工作线程结束')
        self.worker = None
        self._refresh_buttons()
        if self.close_after_stop:
            self.close_after_stop = False
            self.close()

    def _stop_batch(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.stop.setEnabled(False)
            self.status.setText('正在停止视频分析并清理未完成的临时截图…')

    def _on_queue_changed(self, index: int) -> None:
        if 0 <= index < len(self.files):
            self._show_result(self.files[index])
        elif self.current_view_path not in self.results:
            self.current_view_path = None
            self.loaded_video = None
            self.player.stop()
            self.player.setSource(QUrl())
            self._refresh_gallery()

    def _duration_changed(self, duration: int) -> None:
        self.seek.setRange(0, max(1, duration))
        self.manual_time.setMaximum(max(0.0, duration / 1000.0) if duration > 0 else 86_400.0)
        self._position_changed(self.player.position())
        self._refresh_markers()

    def _position_changed(self, position: int) -> None:
        if not self._slider_dragging:
            self.seek.setValue(position)
        if not self.manual_time.hasFocus():
            self.manual_time.blockSignals(True)
            self.manual_time.setValue(position / 1000.0)
            self.manual_time.blockSignals(False)
        self.clock.setText(f'{format_time(position/1000)} / {format_time(self.player.duration()/1000)}')

    def _jump_to(self, position: int) -> None:
        self.player.setPosition(position)
        self.manual_time.setValue(position / 1000.0)

    def _seek_pressed(self) -> None:
        self._slider_dragging = True

    def _seek_released(self) -> None:
        self._slider_dragging = False
        self.player.setPosition(self.seek.value())
        self.manual_time.setValue(self.seek.value() / 1000.0)

    def _playback_changed(self, state) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.play.setText('⏸ 暂停' if playing else '▶ 播放')

    def _player_error(self, error, description) -> None:
        if error != QMediaPlayer.Error.NoError and self.loaded_video:
            log_event(f'Qt 播放器错误：{error} / {description} / {self.loaded_video}')
            self.status.setText(f'视频预览不可用：{description}。仍可输入秒数补截图。')

    def _toggle_play(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _refresh_markers(self) -> None:
        result = self._selected_result()
        positions = [s.cut_seconds * 1000 for s in result.shots] if result else []
        self.seek.set_markers(positions)

    def _refresh_gallery(self) -> None:
        result = self._selected_result()
        self.gallery.blockSignals(True)
        self.gallery.clear()
        if result is None:
            self.gallery_count.setText('0 张')
            self.gallery_name.setText('待处理 · 完成后自动显示截图，旧结果可在上方历史列表查看。')
            self.page_status.setText('第 0 / 0 页')
            self.gallery.blockSignals(False)
            self._refresh_markers()
            self._refresh_buttons()
            return
        count = len(result.shots)
        pages = max(1, (count + PREVIEW_PER_PAGE - 1) // PREVIEW_PER_PAGE)
        self.preview_page = min(self.preview_page, pages - 1)
        self.gallery_name.setText(f'{result.video.name} · {result.output_dir.name}')
        self.gallery_name.setToolTip(str(result.output_dir))
        self.gallery_count.setText(f'{count} 张')
        start = self.preview_page * PREVIEW_PER_PAGE
        for shot in result.shots[start:start+PREVIEW_PER_PAGE]:
            reader = QImageReader(str(shot.path))
            reader.setAutoTransform(True)
            size = reader.size()
            if size.isValid():
                size.scale(QSize(146, 83), Qt.AspectRatioMode.KeepAspectRatio)
                reader.setScaledSize(size)
            image = reader.read()
            item = QListWidgetItem(format_time(shot.seconds))
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            item.setData(Qt.ItemDataRole.UserRole, str(shot.path))
            item.setToolTip(f'{shot.path}\n{shot.origin} · 切点约 {format_time(shot.cut_seconds)}')
            if not image.isNull():
                item.setIcon(QIcon(QPixmap.fromImage(image)))
            self.gallery.addItem(item)
        self.page_status.setText(f'第 {self.preview_page+1} / {pages} 页')
        self.prev_page.setEnabled(self.preview_page > 0)
        self.next_page.setEnabled(self.preview_page < pages - 1)
        self.gallery.blockSignals(False)
        self._refresh_markers()
        self._refresh_buttons()

    def _change_page(self, direction: int) -> None:
        self.preview_page = max(0, self.preview_page + direction)
        self._refresh_gallery()

    def _gallery_selection_changed(self) -> None:
        selected = self.gallery.selectedItems()
        if len(selected) == 1:
            result = self._selected_result()
            if result:
                p = Path(selected[0].data(Qt.ItemDataRole.UserRole))
                shot = next((s for s in result.shots if s.path == p), None)
                if shot:
                    self.player.setPosition(round(shot.seconds * 1000))
                    self.manual_time.setValue(shot.seconds)
        self._refresh_buttons()

    def _open_shot_wall(self, select_path: Path | None = None) -> None:
        result = self._selected_result()
        if result is None or not result.shots:
            return
        dialog = ShotWallDialog(result, self, selected_path=select_path)
        dialog.time_selected.connect(lambda seconds: self.player.setPosition(round(seconds * 1000)))
        dialog.exec()

    def _open_image(self, item) -> None:
        # Open the in-app wall with an immediate large preview; no Finder and
        # no need to launch 100 separate image-viewer windows.
        path = Path(item.data(Qt.ItemDataRole.UserRole))
        self._open_shot_wall(select_path=path)

    def _capture_frame(self) -> None:
        result = self._selected_result()
        if not result:
            return
        value = self.manual_time.value()
        try:
            shot = capture_manual_frame(result, value)
        except Exception as exc:
            QMessageBox.critical(self, '截图失败', str(exc))
            return
        self.preview_page = max(0, result.shots.index(shot) // PREVIEW_PER_PAGE)
        self._refresh_gallery()
        i = self.queue_list.currentRow()
        self._set_item(i)
        self.status.setText(f'已截取当前画面：{format_time(shot.seconds)} · 已保存为 JPG')
        self._save_session()

    def _exclude_shots(self) -> None:
        result = self._selected_result()
        if not result:
            return
        selected = [Path(x.data(Qt.ItemDataRole.UserRole)) for x in self.gallery.selectedItems()]
        if not selected:
            return
        count = 0
        try:
            for image in selected:
                if exclude_shot(result, image):
                    count += 1
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, '移除失败', str(exc))
        self._refresh_gallery()
        self._set_item(self.queue_list.currentRow())
        self.status.setText(f'已移除 {count} 张截图；图片在 .excluded 文件夹中，可逐张恢复。')
        self._save_session()

    def _restore_shot(self) -> None:
        result = self._selected_result()
        if not result:
            return
        try:
            shot = restore_last_excluded(result)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, '恢复失败', str(exc))
            return
        if shot is None:
            self.status.setText('没有可恢复的截图。')
            return
        self.preview_page = max(0, result.shots.index(shot) // PREVIEW_PER_PAGE)
        self._refresh_gallery()
        self._set_item(self.queue_list.currentRow())
        self.status.setText(f'已恢复截图：{shot.path.name}')
        self._save_session()

    def _clean_duplicates(self) -> None:
        result = self._selected_result()
        if not result or len(result.shots) < 2:
            return
        try:
            count = remove_duplicate_existing_shots(result)
        except Exception as exc:
            log_event(f'手动去重失败: {exc}')
            QMessageBox.warning(self, '去重失败', str(exc))
            return
        self._refresh_gallery()
        self._set_item(self.queue_list.currentRow())
        self.status.setText(f'同刻重复截图已移除 {count} 张，可通过“恢复上一张”找回。')
        self._save_session()

    def _contact_sheet(self) -> None:
        result = self._selected_result()
        if not result:
            return
        try:
            files = export_contact_sheets(result)
        except Exception as exc:
            QMessageBox.critical(self, '导出失败', str(exc))
            return
        self.status.setText(f'已导出 {len(files)} 张高清镜头总览图：{result.output_dir}')
        QMessageBox.information(self, '导出完成',
                                f'生成 {len(files)} 张镜头总览图，已保存在：\n{result.output_dir}')

    def _open_output(self) -> None:
        result = self._selected_result()
        if result:
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(result.output_dir))):
                QMessageBox.warning(self, '无法打开文件夹', str(result.output_dir))

    def closeEvent(self, event) -> None:
        if self._is_running():
            answer = QMessageBox.question(
                self, '结束任务？', '有视频正在处理。要停止任务并退出吗？',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer == QMessageBox.StandardButton.Yes:
                self.close_after_stop = True
                self._stop_batch()
            event.ignore()
        else:
            self.player.stop()
            self.player.setSource(QUrl())
            self._save_session()
            log_event('正常关闭窗口')
            event.accept()


def _cleanup_qt_before_interpreter_exit(window: SceneCutterWindow) -> None:
    """Destroy the widget tree while QApplication is still alive.

    A Qt/PySide shutdown abort has been observed while destroying QPushButton
    wrappers in Py_FinalizeEx. Do not leave the live QMainWindow and its child
    widgets for PySide's interpreter-atexit clean-up to discover and destroy.
    """
    try:
        worker = window.worker
        if worker is not None and worker.isRunning():
            # Normally closeEvent has already cancelled an active batch. This
            # also protects against quitting via menu / Cmd-Q / OS shutdown.
            log_event('Qt 退出清理：取消仍在运行的后台任务')
            worker.cancel()
            worker.wait()  # Do not destroy a QThread while it is still running.
        window.player.stop()
        window.player.setSource(QUrl())
        # Explicitly disconnect the multimedia pipeline before deleting the
        # video widget and the main window.
        window.player.setVideoOutput(None)
        window.player.setAudioOutput(None)
        window._save_session()
    except Exception as exc:
        log_event(f'Qt 退出清理准备阶段异常: {exc!r}')

    try:
        window.deleteLater()
        # app.exec() has returned, so ordinary event dispatch is no longer
        # running. Flush DeferredDelete while QApplication still exists.
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        log_event('Qt 退出清理：主窗口及其子控件已请求销毁')
    except Exception as exc:
        log_event(f'Qt 延迟删除阶段异常: {exc!r}')


def main() -> int:
    install_crash_logging()
    app = QApplication(sys.argv)
    app.setApplicationName('镜头切片')
    icon_path = application_icon_path()
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    window = SceneCutterWindow()
    if icon_path.is_file():
        window.setWindowIcon(QIcon(str(icon_path)))
    window.show()
    QTimer.singleShot(250, window._prompt_first_output_folder)
    log_event(f'主窗口已显示；QT_MEDIA_BACKEND={os.environ.get("QT_MEDIA_BACKEND", "default")}')
    try:
        return_code = app.exec()
    finally:
        _cleanup_qt_before_interpreter_exit(window)
        # Release the Python wrapper before QApplication destruction/atexit.
        del window
    return return_code


if __name__ == '__main__':
    raise SystemExit(main())
