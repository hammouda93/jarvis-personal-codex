from __future__ import annotations

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import QHeaderView, QLabel, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from .event_bus import BusEvent
from .runtime_activity import RuntimeActivityState


class RuntimeActivityPanel(QWidget):
    """Small developer view fed exclusively by real runtime events."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            "QLabel { color: #c6d9e5; font-size: 11px; }"
            "QTreeWidget { color: #dce8ee; background: #0a1420; border: 1px solid #253544; }"
            "QHeaderView::section { color: #b5cddb; background: #122332; padding: 4px; }"
        )
        self.state = RuntimeActivityState()
        self.summary = QLabel("Activité des outils — en attente d'un tour agent")
        self.summary.setTextFormat(Qt.PlainText)
        self.route = QLabel("Boucle agent observée ; actions directes hors de ce panneau")
        self.route.setTextFormat(Qt.PlainText)
        self.route.setWordWrap(True)
        self.calls = QTreeWidget()
        self.calls.setColumnCount(3)
        self.calls.setHeaderLabels(["Outil", "Résultat / preuve", "Durée (ms)"])
        self.calls.setRootIsDecorated(False)
        self.calls.setMaximumHeight(160)
        self.calls.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.calls.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self.calls.header().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.summary)
        layout.addWidget(self.route)
        layout.addWidget(self.calls)

    @Slot(object)
    def on_event(self, event: BusEvent) -> None:
        if not isinstance(event, BusEvent) or not self.state.apply(event):
            return
        labels = {
            "idle": "En attente", "running": "Tour en cours",
            "thinking": "Réflexion", "acting": "Action en cours",
            "finished": "Tour terminé — critères de mission non évalués",
            "error": "Tour interrompu par une erreur",
        }
        summary = labels[self.state.status]
        if self.state.failed_action_count:
            summary += f" · {self.state.failed_action_count} échec(s) observé(s)"
        if self.state.dropped_calls:
            summary += f" · {self.state.dropped_calls} appel(s) plus ancien(s) masqué(s)"
        self.summary.setText(summary)
        self.route.setText(
            f"Route configurée : {self.state.configured_provider or '?'} / "
            f"{self.state.configured_model or '?'} · tour {self.state.turn_id}"
        )
        result_labels = {
            "running": "EN COURS", "completed": "TERMINÉ · NON VÉRIFIÉ",
            "verified": "VÉRIFIÉ · PREUVE OUTIL", "failed": "ÉCHEC",
        }
        self.calls.clear()
        for call in self.state.calls.values():
            item = QTreeWidgetItem([
                call.name, result_labels[call.status],
                f"{call.duration_ms:.1f}" if call.duration_ms is not None else "",
            ])
            self.calls.addTopLevelItem(item)
