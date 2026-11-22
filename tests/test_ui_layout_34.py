"""3.4 的界面静态契约检查：不导入 PySide6，避免无 GUI 环境依赖。"""
import unittest
from pathlib import Path


SRC = (Path(__file__).resolve().parents[1] / 'app.py').read_text(encoding='utf-8')


class Layout34Tests(unittest.TestCase):
    def test_30_ink_figure_is_purely_decorative(self):
        figure = SRC.split('class InkFigureLabel(QLabel):', 1)[1].split('class DropPanel(QFrame):', 1)[0]
        self.assertIn('WA_TransparentForMouseEvents', figure)
        self.assertNotIn('mousePressEvent', figure)
        self.assertNotIn('QDialog(', figure)
        self.assertNotIn('PointingHandCursor', figure)
        self.assertNotIn('setToolTip(', figure)

    def test_31_sensitivity_is_centered_above_video(self):
        section = SRC.split('def _build_ui(self)', 1)[1].split('def _open_log(self)', 1)[0]
        title = section.index("label('截图灵敏度', 'sensitivityTitle')")
        self.assertIn('sensitivity_heading.setAlignment(Qt.AlignmentFlag.AlignCenter)', section)
        self.assertIn('QLabel#sensitivityTitle { font-size: 23px;', SRC)
        slider = section.index('self.slider = QSlider(', title)
        video = section.index("stage.setObjectName('videoStage')", slider)
        self.assertLess(title, slider)
        self.assertLess(slider, video)
        self.assertNotIn("label('镜头检测'", section)
        self.assertEqual(section.count('self.slider = QSlider('), 1)

    def test_32_capture_is_directly_below_playback_bar(self):
        section = SRC.split('def _build_ui(self)', 1)[1].split('def _open_log(self)', 1)[0]
        player = section.index('cl.addLayout(player_controls)')
        manual = section.index('manual = QHBoxLayout()', player)
        capture = section.index("self.capture = QPushButton('截取当前画面')", manual)
        processing = section.index('processing_row = QHBoxLayout()', capture)
        self.assertLess(player, manual)
        self.assertLess(manual, capture)
        self.assertLess(capture, processing)
        self.assertEqual(section.count('manual = QHBoxLayout()'), 1)
        self.assertIn('self.capture.clicked.connect(self._capture_frame)', section)
        self.assertNotIn('在当前时间补一张截图', section)
        self.assertIn("self.start.setObjectName('primary')", section)


if __name__ == '__main__':
    unittest.main()
