#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Large, scrollable in-app storyboard gallery. Does not modify or delete JPGs."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QSize, QTimer, Signal, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QImageReader, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QFrame, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QSlider, QSplitter, QVBoxLayout, QWidget,
)

from scene_engine import ExtractionResult, format_time


class ShotWallDialog(QDialog):
    """A single window displaying every screenshot as a browsable storyboard.

    Only the first batch of icons is decoded immediately. Additional batches
    appear automatically as the user scrolls, avoiding opening hundreds of
    external windows and avoiding unnecessary thumbnail memory usage.
    """

    time_selected = Signal(float)
    CHUNK_SIZE = 72

    def __init__(self, result: ExtractionResult, parent=None,
                 selected_path: Path | None = None):
        super().__init__(parent)
        self.result = result
        self.shots = [s for s in result.shots if s.path.is_file()]
        self.loaded = 0
        self.icon_width = 228
        self.selected_index = 0
        self.selected_pixmap = QPixmap()
        self._loading = False
        self.setWindowTitle(f'镜头总览 · {result.video.name}')
        self.resize(1400, 860)
        self.setMinimumSize(960, 600)
        self.setStyleSheet('''
            QDialog { background-color: #F7F5F0; }
            QWidget, QLabel { font-family: 'PingFang SC', sans-serif; color: #151515; font-size: 12px; }
            QListWidget { background-color: #F7F5F0; border: 0px; }
            QListWidget::item { border: 1px solid transparent; padding: 5px; }
            QListWidget::item:selected { background-color: #E2E0D8; border: 2px solid #181818; }
            QPushButton { background: transparent; border: 1px solid #1B1B1B; padding: 8px 12px; }
            QPushButton:hover { background-color: #E5E2DA; }
            QSlider::groove:horizontal { height: 3px; background: #AAA8A1; }
            QSlider::handle:horizontal { background: #161616; width: 12px; margin: -6px 0; }
        ''')
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 16)
        root.setSpacing(12)

        top = QHBoxLayout()
        title = QLabel(f'镜头总览   ·   共 {len(self.shots)} 张')
        title.setStyleSheet('font-size: 21px; font-weight: 760;')
        top.addWidget(title)
        top.addStretch()
        top.addWidget(QLabel('缩略图大小'))
        self.zoom = QSlider(Qt.Orientation.Horizontal)
        self.zoom.setRange(165, 290)
        self.zoom.setValue(self.icon_width)
        self.zoom.setFixedWidth(122)
        self.zoom.valueChanged.connect(self._zoom_changed)
        top.addWidget(self.zoom)
        folder = QPushButton('打开截图文件夹')
        folder.clicked.connect(self._open_folder)
        top.addWidget(folder)
        done = QPushButton('关闭')
        done.clicked.connect(self.accept)
        top.addWidget(done)
        root.addLayout(top)

        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet('background: #171717; border: none;')
        root.addWidget(line)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        left = QWidget()
        lay = QVBoxLayout(left)
        lay.setContentsMargins(0, 0, 4, 0)
        lay.setSpacing(7)
        hint = QLabel('连续滚动查看所有镜头。选择缩略图可在右侧直接预览，无需逐张打开。')
        hint.setStyleSheet('color: #68645B;')
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.listing = QListWidget()
        self.listing.setViewMode(QListWidget.ViewMode.IconMode)
        self.listing.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.listing.setMovement(QListWidget.Movement.Static)
        self.listing.setWrapping(True)
        self.listing.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.listing.setSpacing(6)
        self.listing.setUniformItemSizes(True)
        self._set_icon_geometry()
        self.listing.currentRowChanged.connect(self._selected)
        self.listing.verticalScrollBar().valueChanged.connect(self._scroll_changed)
        lay.addWidget(self.listing, 1)
        self.loading_text = QLabel('正在载入截图…')
        self.loading_text.setStyleSheet('color: #68645B;')
        lay.addWidget(self.loading_text)
        splitter.addWidget(left)

        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(8, 0, 0, 0)
        right_lay.setSpacing(10)
        self.preview_heading = QLabel('大图预览')
        self.preview_heading.setStyleSheet('font-size: 17px; font-weight: 750;')
        right_lay.addWidget(self.preview_heading)
        self.large = QLabel('选择左侧的缩略图')
        self.large.setMinimumSize(230, 180)
        self.large.setStyleSheet('background: #151515; color: #BBBBBB;')
        self.large.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_lay.addWidget(self.large, 1)
        self.info = QLabel('')
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        right_lay.addWidget(self.info)
        controls = QHBoxLayout()
        prev = QPushButton('上一张')
        prev.clicked.connect(lambda: self._advance(-1))
        controls.addWidget(prev)
        nxt = QPushButton('下一张')
        nxt.clicked.connect(lambda: self._advance(1))
        controls.addWidget(nxt)
        right_lay.addLayout(controls)
        help_ = QLabel('可使用键盘左右方向键切换；单击缩略图即可查看大图。')
        help_.setWordWrap(True)
        help_.setStyleSheet('color: #68645B;')
        right_lay.addWidget(help_)
        splitter.addWidget(right)
        splitter.setSizes([820, 475])
        self._load_more()
        if self.shots:
            if selected_path:
                chosen = next((i for i, s in enumerate(self.shots)
                               if s.path == selected_path), 0)
                while self.loaded <= chosen:
                    self._load_more()
                self.listing.setCurrentRow(chosen)
                self.listing.scrollToItem(self.listing.item(chosen))
            else:
                self.listing.setCurrentRow(0)
        else:
            self.loading_text.setText('此结果中没有可读取的截图。')

    def _set_icon_geometry(self):
        self.listing.setIconSize(QSize(self.icon_width, round(self.icon_width * 9 / 16)))
        self.listing.setGridSize(QSize(self.icon_width + 26,
                                      round(self.icon_width * 9 / 16) + 43))

    def _make_icon(self, path: Path) -> QIcon:
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid():
            size.scale(QSize(self.icon_width * 2,
                            round(self.icon_width * 9 / 8)),
                       Qt.AspectRatioMode.KeepAspectRatio)
            reader.setScaledSize(size)
        image = reader.read()
        if image.isNull():
            return QIcon()
        pix = QPixmap.fromImage(image)
        return QIcon(pix)

    def _load_more(self) -> None:
        if self._loading or self.loaded >= len(self.shots):
            return
        self._loading = True
        end = min(len(self.shots), self.loaded + self.CHUNK_SIZE)
        self.listing.blockSignals(True)
        for shot in self.shots[self.loaded:end]:
            item = QListWidgetItem(format_time(shot.seconds))
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            item.setToolTip(f'截图时间：{format_time(shot.seconds)}\n{shot.path}')
            item.setData(Qt.ItemDataRole.UserRole, str(shot.path))
            item.setIcon(self._make_icon(shot.path))
            self.listing.addItem(item)
        self.listing.blockSignals(False)
        self.loaded = end
        self.loading_text.setText(f'已显示 {self.loaded} / {len(self.shots)} 张 · 向下滚动继续加载'
                                  if self.loaded < len(self.shots)
                                  else f'全部 {len(self.shots)} 张已显示')
        self._loading = False

    def _scroll_changed(self, value: int) -> None:
        bar = self.listing.verticalScrollBar()
        if self.loaded < len(self.shots) and value >= bar.maximum() - 70:
            QTimer.singleShot(0, self._load_more)

    def _selected(self, index: int) -> None:
        if index < 0 or index >= len(self.shots):
            return
        self.selected_index = index
        shot = self.shots[index]
        # Only decode a full-size still for the selected image; never decode
        # every full-res JPG at once.
        reader = QImageReader(str(shot.path))
        reader.setAutoTransform(True)
        self.selected_pixmap = QPixmap.fromImage(reader.read())
        self._refresh_large()
        self.preview_heading.setText(f'第 {index + 1} 张 / 共 {len(self.shots)} 张')
        self.info.setText(f'时间：{format_time(shot.seconds)}\n文件：{shot.path.name}')
        self.time_selected.emit(shot.seconds)

    def _refresh_large(self) -> None:
        if self.selected_pixmap.isNull():
            self.large.setText('无法读取这张截图')
            return
        size = self.large.size() - QSize(14, 14)
        self.large.setPixmap(self.selected_pixmap.scaled(
            size, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, 'selected_pixmap'):
            QTimer.singleShot(0, self._refresh_large)

    def _advance(self, delta: int) -> None:
        if not self.shots:
            return
        dest = max(0, min(len(self.shots) - 1, self.selected_index + delta))
        while self.loaded <= dest:
            self._load_more()
        self.listing.setCurrentRow(dest)
        self.listing.scrollToItem(self.listing.item(dest))

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Right:
            self._advance(1)
            event.accept()
        elif event.key() == Qt.Key.Key_Left:
            self._advance(-1)
            event.accept()
        else:
            super().keyPressEvent(event)

    def _zoom_changed(self, value: int) -> None:
        self.icon_width = value
        self._set_icon_geometry()
        # Reload the already displayed thumbnails at the new width.
        for i in range(self.loaded):
            self.listing.item(i).setIcon(self._make_icon(self.shots[i].path))

    def _open_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.result.output_dir)))
