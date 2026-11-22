"""3.2 workflow regression: clearing jobs must never delete exported JPEGs."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from scene_engine import (
    ExtractionResult, SessionStore, Shot, load_result, pending_jobs,
    prune_completed_queue, save_manifest, video_fingerprint, plan_reimport,
)


class PersistenceWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.exports = self.root / 'All exports'
        self.exports.mkdir()
        self.video_a = self.root / 'A.mov'
        self.video_b = self.root / 'B.mp4'
        self.video_a.write_bytes(b'fake video A')
        self.video_b.write_bytes(b'fake video B')
        self.result_dir = self.exports / 'A.mov_shots'
        self.result_dir.mkdir()
        self.jpg = self.result_dir / '000000.000.jpg'
        Image.new('RGB', (48, 28), 'white').save(self.jpg)
        self.result = ExtractionResult(
            self.video_a, self.result_dir,
            [Shot(0.0, self.jpg, 0.0, 'auto', 0)],
            source_fingerprint=video_fingerprint(self.video_a),
        )
        save_manifest(self.result)
        self.store = SessionStore(self.root / 'state.json')

    def tearDown(self):
        self.temp.cleanup()

    def test_16_next_import_prunes_completed_but_keeps_pending(self):
        files, removed = prune_completed_queue(
            [self.video_a, self.video_b],
            {self.video_a: 'done', self.video_b: 'pending'},
        )
        self.assertEqual(files, [self.video_b])
        self.assertEqual(removed, [self.video_a])
        self.assertTrue(self.jpg.is_file())

    def test_17_history_survives_queue_prune_and_restart(self):
        self.store.save(
            [self.video_b], {self.video_b: 'pending'},
            {self.video_a: self.result}, self.exports, 65,
            auto_clear_completed=True,
            history={self.video_a: self.result},
            history_order=[self.video_a],
        )
        files, statuses, results, settings = self.store.restored()
        archive, order = self.store.restored_history(settings, results)
        self.assertEqual(files, [self.video_b])
        self.assertEqual(pending_jobs(files, statuses), [(0, self.video_b)])
        self.assertIn(self.video_a, archive)
        self.assertEqual(order, [self.video_a])
        self.assertEqual(archive[self.video_a].shots[0].path, self.jpg)
        self.assertTrue(self.jpg.is_file())

    def test_18_output_folder_and_auto_clear_saved_as_preferences(self):
        self.store.save(
            [], {}, {}, self.exports, 78,
            auto_clear_completed=True,
        )
        state = self.store.load()
        self.assertEqual(state['output_mode'], 'custom')
        self.assertEqual(state['output_root'], str(self.exports))
        self.assertTrue(state['auto_clear_completed'])
        self.assertEqual(state['sensitivity'], 78)

    def test_19_history_survives_missing_source_video(self):
        self.store.save([], {}, {}, self.exports, 65,
                        history={self.video_a: self.result},
                        history_order=[self.video_a])
        self.video_a.unlink()
        archive, order = self.store.restored_history(self.store.load())
        self.assertIn(self.video_a, archive)
        self.assertTrue(archive[self.video_a].shots[0].path.exists())
        self.assertTrue(self.jpg.exists())

    def test_20_migrates_older_311_session(self):
        older = {
            'format_version': 3,
            'files': [{'path': str(self.video_a), 'state': 'done',
                       'fingerprint': video_fingerprint(self.video_a),
                       'output_dir': str(self.result_dir)}],
            'output_root': None,
            'sensitivity': 63,
        }
        self.store.path.write_text(json.dumps(older))
        files, states, results, settings = self.store.restored()
        archive, order = self.store.restored_history(settings, results)
        self.assertEqual(states[self.video_a], 'done')
        self.assertIn(self.video_a, archive)
        # Old original-folder option doesn't get silently used: UI must select custom.
        self.assertIsNone(settings['output_root'])
        self.assertTrue(self.jpg.is_file())

    def test_21_archived_output_is_retained_when_queue_empty(self):
        self.store.save([], {}, {}, self.exports, 75,
                        history={self.video_a: self.result},
                        history_order=[self.video_a])
        self.assertEqual(self.store.load()['files'], [])
        self.assertEqual(len(self.store.load()['history']), 1)
        self.assertIsNotNone(load_result(self.video_a, self.result_dir))
        self.assertTrue(self.jpg.is_file())


class ReimportTests(unittest.TestCase):
    def setUp(self):
        self.a = Path('/temporary/A.mp4')
        self.b = Path('/temporary/B.mp4')
        self.c = Path('/temporary/C.mp4')

    def test_23_completed_in_queue_is_requeued(self):
        added, again, skip = plan_reimport(
            [self.a], [self.a], {self.a: 'done'})
        self.assertEqual(added, [])
        self.assertEqual(again, [self.a])
        self.assertEqual(skip, [])

    def test_24_old_processed_video_outside_queue_is_accepted(self):
        # It could be in the independent screenshot history, which must not
        # prevent another drag from scheduling a fresh export.
        added, again, skip = plan_reimport(
            [self.a], [], {})
        self.assertEqual(added, [self.a])
        self.assertFalse(again or skip)

    def test_25_active_pending_video_does_not_duplicate(self):
        added, again, skip = plan_reimport(
            [self.a, self.a], [self.a], {self.a: 'pending'})
        self.assertEqual(added, [])
        self.assertEqual(again, [])
        self.assertEqual(skip, [self.a])

    def test_26_requeued_done_is_not_auto_pruned(self):
        _, again, _ = plan_reimport([self.a], [self.a, self.b],
                                    {self.a: 'done', self.b: 'done'})
        states = {self.a: 'done', self.b: 'done'}
        for video in again:
            states[video] = 'pending'
        keep, gone = prune_completed_queue([self.a, self.b], states)
        self.assertEqual(keep, [self.a])
        self.assertEqual(gone, [self.b])

    def test_27_existing_failed_video_requeued(self):
        _, again, _ = plan_reimport(
            [self.a], [self.a], {self.a: 'failed'})
        self.assertEqual(again, [self.a])


class UIContractTests(unittest.TestCase):
    def test_28_macos_ui_all_requested_controls_present(self):
        root = Path(__file__).resolve().parents[1]
        code = (root / 'app.py').read_text(encoding='utf-8')
        gallery = (root / 'shot_wall.py').read_text(encoding='utf-8')
        for item in ('self.auto_clear_check', 'self.history_combo',
                     '尚未选择截图保存位置', 'def _prompt_first_output_folder',
                     'QTimer.singleShot(250, window._prompt_first_output_folder)',
                     'plan_reimport(', 'self.wall_button',
                     '镜头切片', '开始解析', '#168640',
                     'ink_figure_hd.png'):
            self.assertIn(item, code)
        for item in ('class ShotWallDialog', 'CHUNK_SIZE',
                     '镜头总览', '向下滚动继续加载', '上一张', '下一张'):
            self.assertIn(item, gallery)
        self.assertTrue((root / 'assets' / 'ink_figure_hd.png').stat().st_size > 30000)

    def test_29_visible_headings_are_chinese(self):
        code = (Path(__file__).resolve().parents[1] / 'app.py').read_text('utf-8')
        for literal in ("'SCENE CUTTER'", "'SCENE DETECTION'", "'LOCAL PROCESSING",
                        "'视频队列  /  QUEUE'", "'镜头截图  /  FRAMES'"):
            self.assertNotIn(literal, code)


if __name__ == '__main__':
    unittest.main()
