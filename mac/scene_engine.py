#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Scene Cutter 3.0 — local, frame-accurate, multi-signal shot extraction.

No Qt imports: this module is independently testable and usable from scripts.
Requires FFmpeg/FFprobe, NumPy, Pillow. Never modifies the source video.
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import numpy as np

VIDEO_EXTENSIONS = frozenset({
    '.mp4', '.mov', '.mkv', '.avi', '.flv', '.webm', '.m4v',
    '.ts', '.wmv', '.mpg', '.mpeg', '.3gp', '.rmvb', '.m2ts',
})
SCAN_WIDTH = 224
SCAN_HEIGHT = 126
FRAME_BYTES = SCAN_WIDTH * SCAN_HEIGHT * 3
MANIFEST_NAME = 'shots.json'
Progress = Optional[Callable[[float], None]]


@dataclass(frozen=True)
class Shot:
    seconds: float
    path: Path
    cut_seconds: float = 0.0
    origin: str = 'auto'
    frame_index: int | None = None


@dataclass
class ExtractionResult:
    video: Path
    output_dir: Path
    shots: list[Shot]
    removed: list[dict] = field(default_factory=list)
    sensitivity: float = 0.75
    source_fingerprint: dict | None = None


class ExtractionCancelled(Exception):
    pass


def collect_videos(paths: list[str | Path]) -> list[Path]:
    found: dict[str, Path] = {}
    for raw in paths:
        path = Path(raw).expanduser()
        if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS:
            p = path.resolve()
            found[str(p)] = p
        elif path.is_dir():
            for root, dirs, filenames in os.walk(path, followlinks=False):
                dirs[:] = sorted(d for d in dirs if not d.startswith('.'))
                for filename in sorted(filenames):
                    candidate = Path(root) / filename
                    if candidate.suffix.lower() in VIDEO_EXTENSIONS and candidate.is_file():
                        p = candidate.resolve()
                        found[str(p)] = p
    return sorted(found.values(), key=lambda p: str(p).casefold())


def pending_jobs(files: list[Path], states: dict[Path, str]) -> list[tuple[int, Path]]:
    return [(i, p) for i, p in enumerate(files) if states.get(p, 'pending') == 'pending']


def plan_reimport(discovered: list[Path], queue: list[Path], states: dict[Path, str]
                  ) -> tuple[list[Path], list[Path], list[Path]]:
    """Plan a fresh drag-and-drop operation.

    Dragging a previously completed video always means *process it again*.
    Returns (new queue entries, existing entries reset to pending,
    entries which are already pending). JPG files are not touched.
    """
    queued = set(queue)
    seen: set[Path] = set()
    incoming: list[Path] = []
    rerun: list[Path] = []
    already_pending: list[Path] = []
    for path in discovered:
        if path in seen:
            continue
        seen.add(path)
        if path not in queued:
            incoming.append(path)
        elif states.get(path) in ('done', 'failed'):
            rerun.append(path)
        else:
            already_pending.append(path)
    return incoming, rerun, already_pending


