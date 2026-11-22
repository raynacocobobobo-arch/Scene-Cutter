"""Run from project root with: python3 -m unittest discover -s tests -v"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

import numpy as np

from scene_engine import (
    ExtractionCancelled, SessionStore, capture_manual_frame, collect_videos,
    detect_boundaries, exclude_shot, export_contact_sheets, extract_scenes,
    load_result, pending_jobs, restore_last_excluded, timestamp_filename,
    video_fingerprint,
)


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if shutil.which('ffmpeg') is None or shutil.which('ffprobe') is None:
            raise unittest.SkipTest('FFmpeg and FFprobe are required')
        cls.temp = tempfile.TemporaryDirectory(prefix='scenecutter_test_')
        cls.root = Path(cls.temp.name)
        cls.video = cls.root / 'test_shots.mp4'
        frames = []
        for k in range(48):
            a = np.full((90, 160, 3), 65, dtype=np.uint8)
            if k < 12:
                a[:, :80] = 91
            elif k < 24:
                a[:, 80:] = 91
            elif k < 36:
                a[:, :80] = 97
            else:
                a[30:60, 30:100] = 120
            if k == 18:
                a[:] = 255  # one-frame flash should NOT create a shot
            frames.append(a)
        raw = cls.root / 'shots.rgb'
        raw.write_bytes(b''.join(frame.tobytes() for frame in frames))
        subprocess.run([
            'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
            '-f', 'rawvideo', '-pixel_format', 'rgb24', '-video_size', '160x90',
            '-framerate', '12', '-i', str(raw),
            '-c:v', 'libx264', '-crf', '0', '-pix_fmt', 'yuv444p', str(cls.video),
        ], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_01_four_real_shots_and_no_flash(self):
        self.result = extract_scenes(self.video, .75)
        self.assertEqual(len(self.result.shots), 4)
        self.assertEqual([s.frame_index for s in self.result.shots][0], 0)
        self.assertEqual([round(s.cut_seconds, 1) for s in self.result.shots], [0, 1, 2, 3])
        self.assertTrue(all(s.path.is_file() for s in self.result.shots))
        self.assertEqual(self.result.shots[0].path.name, '000000.000.jpg')
        self.assertIsNotNone(load_result(self.video, self.result.output_dir))

    def test_02_short_two_frame_shot(self):
        frames = []
        for i in range(20):
            a = np.full((90, 160, 3), 20 if i < 8 else 235 if i < 10 else 90, np.uint8)
            frames.append(a)
        raw = self.root / 'short.rgb'
        raw.write_bytes(b''.join(x.tobytes() for x in frames))
        video = self.root / 'short.mp4'
        subprocess.run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
                        '-f', 'rawvideo', '-pixel_format', 'rgb24', '-video_size', '160x90',
                        '-framerate', '10', '-i', str(raw), '-c:v', 'libx264', '-crf', '0',
                        '-pix_fmt', 'yuv444p', str(video)], check=True)
        result = extract_scenes(video, .75)
        self.assertIn(8, [round(x.cut_seconds * 10) for x in result.shots])
        self.assertIn(10, [round(x.cut_seconds * 10) for x in result.shots])

    def test_03_output_folder_and_not_overwritten(self):
        a = extract_scenes(self.video, .75)
        b = extract_scenes(self.video, .75)
        self.assertNotEqual(a.output_dir, b.output_dir)
        self.assertTrue(all(s.path.is_file() for s in a.shots))
        self.assertEqual(len(a.shots), len(b.shots))

    def test_04_manual_capture_persists(self):
        result = extract_scenes(self.video, .75)
        extra = capture_manual_frame(result, 1.85)
        self.assertTrue(extra.path.is_file())
        self.assertEqual(extra.origin, 'manual')
        loaded = load_result(self.video, result.output_dir)
        self.assertIsNotNone(loaded)
        self.assertTrue(any(s.origin == 'manual' for s in loaded.shots))

    def test_05_exclude_and_restore_persists(self):
        result = extract_scenes(self.video, .75)
        first = result.shots[0]
        self.assertTrue(exclude_shot(result, first.path))
        self.assertFalse(first.path.exists())
        self.assertTrue((result.output_dir / '.excluded' / first.path.name).exists())
        loaded = load_result(self.video, result.output_dir)
        self.assertEqual(len(loaded.removed), 1)
        shot = restore_last_excluded(loaded)
        self.assertIsNotNone(shot)
        self.assertTrue(shot.path.is_file())
        self.assertFalse(loaded.removed)

    def test_06_contact_sheet(self):
        result = extract_scenes(self.video, .75)
        output = export_contact_sheets(result, columns=2, rows=1)
        self.assertEqual(len(output), 2)
        self.assertTrue(all(x.stat().st_size > 2000 for x in output))
        self.assertEqual(len(result.shots), 4)

    def test_07_session_persist_and_skip_finished(self):
        result = extract_scenes(self.video, .75)
        state = SessionStore(self.root / 'saved_state.json')
        paths = [self.video]
        state.save(paths, {self.video: 'done'}, {self.video: result}, self.root, 81)
        files, statuses, results, settings = state.restored()
        self.assertEqual(files, paths)
        self.assertEqual(statuses[self.video], 'done')
        self.assertIn(self.video, results)
        self.assertEqual(pending_jobs(files, statuses), [])
        self.assertEqual(settings['sensitivity'], 81)

    def test_08_changed_video_requeued(self):
        result = extract_scenes(self.video, .75)
        state = SessionStore(self.root / 'changed_state.json')
        state.save([self.video], {self.video: 'done'}, {self.video: result}, None, 75)
        # Simulate changed source metadata without altering input used by other tests.
        data = state.load()
        data['files'][0]['fingerprint']['size'] += 1
        from scene_engine import _write_json_atomic
        _write_json_atomic(state.path, data)
        files, statuses, results, _ = state.restored()
        self.assertEqual(statuses[self.video], 'pending')
        self.assertNotIn(self.video, results)
        self.assertEqual(pending_jobs(files, statuses), [(0, self.video)])

    def test_09_path_deduplication(self):
        found = collect_videos([self.video, self.root, self.video])
        self.assertEqual(found.count(self.video), 1)

    def test_10_cancel_leaves_no_partial_result(self):
        event = threading.Event()
        event.set()
        with self.assertRaises(ExtractionCancelled):
            extract_scenes(self.video, cancel=event)

    def test_11_custom_output_folder(self):
        destination = self.root / 'My Exports'
        result = extract_scenes(self.video, .75, output_root=destination)
        self.assertEqual(result.output_dir.parent, destination)
        self.assertTrue(all(shot.path.is_file() for shot in result.shots))

    def test_12_cancel_mid_scan_cleans_temp(self):
        work = self.root / 'cancel_dest'
        work.mkdir(exist_ok=True)
        cancel = threading.Event()
        def stop_when_started(progress):
            if progress > 0.1:
                cancel.set()
        with self.assertRaises(ExtractionCancelled):
            extract_scenes(self.video, on_progress=stop_when_started,
                           cancel=cancel, output_root=work)
        self.assertEqual(list(work.iterdir()), [])

    def test_13_filename(self):
        self.assertEqual(timestamp_filename(3661.2346), '010101.235.jpg')


if __name__ == '__main__':
    unittest.main()

# Kept outside the existing class to independently exercise timestamp deduplication.
class DuplicateTimestampTests(unittest.TestCase):
    def test_identical_frame_at_duplicate_pts_is_omitted(self):
        from scene_engine import FrameMetric, deduplicate_exported_frames
        import numpy as np
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as t:
            folder = Path(t)
            identical = np.full((14, 14, 3), 60, dtype=np.uint8)
            distinct = np.full((14, 14, 3), 190, dtype=np.uint8)
            metrics = [FrameMetric(0, 0, 0, 0, 0, x) for x in (identical, identical, distinct)]
            names = ['a.jpg', 'b.jpg', 'c.jpg']
            for n in names:
                (folder / n).write_bytes(b'test')
            result = deduplicate_exported_frames([(0, 11.981, names[0]), (1, 11.981, names[1]),
                                                    (2, 11.981, names[2])], metrics, folder, 24.0)
            self.assertEqual([r[2] for r in result], ['a.jpg', 'c.jpg'])
            self.assertFalse((folder / 'b.jpg').exists())
            self.assertTrue((folder / 'c.jpg').exists())

class ExistingDuplicateTests(unittest.TestCase):
    def test_can_archive_existing_duplicate_shots_without_deleting(self):
        from PIL import Image
        from scene_engine import ExtractionResult, Shot, remove_duplicate_existing_shots
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            shots = []
            for k, val in enumerate((40, 40, 210)):
                path = folder / f'image{k}.jpg'
                Image.new('RGB', (64, 36), (val, val, val)).save(path, 'JPEG')
                shots.append(Shot(11.981, path, 11.981))
            result = ExtractionResult(folder / 'sample.mp4', folder, shots)
            removed = remove_duplicate_existing_shots(result)
            self.assertEqual(removed, 1)
            self.assertEqual(len(result.shots), 2)
            self.assertEqual(len(result.removed), 1)
            self.assertTrue((folder / '.excluded' / 'image1.jpg').exists())
            self.assertIsNotNone(restore_last_excluded(result))
            self.assertEqual(len(result.shots), 3)
