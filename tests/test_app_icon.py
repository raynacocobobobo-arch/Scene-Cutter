"""验证正式图标在源码、应用和 GitHub 打包中保持一致。"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class AppIconTests(unittest.TestCase):
    def test_icon_resources_are_valid(self):
        png = ROOT / 'assets' / 'app_icon.png'
        icns = ROOT / 'assets' / 'app_icon.icns'
        self.assertTrue(png.exists())
        self.assertTrue(icns.exists())
        import struct
        content = png.read_bytes()
        self.assertTrue(content.startswith(b'\x89PNG\r\n\x1a\n'))
        self.assertEqual(struct.unpack('>II', content[16:24]), (1024, 1024))
        self.assertEqual(icns.read_bytes()[:4], b'icns')

    def test_packaging_and_window_icon_are_configured(self):
        script = (ROOT/'build_macos.command').read_text(encoding='utf-8')
        workflow = (ROOT/'.github/workflows/build-macos.yml').read_text(encoding='utf-8')
        app = (ROOT/'app.py').read_text(encoding='utf-8')
        self.assertIn('--icon "assets/app_icon.icns"', script)
        self.assertIn("--icon 'assets/app_icon.icns'", workflow)
        self.assertIn('app.setWindowIcon(QIcon(str(icon_path)))', app)
        self.assertIn('window.setWindowIcon(QIcon(str(icon_path)))', app)

if __name__=='__main__':
    unittest.main()
