"""Check the real desktop imports and window without voice or network access."""
from __future__ import annotations

import json
import sys
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6 import __version__ as qt_version
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QApplication

from jarvis_agent import ui
from jarvis_agent.config import PROJECT_ROOT
from jarvis_agent.memory import LOCAL_MEMORY


class CheckWorker(QObject):
    state_changed = Signal(str)
    status_changed = Signal(str)
    transcript_changed = Signal(str)
    detail_changed = Signal(str)
    audio_level_changed = Signal(float)
    log_line = Signal(str)
    runtime_event = Signal(object)
    finished = Signal()

    @Slot()
    def run(self):
        self.finished.emit()

    def stop(self):
        pass


def main() -> int:
    # The check is a separate process; the normal entry and worker stay intact.
    ui.AssistantWorker = CheckWorker
    ui.settings = replace(ui.settings, ui_fullscreen=False)
    app = QApplication([])
    window = ui.JarvisWindow()
    window.show()
    deadline = time.monotonic() + 5
    while window._thread.isRunning() and time.monotonic() < deadline:
        app.processEvents()
    if window._thread.isRunning():
        raise RuntimeError("desktop_check_thread_did_not_finish")
    app.processEvents()
    if not window.close():
        raise RuntimeError("desktop_check_window_did_not_close")
    app.processEvents()
    print(json.dumps({
        "status": "ok", "project_root": str(PROJECT_ROOT),
        "python": sys.executable, "qt_version": qt_version,
        "ui": "window_created_and_closed", "worker": "fixture",
        "microphone": "not_used", "network": "not_used",
        "memory_db_path": str(LOCAL_MEMORY.db_path),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
