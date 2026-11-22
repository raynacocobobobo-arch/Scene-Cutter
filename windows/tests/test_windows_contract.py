"""Windows platform contract, safe to run under Linux during development."""
from pathlib import Path
from unittest import TestCase, mock
import os
import sys
import tempfile
import scene_engine
import crashlog

class WindowsPortTests(TestCase):
    def test_find_program_uses_custom_ffmpeg_folder(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'ffmpeg.exe'
            p.write_bytes(b'placeholder')
            with mock.patch.object(scene_engine.sys,'platform','win32'), mock.patch.dict(os.environ, {'SCENECUTTER_FFMPEG_DIR':td}):
                found = scene_engine.find_program('ffmpeg')
            self.assertEqual(found, str(p.resolve()))

    def test_store_is_under_local_appdata(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {'LOCALAPPDATA':td}):
            result=scene_engine.SessionStore().path
        self.assertEqual(result,Path(td)/'SceneCutter'/'state.json')

    def test_crash_log_under_local_appdata(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {'LOCALAPPDATA':td}):
            result=crashlog.log_path()
        self.assertEqual(result,Path(td)/'SceneCutter'/'Logs'/'crash.log')

    def test_windows_no_console_flag_contract(self):
        with mock.patch.object(scene_engine.sys, 'platform', 'win32'):
            self.assertEqual(scene_engine._hidden_subprocess_flags(),getattr(scene_engine.subprocess,'CREATE_NO_WINDOW',0))

    def test_source_preserves_full_resolution_jpeg(self):
        text=(Path(scene_engine.__file__).read_text(encoding='utf-8'))
        fragment=text.split('def export_selected_frames(',1)[1].split('def ',1)[0]
        self.assertIn("'-q:v', '2'",fragment)
        self.assertNotIn('scale=',fragment)
