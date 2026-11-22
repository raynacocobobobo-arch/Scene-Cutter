#!/usr/bin/env python3
"""Persistent diagnostics for Python exceptions and fatal native errors."""
from __future__ import annotations

import faulthandler
import os
import platform
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

_LOG_HANDLE = None
_LOG_LOCK = threading.RLock()


def log_path() -> Path:
    return Path(os.environ.get('LOCALAPPDATA') or (Path.home() / 'AppData' / 'Local')) / 'SceneCutter' / 'Logs' / 'crash.log'


def log_event(message: str) -> None:
    try:
        path = log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_LOCK, path.open('a', encoding='utf-8') as f:
            f.write(f'[{datetime.now().isoformat(timespec="seconds")}] {message}\n')
    except OSError:
        pass


def log_exception(exc_type, exc_value, exc_tb) -> None:
    log_event('Python 未处理异常:\n' + ''.join(traceback.format_exception(exc_type, exc_value, exc_tb)))
    sys.__excepthook__(exc_type, exc_value, exc_tb)


def _thread_exception(args) -> None:
    log_event('线程异常: ' + args.thread.name + '\n' +
              ''.join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))


def install_crash_logging() -> None:
    global _LOG_HANDLE
    if _LOG_HANDLE is not None:
        return
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Keep the latest backup if this log grows large, without unbounded storage.
    try:
        if path.exists() and path.stat().st_size > 8_000_000:
            path.replace(path.with_suffix('.previous.log'))
    except OSError:
        pass
    # Keep the file open: faulthandler needs a live file descriptor on SIGSEGV/SIGABRT.
    _LOG_HANDLE = path.open('a', encoding='utf-8', buffering=1)
    faulthandler.enable(file=_LOG_HANDLE, all_threads=True)
    sys.excepthook = log_exception
    threading.excepthook = _thread_exception
    log_event(f'Start: Python {platform.python_version()}, OS {platform.platform()}, PID {os.getpid()}')