def find_program(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for root in ('/opt/homebrew/bin', '/usr/local/bin', '/usr/bin'):
        p = Path(root) / name
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    return None


def probe_video(video: Path, ffprobe: str | None = None) -> tuple[float | None, float | None, int | None]:
    ffprobe = ffprobe or find_program('ffprobe')
    if not ffprobe:
        return None, None, None
    try:
        res = subprocess.run([
            ffprobe, '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'format=duration:stream=duration,nb_frames,avg_frame_rate',
            '-of', 'json', str(video),
        ], capture_output=True, text=True, timeout=30, check=True)
        data = json.loads(res.stdout)
        stream = (data.get('streams') or [{}])[0]
        durations = []
        for val in [data.get('format', {}).get('duration'), stream.get('duration')]:
            try:
                f = float(val)
                if math.isfinite(f) and f > 0:
                    durations.append(f)
            except (ValueError, TypeError):
                pass
        duration = max(durations) if durations else None
        fps = None
        rate = stream.get('avg_frame_rate', '0/0')
        try:
            a, b = rate.split('/')
            value = float(a) / float(b)
            if math.isfinite(value) and value > 0:
                fps = value
        except (ValueError, ZeroDivisionError, AttributeError):
            pass
        try:
            frames = int(stream.get('nb_frames'))
            if frames <= 0:
                frames = None
        except (TypeError, ValueError):
            frames = None
        if frames is None and duration and fps:
            frames = max(1, round(duration * fps))
        return duration, fps, frames
    except (subprocess.SubprocessError, OSError, ValueError, json.JSONDecodeError):
        return None, None, None


def video_fingerprint(path: Path) -> dict:
    stat = path.stat()
    return {'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns}


def unique_output_dir(video: Path, output_root: Path | None = None) -> Path:
    root = (Path(output_root).expanduser() if output_root else video.parent)
    basename = f'{video.name}_shots'
    destination = root / basename
    index = 2
    while destination.exists():
        destination = root / f'{basename}_{index:02d}'
        index += 1
    return destination


def timestamp_filename(seconds: float) -> str:
    ms = max(0, round(seconds * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f'{h:02d}{m:02d}{s:02d}.{ms:03d}.jpg'


def format_time(seconds: float) -> str:
    ms = max(0, round(seconds * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f'{h:02d}:{m:02d}:{s:02d}.{ms:03d}'


def _safe_name(path: Path, candidate: str) -> str:
    # Never overwrite a screenshot or its excluded counterpart.
    base = Path(candidate).stem
    ext = Path(candidate).suffix
    name = candidate
    n = 2
    while (path / name).exists() or (path / '.excluded' / name).exists():
        name = f'{base}_{n:02d}{ext}'
        n += 1
    return name


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f'.{path.stem}_', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save_manifest(result: ExtractionResult) -> None:
    data = {
        'format_version': 3,
        'video': str(result.video),
        'sensitivity': result.sensitivity,
        'source_fingerprint': result.source_fingerprint,
        'shots': [
            {'seconds': s.seconds, 'filename': s.path.name,
             'cut_seconds': s.cut_seconds, 'origin': s.origin, 'frame_index': s.frame_index}
            for s in result.shots
        ],
        'removed': result.removed,
    }
    _write_json_atomic(result.output_dir / MANIFEST_NAME, data)


def load_result(video: str | Path, output_dir: str | Path) -> ExtractionResult | None:
    folder = Path(output_dir).expanduser()
    manifest = folder / MANIFEST_NAME
    if not manifest.is_file():
        return None
    try:
        data = json.loads(manifest.read_text(encoding='utf-8'))
        video = Path(video).resolve()
        if Path(data['video']).resolve() != video:
            return None
        shots = []
        for record in data['shots']:
            filename = Path(record['filename']).name
            p = folder / filename
            if not p.is_file():
                continue
            shots.append(Shot(float(record['seconds']), p,
                              float(record.get('cut_seconds', record['seconds'])),
                              str(record.get('origin', 'auto')),
                              record.get('frame_index')))
        shots.sort(key=lambda shot: (shot.seconds, shot.path.name))
        removed = list(data.get('removed', []))
        return ExtractionResult(video, folder, shots, removed,
                                float(data.get('sensitivity', 0.75)),
                                data.get('source_fingerprint'))
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


class SessionStore:
    """Queue settings + independent result archive (never deletes JPEGs).

    ``files`` contains *only* active queue entries; ``history`` is a separate,
    persistent result index. Auto-pruning the queue therefore does not remove
    screenshot previews or the physical output folder.
    """

    def __init__(self, path: Path | None = None):
        self.path = path or (Path.home() / 'Library' / 'Application Support' / 'SceneCutter' / 'state.json')

    def load(self) -> dict:
        try:
            raw = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(raw, dict):
                raise ValueError('not an object')
            return raw
        except (OSError, ValueError, json.JSONDecodeError):
            return {'files': [], 'output_root': None, 'sensitivity': 75,
                    'auto_clear_completed': True, 'history': []}

    def save(self, files: list[Path], states: dict[Path, str],
             results: dict[Path, ExtractionResult], output_root: Path | None,
             sensitivity: int, *, auto_clear_completed: bool = True,
             history: dict[Path, ExtractionResult] | None = None,
             history_order: list[Path] | None = None) -> None:
        records = []
        for p in files:
            if not p.exists():
                continue
            current_state = states.get(p, 'pending')
            fingerprint = (results[p].source_fingerprint
                           if current_state == 'done' and p in results
                           and results[p].source_fingerprint else video_fingerprint(p))
            record = {'path': str(p), 'state': current_state, 'fingerprint': fingerprint}
            if p in results:
                record['output_dir'] = str(results[p].output_dir)
            records.append(record)
        # A stable, independent history index is maintained even if the queue
        # is cleared. Store paths only; the authoritative shot metadata lives
        # in each result's shots.json manifest.
        archive = dict(history or {})
        for p, result in results.items():
            if result.output_dir.is_dir() and p not in archive:
                archive[p] = result
        ordered = list(history_order or [])
        ordered += [p for p in archive if p not in ordered]
        history_records = [
            {'video': str(p), 'output_dir': str(archive[p].output_dir)}
            for p in ordered if p in archive and archive[p].output_dir.is_dir()
        ]
        _write_json_atomic(self.path, {
            'format_version': 4,
            'files': records,
            'history': history_records,
            'output_root': str(output_root) if output_root else None,
            'output_mode': 'custom',
            'auto_clear_completed': bool(auto_clear_completed),
            'sensitivity': sensitivity,
        })

    @staticmethod
    def restored_history(settings: dict,
                         queue_results: dict[Path, ExtractionResult] | None = None
                         ) -> tuple[dict[Path, ExtractionResult], list[Path]]:
        """Restore archived previews even for files no longer in queue.

        A missing source video may still have browsable JPGs. We load the
        manifest without requiring the original video to exist.
        """
        found: dict[Path, ExtractionResult] = {}
        order: list[Path] = []
        for record in settings.get('history', []):
            try:
                video = Path(record['video']).expanduser().resolve()
                out = record['output_dir']
                result = load_result(video, out)
                if result:
                    found[video] = result
                    if video in order:
                        order.remove(video)
                    order.append(video)
            except (KeyError, OSError, ValueError, TypeError):
                continue
        for video, result in (queue_results or {}).items():
            if video not in found:
                found[video] = result
                order.append(video)
        return found, order

    def restored(self) -> tuple[list[Path], dict[Path, str], dict[Path, ExtractionResult], dict]:
        settings = self.load()
        files: list[Path] = []
        states: dict[Path, str] = {}
        results: dict[Path, ExtractionResult] = {}
        seen: set[Path] = set()
        for item in settings.get('files', []):
            try:
                p = Path(item['path']).expanduser().resolve()
                if p in seen or not p.is_file():
                    continue
                seen.add(p)
                files.append(p)
                if item.get('state') == 'done' and item.get('fingerprint') == video_fingerprint(p):
                    output = item.get('output_dir')
                    result = load_result(p, output) if output else None
                    if result and (result.source_fingerprint is None or
                                   result.source_fingerprint == video_fingerprint(p)):
                        states[p] = 'done'
                        results[p] = result
                        continue
                states[p] = 'pending'
            except (OSError, KeyError, ValueError, TypeError):
                continue
        return files, states, results, settings


def prune_completed_queue(files: list[Path], states: dict[Path, str]
                          ) -> tuple[list[Path], list[Path]]:
    """Return (retained queue, completed removed); never touches disk."""
    return ([p for p in files if states.get(p) != 'done'],
            [p for p in files if states.get(p) == 'done'])


@dataclass(frozen=True)
class FrameMetric:
    rgb: float
    structure: float
    histogram: float
    sharpness: float
    brightness: float
    signature: np.ndarray  # 14 x 8 x 3, enough for short flash verification


def _compute_metrics(frame: np.ndarray, previous: np.ndarray | None,
                     previous_gray: np.ndarray | None, previous_hist: np.ndarray | None,
                     prev_edge: np.ndarray | None) -> tuple[FrameMetric, np.ndarray, np.ndarray, np.ndarray]:
    # Half-resolution grayscale for low-cost structure and focus measurements.
    gray = (0.299 * frame[::2, ::2, 0] +
            0.587 * frame[::2, ::2, 1] +
            0.114 * frame[::2, ::2, 2]).astype(np.float32)
    # Gradient magnitude representation; robust to similar palettes/different outlines.
    dx = np.abs(np.diff(gray, axis=1))
    dy = np.abs(np.diff(gray, axis=0))
    edge = np.zeros_like(gray)
    edge[:, 1:] += dx
    edge[1:, :] += dy
    hist = np.bincount(np.clip((gray / 16).astype(np.int32), 0, 15).ravel(), minlength=16).astype(np.float32)
    hist /= max(float(hist.sum()), 1.0)
    rgb = (float(np.abs(frame.astype(np.int16) - previous.astype(np.int16)).mean()) / 255
           if previous is not None else 0.0)
    structure = (float(np.abs(edge - prev_edge).mean()) / 255
                 if prev_edge is not None else 0.0)
    histogram = (float(np.abs(hist - previous_hist).sum()) / 2
                 if previous_hist is not None else 0.0)
    sharpness = float((dx * dx).mean() + (dy * dy).mean()) / (255 * 255)
    brightness = float(gray.mean()) / 255
    signature = frame[::9, ::16, :].copy()
    return FrameMetric(rgb, structure, histogram, sharpness, brightness, signature), gray, hist, edge


def _stop_process(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _cancel_watcher(proc: subprocess.Popen, cancel: threading.Event | None,
                    finished: threading.Event) -> None:
    if cancel is None:
        return
    while not finished.wait(0.2):
        if cancel.is_set():
            _stop_process(proc)
            return


def _log_tail(file: Path) -> str:
    try:
        return '\n'.join(file.read_text(encoding='utf-8', errors='replace').splitlines()[-12:])
    except OSError:
        return ''


def scan_frames(video: Path, ffmpeg: str, log: Path, total: int | None,
                on_progress: Progress, cancel: threading.Event | None) -> list[FrameMetric]:
    cmd = [
        ffmpeg, '-hide_banner', '-nostdin', '-nostats', '-loglevel', 'error',
        '-i', str(video), '-map', '0:v:0', '-an', '-sn', '-dn',
        '-vf', (f'scale={SCAN_WIDTH}:{SCAN_HEIGHT}:force_original_aspect_ratio=decrease:'
                'flags=fast_bilinear,'
                f'pad={SCAN_WIDTH}:{SCAN_HEIGHT}:(ow-iw)/2:(oh-ih)/2,format=rgb24'),
        '-fps_mode', 'passthrough', '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1',
    ]
    metrics: list[FrameMetric] = []
    with log.open('w', encoding='utf-8') as err:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err, bufsize=FRAME_BYTES * 2)
        finished = threading.Event()
        watcher = threading.Thread(target=_cancel_watcher, args=(proc, cancel, finished), daemon=True)
        watcher.start()
        try:
            if proc.stdout is None:
                raise RuntimeError('FFmpeg 没有输出视频帧')
            previous = previous_gray = previous_hist = prev_edge = None
            while True:
                if cancel and cancel.is_set():
                    raise ExtractionCancelled('已停止')
                raw = proc.stdout.read(FRAME_BYTES)
                if not raw:
                    break
                if len(raw) != FRAME_BYTES:
                    raise RuntimeError('读到不完整的视频帧')
                frame = np.frombuffer(raw, dtype=np.uint8).reshape(SCAN_HEIGHT, SCAN_WIDTH, 3)
                metric, previous_gray, previous_hist, prev_edge = _compute_metrics(
                    frame, previous, previous_gray, previous_hist, prev_edge)
                metrics.append(metric)
                previous = frame.copy()
                if on_progress and total and len(metrics) % 30 == 0:
                    on_progress(min(0.60, 0.60 * len(metrics) / total))
            proc.stdout.close()
            status = proc.wait()
            if cancel and cancel.is_set():
                raise ExtractionCancelled('已停止')
            if status != 0:
                raise RuntimeError(f'视频分析失败（FFmpeg {status}）\n{_log_tail(log)}')
            if not metrics:
                raise RuntimeError('视频没有可解码的画面')
            if on_progress:
                on_progress(0.60)
            return metrics
        finally:
            finished.set()
            _stop_process(proc)
            if proc.stdout and not proc.stdout.closed:
                proc.stdout.close()


def detect_boundaries(metrics: list[FrameMetric], sensitivity: float = 0.75) -> list[int]:
    """Fuse RGB, edge structure and luminance histograms with local baselines.

    Each candidate is the first frame AFTER a cut. Differences are relative to
    its local motion, so smooth motion does not trigger on every frame.
    No heuristic guarantees perfect recall for fades or matched cuts.
    """
    if not 0 <= sensitivity <= 1:
        raise ValueError('灵敏度需要在 0～1 之间')
    n = len(metrics)
    if n <= 1:
        return [0] if n else []
    values = np.array([[m.rgb, m.structure, m.histogram] for m in metrics], dtype=np.float32)
    # At maximum sensitivity prefer recall; medium setting is less permissive.
    mins = np.array([
        0.003 + 0.047 * (1 - sensitivity) ** 2,
        0.004 + 0.090 * (1 - sensitivity) ** 2,
        0.012 + 0.230 * (1 - sensitivity) ** 2,
    ], dtype=np.float32)
    ratio_min = 1.20 + 2.50 * (1 - sensitivity)
    candidates: list[tuple[int, float]] = []
    for i in range(1, n):
        cur = values[i]
        if not bool(np.any(cur > mins)):
            continue
        vicinity = np.concatenate((values[max(1, i-14):max(1, i-1)],
                                    values[min(n, i+2):min(n, i+15)]))
        base = np.median(vicinity, axis=0) if len(vicinity) else np.zeros(3, dtype=np.float32)
        ratio = cur / np.maximum(base, np.array([0.001, 0.002, 0.006]))
        significant = (cur >= mins) & (ratio >= ratio_min)
        # One highly exceptional signal or two moderately exceptional ones.
        peak_strength = np.maximum(cur / mins, 0) * np.maximum(ratio / ratio_min, 0)
        strong = bool(np.any(significant & (peak_strength > 1.15)))
        multichannel = bool(np.count_nonzero((cur > mins * 0.8) & (ratio > ratio_min * 0.90)) >= 2)
        # Force inclusion for unmistakably different adjacent frames.
        obvious = bool(cur[0] > 0.19 and ratio[0] > 1.03)
        if not (strong or multichannel or obvious):
            continue
        strength = float(np.max(np.minimum(peak_strength, 100.0)))
        candidates.append((i, strength))

    # Reject single-frame flashes: A -> bright B -> almost identical A.
    rejected: set[int] = set()
    candidate_set = {p for p, _ in candidates}
    for i in candidate_set:
        if i + 1 in candidate_set and i > 0 and i + 1 < n:
            before = metrics[i-1].signature
            after = metrics[i+1].signature
            diff = float(np.abs(before.astype(np.int16) - after.astype(np.int16)).mean()) / 255
            local = max(float(values[i, 0]), float(values[i+1, 0]), 0.01)
            if diff < min(0.036, local * 0.23):
                rejected.update((i, i + 1))

    # Avoid double registering immediately neighboring peaks unless they are
    # distinct strong cuts (allows 2–3-frame shots).
    chosen = [0]
    strengths = {0: 0.0}
    for idx, strength in candidates:
        if idx in rejected:
            continue
        if idx - chosen[-1] == 1:
            prev_idx = chosen[-1]
            if strength > strengths.get(prev_idx, 0):
                if prev_idx != 0:
                    chosen.pop()
                chosen.append(idx)
                strengths[idx] = strength
            continue
        chosen.append(idx)
        strengths[idx] = strength
    return chosen


def choose_representatives(metrics: list[FrameMetric], cuts: list[int]) -> list[int]:
    """One image per shot; first shot always preserves literal frame zero.

    Others choose from interior based on focus, motion stability and centrality.
    """
    if not metrics:
        return []
    if not cuts:
        return [0]
    reps = [0]
    n = len(metrics)
    for shot_idx, start in enumerate(cuts[1:], 1):
        end = cuts[shot_idx+1] if shot_idx + 1 < len(cuts) else n
        end = max(start + 1, min(end, n))
        length = end - start
        if length <= 2:
            reps.append(start)
            continue
        margin = min(max(1, round(length * 0.10)), max(1, (length - 1) // 3))
        lo, hi = start + margin, end - margin
        if lo >= hi:
            lo, hi = start, end
        step = max(1, (hi - lo) // 120)
        candidates = list(range(lo, hi, step))
        sharp = np.array([metrics[i].sharpness for i in candidates])
        motion = np.array([metrics[i].rgb for i in candidates])
        sharp_scale = float(np.percentile(sharp, 90)) + 1e-7
        motion_scale = float(np.percentile(motion, 80)) + 0.003
        best, best_score = candidates[0], -1e9
        for k, at in enumerate(candidates):
            sharp_score = min(1.0, float(sharp[k]) / sharp_scale)
            stability = 1.0 - min(1.0, float(motion[k]) / motion_scale)
            brightness = metrics[at].brightness
            exposure = 0.0 if 0.04 < brightness < 0.96 else -0.25
            center = 1 - abs((at - start) / length - 0.5) * 2
            score = 0.55 * sharp_score + 0.32 * stability + 0.13 * center + exposure
            if score > best_score:
                best_score, best = score, at
        reps.append(best)
    return reps


def _balanced_select(indices: list[int]) -> str:
    # Shallow tree significantly reduces FFmpeg expression checking cost.
    def build(start: int, end: int) -> str:
        if start >= end:
            return '0'
        mid = (start + end) // 2
        at = indices[mid]
        if end - start == 1:
            return f'eq(n,{at})'
        left = build(start, mid)
        right = build(mid + 1, end)
        return f'if(lt(n,{at}),{left},if(eq(n,{at}),1,{right}))'
    return build(0, len(indices))


_SHOWINFO_RE = re.compile(r'\[Parsed_showinfo_\d+[^\]]*\].*?\bpts_time:\s*(-?\d+(?:\.\d+)?)')


def export_selected_frames(video: Path, indices: list[int], ffmpeg: str,
                           folder: Path, duration: float | None,
                           on_progress: Progress, cancel: threading.Event | None) -> list[tuple[int, float, str]]:
    if not indices:
        raise ValueError('没有需要截图的帧')
    # '-filter_script:v' works on FFmpeg 5+, unlike newer -/filter:v syntax.
    filter_file = folder / 'extract_filter.txt'
    filter_file.write_text(
        "setpts=PTS-STARTPTS,select='" + _balanced_select(indices) + "',showinfo",
        encoding='utf-8',
    )
    log = folder / 'extract.log'
    output = folder / 'frame_%08d.jpg'
    cmd = [
        ffmpeg, '-hide_banner', '-nostdin', '-nostats', '-loglevel', 'info',
        '-progress', 'pipe:1', '-i', str(video), '-map', '0:v:0',
        '-filter_script:v', str(filter_file), '-fps_mode', 'vfr',
        '-q:v', '2', '-an', '-sn', '-dn', '-y', str(output),
    ]
    with log.open('w', encoding='utf-8') as err:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err, text=True,
                                encoding='utf-8', errors='replace', bufsize=1)
        finished = threading.Event()
        watcher = threading.Thread(target=_cancel_watcher, args=(proc, cancel, finished), daemon=True)
        watcher.start()
        try:
            if proc.stdout is None:
                raise RuntimeError('无法获取视频提取进度')
            for line in proc.stdout:
                if cancel and cancel.is_set():
                    raise ExtractionCancelled('已停止')
                key, sep, value = line.partition('=')
                if sep and key in ('out_time_us', 'out_time_ms') and duration:
                    try:
                        if on_progress:
                            on_progress(min(0.98, 0.60 + 0.38 * int(value) / 1_000_000 / duration))
                    except ValueError:
                        pass
            proc.stdout.close()
            status = proc.wait()
            if cancel and cancel.is_set():
                raise ExtractionCancelled('已停止')
            if status != 0:
                raise RuntimeError(f'高清截图失败（FFmpeg {status}）\n{_log_tail(log)}')
        finally:
            finished.set()
            _stop_process(proc)
            if proc.stdout and not proc.stdout.closed:
                proc.stdout.close()

    times = []
    with log.open('r', encoding='utf-8', errors='replace') as f:
        for line in f:
            match = _SHOWINFO_RE.search(line)
            if match:
                times.append(max(0.0, float(match.group(1))))
    image_files = sorted(folder.glob('frame_*.jpg'))
    if len(image_files) != len(indices) or len(image_files) != len(times):
        raise RuntimeError(
            f'提取不完整：预期 {len(indices)} 张，得到 {len(image_files)} 张，'
            f'时间戳 {len(times)} 个；本次结果不提交。'
        )
    selected = []
    for index, t, source in zip(indices, times, image_files):
        name = _safe_name(folder, timestamp_filename(t))
        source.rename(folder / name)
        selected.append((index, t, name))
    filter_file.unlink(missing_ok=True)
    log.unlink(missing_ok=True)
    return selected


def deduplicate_exported_frames(
        exported: list[tuple[int, float, str]], metrics: list[FrameMetric],
        folder: Path, fps_guess: float) -> list[tuple[int, float, str]]:
    """Remove near-identical frames exported with the same/adjacent video PTS.

    Some VFR/malformed streams assign indistinguishable PTS to several decoded
    frames. Preserve genuine fast cuts when sampled image signatures differ.
    """
    if len(exported) <= 1:
        return exported
    accepted: list[tuple[int, float, str]] = []
    window = max(0.045, min(0.100, 1.5 / max(fps_guess, 1.0)))
    for index, seconds, name in exported:
        duplicate = False
        # There may be several repeated neighboring candidates at one PTS.
        for before, prior_seconds, _ in reversed(accepted):
            if seconds - prior_seconds > window:
                break
            if abs(seconds - prior_seconds) > window or index >= len(metrics) or before >= len(metrics):
                continue
            a = metrics[index].signature.astype(np.int16)
            b = metrics[before].signature.astype(np.int16)
            if a.shape == b.shape and float(np.abs(a - b).mean()) / 255 < 0.018:
                duplicate = True
                break
        if duplicate:
            (folder / name).unlink(missing_ok=True)
        else:
            accepted.append((index, seconds, name))
    return accepted


def extract_scenes(video: str | Path, sensitivity: float = 0.75,
                   on_progress: Progress = None, cancel: threading.Event | None = None,
                   output_root: Path | str | None = None) -> ExtractionResult:
    if not 0 <= sensitivity <= 1:
        raise ValueError('灵敏度需要在 0～1 之间')
    video = Path(video).expanduser().resolve()
    if not video.is_file():
        raise FileNotFoundError(f'视频不存在：{video}')
    if cancel and cancel.is_set():
        raise ExtractionCancelled('已停止')
    ffmpeg = find_program('ffmpeg')
    if not ffmpeg:
        raise RuntimeError('未找到 FFmpeg。Mac 请执行 brew install ffmpeg')
    root = Path(output_root).expanduser().resolve() if output_root else video.parent
    root.mkdir(parents=True, exist_ok=True)
    fingerprint_start = video_fingerprint(video)
    duration, fps, total = probe_video(video)
    temporary = Path(tempfile.mkdtemp(prefix=f'.{video.stem}_scenecutter_', dir=root))
    try:
        metrics = scan_frames(video, ffmpeg, temporary / 'scan.log', total, on_progress, cancel)
        if cancel and cancel.is_set():
            raise ExtractionCancelled('已停止')
        boundaries = detect_boundaries(metrics, sensitivity)
        reps = choose_representatives(metrics, boundaries)
        if len(reps) != len(boundaries):
            raise RuntimeError('镜头边界和代表帧数量不一致')
        (temporary / 'scan.log').unlink(missing_ok=True)
        exported = export_selected_frames(video, reps, ffmpeg, temporary, duration, on_progress, cancel)
        if cancel and cancel.is_set():
            raise ExtractionCancelled('已停止')
        fps_guess = fps or (len(metrics) / duration if duration else 25.0)
        exported = deduplicate_exported_frames(exported, metrics, temporary, fps_guess)
        cuts_by_rep = {rep: start / fps_guess for start, rep in zip(boundaries, reps)}
        dest = unique_output_dir(video, root)
        shots = [Shot(seconds=t, path=dest / name, cut_seconds=cuts_by_rep[idx],
                      origin='auto', frame_index=idx) for idx, t, name in exported]
        if video_fingerprint(video) != fingerprint_start:
            raise RuntimeError('处理过程中源视频被修改，请在文件写入完成后重试。')
        result = ExtractionResult(video, dest, shots, sensitivity=sensitivity,
                                  source_fingerprint=fingerprint_start)
        # Write manifest BEFORE atomic rename, so resumed jobs are never half-visible.
        staging = ExtractionResult(video, temporary,
                                   [Shot(s.seconds, temporary / s.path.name, s.cut_seconds,
                                         s.origin, s.frame_index) for s in shots],
                                   sensitivity=sensitivity, source_fingerprint=fingerprint_start)
        save_manifest(staging)
        temporary.rename(dest)
        if on_progress:
            on_progress(1.0)
        return result
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)


def capture_manual_frame(result: ExtractionResult, seconds: float) -> Shot:
    """Seek to requested time and save a full-size high-quality JPEG safely."""
    seconds = max(0.0, float(seconds))
    if result.source_fingerprint and video_fingerprint(result.video) != result.source_fingerprint:
        raise RuntimeError('原视频已修改。请重新检测后再补截图，以免结果混入不同版本的画面。')
    ffmpeg = find_program('ffmpeg')
    if not ffmpeg:
        raise RuntimeError('未找到 FFmpeg')
    output_dir = result.output_dir
    temp = output_dir / '.manual_capture.jpg'
    try:
        proc = subprocess.run([
            ffmpeg, '-hide_banner', '-nostdin', '-loglevel', 'error',
            '-ss', f'{seconds:.3f}', '-i', str(result.video),
            '-map', '0:v:0', '-frames:v', '1', '-q:v', '2', '-an', '-sn', '-dn',
            '-y', str(temp),
        ], capture_output=True, text=True, timeout=120)
        if proc.returncode != 0 or not temp.is_file() or temp.stat().st_size == 0:
            raise RuntimeError('手动截图失败。请确认时间点位于视频时长内。\n' + proc.stderr[-500:])
        name = _safe_name(output_dir, timestamp_filename(seconds))
        destination = output_dir / name
        temp.rename(destination)
        shot = Shot(seconds, destination, seconds, 'manual', None)
        result.shots.append(shot)
        result.shots.sort(key=lambda s: (s.seconds, s.path.name))
        save_manifest(result)
        return shot
    finally:
        temp.unlink(missing_ok=True)


def exclude_shot(result: ExtractionResult, path: Path) -> bool:
    """Non-destructive remove. Files go into .excluded, not system Trash."""
    shot = next((s for s in result.shots if s.path == path), None)
    if shot is None:
        return False
    archive = result.output_dir / '.excluded'
    archive.mkdir(exist_ok=True)
    new = archive / _safe_name(archive, shot.path.name)
    shot.path.rename(new)
    result.shots.remove(shot)
    result.removed.append({
        'filename': shot.path.name, 'archived_filename': new.name,
        'seconds': shot.seconds, 'cut_seconds': shot.cut_seconds,
        'origin': shot.origin, 'frame_index': shot.frame_index,
    })
    save_manifest(result)
    return True


def remove_duplicate_existing_shots(result: ExtractionResult,
                                    tolerance_seconds: float = 0.065,
                                    difference_limit: float = 0.020) -> int:
    """Safely archive identical pictures with near-identical timestamps.

    Intended for upgrading existing 3.0 result directories. Different-looking
    shots sharing an unreliable PTS are kept, not deleted or merged.
    """
    from PIL import Image, ImageOps

    shots = sorted(result.shots, key=lambda s: (s.seconds, s.path.name))
    last_candidates: list[tuple[float, np.ndarray]] = []
    duplicates: list[Path] = []
    for shot in shots:
        if not shot.path.is_file():
            continue
        if last_candidates and shot.seconds - last_candidates[-1][0] > tolerance_seconds:
            last_candidates = []
        try:
            with Image.open(shot.path) as original:
                thumb = ImageOps.fit(ImageOps.exif_transpose(original).convert('RGB'), (48, 27))
                rgb = np.asarray(thumb, dtype=np.int16)
        except (OSError, ValueError):
            continue
        duplicate = any(abs(shot.seconds - timepoint) <= tolerance_seconds and
                        float(np.abs(rgb - other).mean()) / 255 < difference_limit
                        for timepoint, other in last_candidates)
        if duplicate:
            duplicates.append(shot.path)
        else:
            last_candidates.append((shot.seconds, rgb))
    removed = 0
    for path in duplicates:
        if exclude_shot(result, path):
            removed += 1
    return removed


def restore_last_excluded(result: ExtractionResult) -> Shot | None:
    if not result.removed:
        return None
    record = result.removed[-1]
    source = result.output_dir / '.excluded' / Path(record['archived_filename']).name
    if not source.is_file():
        return None
    new_name = _safe_name(result.output_dir, Path(record['filename']).name)
    restored = result.output_dir / new_name
    source.rename(restored)
    result.removed.pop()
    shot = Shot(float(record['seconds']), restored, float(record['cut_seconds']),
                str(record.get('origin', 'auto')), record.get('frame_index'))
    result.shots.append(shot)
    result.shots.sort(key=lambda s: (s.seconds, s.path.name))
    save_manifest(result)
    return shot


def export_contact_sheets(result: ExtractionResult, columns: int = 5,
                          rows: int = 6) -> list[Path]:
    """Create paginated high-resolution JPG contact sheets via Pillow."""
    from PIL import Image, ImageDraw, ImageFont, ImageOps

    if not result.shots:
        raise ValueError('当前没有镜头截图')
    columns = max(1, int(columns))
    rows = max(1, int(rows))
    tile_w, tile_h, header = 390, 252, 105
    cell_pic = (tile_w - 22, tile_h - 44)
    shots = sorted(result.shots, key=lambda s: (s.seconds, s.path.name))
    total_pages = math.ceil(len(shots) / (columns * rows))
    folder = result.output_dir
    paths = []
    try:
        font_path = next((p for p in [
            '/System/Library/Fonts/PingFang.ttc',
            '/System/Library/Fonts/Supplemental/Arial.ttf',
            '/Library/Fonts/Arial.ttf',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        ] if Path(p).exists()), None)
        title_font = ImageFont.truetype(font_path, 25) if font_path else ImageFont.load_default()
        small_font = ImageFont.truetype(font_path, 18) if font_path else ImageFont.load_default()
    except OSError:
        title_font = small_font = ImageFont.load_default()

    for page in range(total_pages):
        section = shots[page * columns * rows: (page+1) * columns * rows]
        canvas = Image.new('RGB', (columns * tile_w, header + rows * tile_h), '#111820')
        draw = ImageDraw.Draw(canvas)
        draw.text((20, 22), f'SCENE CUTTER  |  {result.video.name}',
                  font=title_font, fill='#f3f6fb')
        draw.text((20, 58), f'{len(shots)} shots   |   Page {page+1} / {total_pages}',
                  font=small_font, fill='#9cacc4')
        for k, shot in enumerate(section):
            col, row = k % columns, k // columns
            x, y = col * tile_w, header + row * tile_h
            draw.rounded_rectangle([x+5, y+5, x+tile_w-5, y+tile_h-5], radius=8, fill='#252e3a')
            try:
                with Image.open(shot.path) as src:
                    thumb = ImageOps.contain(ImageOps.exif_transpose(src).convert('RGB'), cell_pic)
                    px = x + (tile_w - thumb.width) // 2
                    py = y + 12 + (cell_pic[1] - thumb.height) // 2
                    canvas.paste(thumb, (px, py))
            except OSError:
                draw.text((x+25, y+90), 'Image not found', fill='#ff9a8a', font=small_font)
            draw.text((x+14, y+tile_h-32),
                      f'{page*columns*rows+k+1:03d}    {format_time(shot.seconds)}',
                      fill='#e8f0fc', font=small_font)
        out = folder / f'overview_{page+1:03d}.jpg'
        canvas.save(out, 'JPEG', quality=92, subsampling=0)
        paths.append(out)
    # Remove older surplus pages when the result gets smaller, but not user images.
    for old in folder.glob('overview_*.jpg'):
        if old not in paths and re.fullmatch(r'overview_\d{3}\.jpg', old.name):
            old.unlink()
    return paths
