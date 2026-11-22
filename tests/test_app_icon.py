"""验证正式图标及 macOS 打包的 Bundle ID 配置。"""
import struct
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class AppIconTests(unittest.TestCase):
    def test_icon_resources_are_valid(self):
        png = ROOT / "assets" / "app_icon.png"
        icns = ROOT / "assets" / "app_icon.icns"
        self.assertTrue(png.exists())
        content = png.read_bytes()
        self.assertTrue(content.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(struct.unpack(">II", content[16:24]), (512, 512))
        if icns.exists():
            self.assertEqual(icns.read_bytes()[:4], b"icns")

    def test_packaging_and_window_icon_are_configured(self):
        script = (ROOT / "build_macos.command").read_text(encoding="utf-8")
        workflow = (ROOT / ".github/workflows/build-macos.yml").read_text(encoding="utf-8")
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        for txt in (script, workflow):
            self.assertIn("--osx-bundle-identifier com.scenecutter.app", txt)
            self.assertIn("bash generate_macos_icon.command", txt)
            self.assertIn("PlistBuddy", txt)
            self.assertIn("codesign --force --deep --sign -", txt)
        self.assertIn('--icon "assets/app_icon.icns"', script)
        self.assertIn("--icon 'assets/app_icon.icns'", workflow)
        self.assertIn("app.setWindowIcon(QIcon(str(icon_path)))", app)
        self.assertIn("window.setWindowIcon(QIcon(str(icon_path)))", app)

if __name__ == "__main__":
    unittest.main()
