from pathlib import Path


def test_pyside_pinned_away_from_612():
    root = Path(__file__).resolve().parents[1]
    assert 'PySide6==6.11.3' in (root / 'requirements.txt').read_text()


def test_qt_ui_deleted_before_python_interpreter_exits():
    root = Path(__file__).resolve().parents[1]
    code = (root / 'app.py').read_text()
    assert '_cleanup_qt_before_interpreter_exit(window)' in code
    assert 'window.deleteLater()' in code
    assert 'QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)' in code
    assert 'window.player.setVideoOutput(None)' in code
