"""
Conflict Dialog
Shown when a profile load is attempted but some apps are still running.
The user can close those apps and click "Check Again" to retry.
"""

from __future__ import annotations
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QDialogButtonBox,
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont

from core.switcher import ModuleConflict


class ConflictDialog(QDialog):
    """
    Shows a list of running apps that must be closed before the profile load
    can proceed. Has a "Check Again" button that re-scans.
    """

    def __init__(self, parent=None, conflicts: list[ModuleConflict] | None = None, recheck_fn=None):
        super().__init__(parent)
        self.conflicts = conflicts or []
        self.recheck_fn = recheck_fn  # Callable[[], list[ModuleConflict]]
        self.setWindowTitle("Close Running Applications")
        self.setModal(True)
        self.setMinimumWidth(420)
        self._build_ui()
        self._refresh_conflicts(self.conflicts)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 20, 20, 20)

        header = QLabel("⚠️  Please close these applications before switching profiles:")
        header.setFont(QFont("Segoe UI", 11, QFont.Weight.Medium))
        header.setWordWrap(True)
        layout.addWidget(header)

        self.conflict_area = QVBoxLayout()
        self.conflict_area.setSpacing(6)
        layout.addLayout(self.conflict_area)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #5ce05c; font-weight: bold;")
        layout.addWidget(self.status_label)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #333;")
        layout.addWidget(sep)

        btn_row = QHBoxLayout()
        self.recheck_btn = QPushButton("🔄  Check Again")
        self.recheck_btn.clicked.connect(self._on_recheck)
        self.recheck_btn.setDefault(False)

        self.proceed_btn = QPushButton("▶  Load Profile Anyway")
        self.proceed_btn.setStyleSheet("background: #c04040; color: white;")
        self.proceed_btn.setToolTip("Force-load even if apps are still running (may cause data loss)")
        self.proceed_btn.clicked.connect(self._on_force_proceed)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)

        btn_row.addWidget(self.recheck_btn)
        btn_row.addStretch()
        btn_row.addWidget(self.proceed_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def _refresh_conflicts(self, conflicts: list[ModuleConflict]):
        # Clear existing widgets
        while self.conflict_area.count():
            item = self.conflict_area.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not conflicts:
            self.status_label.setText("✅ All applications are closed — you can proceed!")
            self.proceed_btn.setVisible(False)
            # Auto-accept after a short delay
            QTimer.singleShot(1200, self.accept)
        else:
            self.status_label.setText("")
            for c in conflicts:
                row = QLabel(f"  {c.display_name}   (PID: {', '.join(str(p) for p in c.pids)})")
                row.setStyleSheet(
                    "background: #2a1818; color: #ff8080; border-radius: 4px;"
                    "padding: 6px 10px; font-family: 'Consolas', monospace;"
                )
                self.conflict_area.addWidget(row)

    def _on_recheck(self):
        if self.recheck_fn:
            new_conflicts = self.recheck_fn()
            self._refresh_conflicts(new_conflicts)

    def _on_force_proceed(self):
        """Accept the dialog, signalling caller to proceed regardless."""
        self.setResult(2)  # Custom result code for "force"
        self.close()

    @property
    def forced(self) -> bool:
        return self.result() == 2
