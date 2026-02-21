"""
VRProfile Switcher — Main Window
PyQt6 GUI with a dark VR-themed aesthetic.
Layout: left sidebar (profile list) + right panel (profile detail + actions).
"""

from __future__ import annotations
import logging
from pathlib import Path
from typing import Optional

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QLabel, QPushButton,
    QFrame, QSplitter, QTextEdit, QGroupBox, QScrollArea,
    QMessageBox, QProgressBar, QStatusBar, QMenu, QInputDialog,
    QCheckBox, QSizePolicy, QDialog, QDialogButtonBox,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize
from PyQt6.QtGui import QFont, QColor, QPalette, QAction, QIcon

from core.profile_manager import Profile, ProfileManager
from core.settings import AppSettings
from core.switcher import Switcher, ModuleConflict, OperationResult
from modules import MODULE_REGISTRY, get_module
from gui.profile_editor import ProfileEditorDialog
from gui.conflict_dialog import ConflictDialog

logger = logging.getLogger(__name__)

DARK_STYLESHEET = """
QMainWindow, QWidget {
    background-color: #0f0f14;
    color: #d4d4e8;
    font-family: 'Segoe UI', sans-serif;
    font-size: 13px;
}
QSplitter::handle {
    background: #1e1e2e;
    width: 2px;
}
QListWidget {
    background-color: #13131c;
    border: none;
    border-right: 1px solid #1e1e2e;
    outline: none;
}
QListWidget::item {
    padding: 10px 14px;
    border-bottom: 1px solid #1a1a28;
    border-radius: 0px;
}
QListWidget::item:selected {
    background-color: #1e1e3a;
    color: #a0a8ff;
    border-left: 3px solid #6060ff;
}
QListWidget::item:hover:!selected {
    background-color: #17172a;
}
QPushButton {
    background-color: #1e1e3a;
    color: #a0a8ff;
    border: 1px solid #3030a0;
    border-radius: 6px;
    padding: 7px 16px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #28285a;
    border-color: #5050c0;
}
QPushButton:pressed {
    background-color: #141430;
}
QPushButton:disabled {
    color: #404060;
    border-color: #202040;
}
QPushButton#primary {
    background-color: #3030a0;
    color: #e8e8ff;
    border-color: #5050c0;
    font-weight: 600;
}
QPushButton#primary:hover {
    background-color: #4040c0;
}
QPushButton#danger {
    background-color: #501818;
    color: #ffa0a0;
    border-color: #803030;
}
QPushButton#danger:hover {
    background-color: #702020;
}
QPushButton#success {
    background-color: #184030;
    color: #80ffb0;
    border-color: #30804060;
}
QPushButton#success:hover {
    background-color: #205040;
}
QGroupBox {
    border: 1px solid #1e1e3a;
    border-radius: 8px;
    margin-top: 10px;
    padding-top: 8px;
    font-weight: 600;
    color: #8080c0;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}
QTextEdit {
    background-color: #13131c;
    border: 1px solid #1e1e3a;
    border-radius: 6px;
    color: #a0a0c0;
    padding: 6px;
    font-family: 'Consolas', monospace;
    font-size: 11px;
}
QScrollArea {
    border: none;
    background: transparent;
}
QScrollBar:vertical {
    background: #13131c;
    width: 8px;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #30306060;
    border-radius: 4px;
    min-height: 30px;
}
QStatusBar {
    background-color: #0a0a12;
    color: #505080;
    border-top: 1px solid #1a1a2a;
}
QProgressBar {
    background-color: #13131c;
    border: 1px solid #1e1e3a;
    border-radius: 4px;
    text-align: center;
    color: #a0a8ff;
    height: 16px;
}
QProgressBar::chunk {
    background-color: #3030a0;
    border-radius: 3px;
}
QMenu {
    background-color: #1a1a2a;
    border: 1px solid #2a2a4a;
    border-radius: 6px;
    padding: 4px;
}
QMenu::item {
    padding: 6px 20px;
    border-radius: 4px;
}
QMenu::item:selected {
    background-color: #2a2a5a;
    color: #a0a8ff;
}
QLabel#header {
    font-size: 22px;
    font-weight: 700;
    color: #8080ff;
    letter-spacing: 1px;
}
QLabel#subheader {
    font-size: 12px;
    color: #505080;
}
"""


class WorkerThread(QThread):
    """Background thread for backup/restore operations."""
    progress = pyqtSignal(str, str, str)   # module_id, step, message
    finished = pyqtSignal(object)           # OperationResult

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        result = self._fn(progress=self.progress.emit)
        self.finished.emit(result)


class ProfileListItem(QListWidgetItem):
    def __init__(self, profile: Profile):
        super().__init__()
        self.profile = profile
        self._refresh()

    def _refresh(self):
        enabled = self.profile.enabled_modules()
        icons = []
        for mid in enabled:
            cls = MODULE_REGISTRY.get(mid)
            if cls:
                icons.append(cls.icon)
        icon_str = " ".join(icons) if icons else "○"
        self.setText(f"  {self.profile.name}\n  {icon_str}")
        self.setSizeHint(QSize(0, 56))


class PartialSaveDialog(QDialog):
    """
    Dialog that lets the user pick which modules to save individually.
    Only shows modules that are enabled in the current profile.
    """

    def __init__(self, parent=None, profile=None):
        super().__init__(parent)
        self.profile = profile
        self.setWindowTitle("Save Selected Modules")
        self.setModal(True)
        self.setMinimumWidth(360)
        self._checkboxes: dict[str, QCheckBox] = {}
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        header = QLabel("Choose which modules to save into this profile:")
        header.setWordWrap(True)
        header.setStyleSheet("color: #a0a0c0; font-size: 12px;")
        layout.addWidget(header)

        # One checkbox per enabled module
        for mid in self.profile.enabled_modules():
            cls = MODULE_REGISTRY.get(mid)
            if not cls:
                continue
            module = cls()
            cb = QCheckBox(f"{module.icon}  {module.display_name}")
            cb.setChecked(True)  # default: all ticked
            cb.setFont(QFont("Segoe UI", 10))
            layout.addWidget(cb)
            self._checkboxes[mid] = cb

        if not self._checkboxes:
            layout.addWidget(QLabel("No modules enabled in this profile."))

        # Select all / none shortcuts
        sel_row = QHBoxLayout()
        all_btn = QPushButton("Select All")
        all_btn.setFixedWidth(90)
        all_btn.clicked.connect(lambda: [cb.setChecked(True) for cb in self._checkboxes.values()])
        none_btn = QPushButton("Select None")
        none_btn.setFixedWidth(90)
        none_btn.clicked.connect(lambda: [cb.setChecked(False) for cb in self._checkboxes.values()])
        sel_row.addWidget(all_btn)
        sel_row.addWidget(none_btn)
        sel_row.addStretch()
        layout.addLayout(sel_row)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #333;")
        layout.addWidget(sep)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("💾  Save Selected")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_modules(self) -> list[str]:
        return [mid for mid, cb in self._checkboxes.items() if cb.isChecked()]


class MainWindow(QMainWindow):
    def __init__(self, pm: ProfileManager, settings: AppSettings):
        super().__init__()
        self.pm = pm
        self.settings = settings
        self.switcher = Switcher(pm)
        self._current_profile: Optional[Profile] = None
        self._worker: Optional[WorkerThread] = None

        self.setWindowTitle("VRProfile Switcher")
        self.setMinimumSize(820, 560)
        self.setStyleSheet(DARK_STYLESHEET)

        self._build_ui()
        self._refresh_profile_list()

        # Restore window geometry
        geom = self.settings.get("window_geometry", "")
        if geom:
            try:
                self.restoreGeometry(bytes.fromhex(geom))
            except Exception:
                pass

        # Status refresh timer
        self._status_timer = QTimer(self)
        self._status_timer.timeout.connect(self._refresh_status_indicators)
        self._status_timer.start(5000)

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(2)
        root.addWidget(splitter)

        # ---- LEFT: Sidebar ----
        sidebar = self._build_sidebar()
        splitter.addWidget(sidebar)

        # ---- RIGHT: Detail panel ----
        detail = self._build_detail_panel()
        splitter.addWidget(detail)

        splitter.setSizes([240, 580])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")

    def _build_sidebar(self) -> QWidget:
        w = QWidget()
        w.setMinimumWidth(200)
        w.setMaximumWidth(280)
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Logo area
        logo_area = QWidget()
        logo_area.setStyleSheet("background: #0d0d18; border-bottom: 1px solid #1a1a28;")
        logo_layout = QVBoxLayout(logo_area)
        logo_layout.setContentsMargins(14, 14, 14, 12)
        logo_layout.setSpacing(2)

        title_lbl = QLabel("VRProfile")
        title_lbl.setObjectName("header")
        logo_layout.addWidget(title_lbl)

        sub_lbl = QLabel("Multi-app profile switcher")
        sub_lbl.setObjectName("subheader")
        logo_layout.addWidget(sub_lbl)

        layout.addWidget(logo_area)

        # Profile list
        self.profile_list = QListWidget()
        self.profile_list.setFont(QFont("Segoe UI", 10))
        self.profile_list.currentItemChanged.connect(self._on_profile_selected)
        self.profile_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.profile_list.customContextMenuRequested.connect(self._show_profile_context_menu)
        layout.addWidget(self.profile_list)

        # Sidebar action buttons
        btn_area = QWidget()
        btn_area.setStyleSheet("background: #0d0d18; border-top: 1px solid #1a1a28;")
        btn_layout = QHBoxLayout(btn_area)
        btn_layout.setContentsMargins(8, 8, 8, 8)

        new_btn = QPushButton("＋ New")
        new_btn.clicked.connect(self._on_new_profile)
        btn_layout.addWidget(new_btn)

        self.dup_btn = QPushButton("⧉ Duplicate")
        self.dup_btn.clicked.connect(self._on_duplicate_profile)
        self.dup_btn.setEnabled(False)
        self.dup_btn.setToolTip("Duplicate this profile including all saved module data")
        btn_layout.addWidget(self.dup_btn)

        self.del_btn = QPushButton("🗑 Delete")
        self.del_btn.setObjectName("danger")
        self.del_btn.clicked.connect(self._on_delete_profile)
        self.del_btn.setEnabled(False)
        btn_layout.addWidget(self.del_btn)

        layout.addWidget(btn_area)
        return w

    def _build_detail_panel(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(24, 20, 24, 16)
        layout.setSpacing(16)

        # Profile name header
        header_row = QHBoxLayout()
        self.profile_name_lbl = QLabel("Select a profile →")
        self.profile_name_lbl.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        self.profile_name_lbl.setStyleSheet("color: #c0c0ff;")
        header_row.addWidget(self.profile_name_lbl)
        header_row.addStretch()

        self.edit_btn = QPushButton("✏ Edit")
        self.edit_btn.clicked.connect(self._on_edit_profile)
        self.edit_btn.setEnabled(False)
        header_row.addWidget(self.edit_btn)

        layout.addLayout(header_row)

        # Notes
        self.notes_lbl = QLabel("")
        self.notes_lbl.setStyleSheet("color: #606080; font-size: 12px; font-style: italic;")
        self.notes_lbl.setWordWrap(True)
        layout.addWidget(self.notes_lbl)

        # Module status group
        module_group = QGroupBox("Modules")
        module_group_layout = QVBoxLayout(module_group)
        module_group_layout.setSpacing(6)

        self._module_rows: dict[str, dict] = {}
        for mid, cls in MODULE_REGISTRY.items():
            row = self._build_module_status_row(mid, cls)
            module_group_layout.addWidget(row)

        layout.addWidget(module_group)

        # Action buttons
        action_group = QGroupBox("Actions")
        action_layout = QHBoxLayout(action_group)
        action_layout.setSpacing(10)

        self.backup_btn = QPushButton("💾  Save All → Profile")
        self.backup_btn.setObjectName("primary")
        self.backup_btn.setEnabled(False)
        self.backup_btn.clicked.connect(self._on_backup)
        self.backup_btn.setToolTip("Save current settings for all enabled modules into this profile")
        action_layout.addWidget(self.backup_btn)

        self.partial_backup_btn = QPushButton("💾  Save Selected…")
        self.partial_backup_btn.setEnabled(False)
        self.partial_backup_btn.clicked.connect(self._on_partial_backup)
        self.partial_backup_btn.setToolTip("Choose which modules to save into this profile")
        action_layout.addWidget(self.partial_backup_btn)

        self.load_btn = QPushButton("▶  Load This Profile")
        self.load_btn.setObjectName("success")
        self.load_btn.setEnabled(False)
        self.load_btn.clicked.connect(self._on_load_profile)
        action_layout.addWidget(self.load_btn)

        layout.addWidget(action_group)

        # Undo last switch
        undo_layout = QHBoxLayout()
        self.undo_btn = QPushButton("↩  Undo Last Switch")
        self.undo_btn.setEnabled(False)
        self.undo_btn.clicked.connect(self._on_undo_last)
        self.undo_btn.setToolTip("Restore the auto-backup taken before the last profile load")
        undo_layout.addWidget(self.undo_btn)
        undo_layout.addStretch()
        layout.addLayout(undo_layout)

        # Progress bar (hidden when idle)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setRange(0, 0)  # indeterminate
        layout.addWidget(self.progress_bar)

        # Log output
        log_group = QGroupBox("Operation Log")
        log_layout = QVBoxLayout(log_group)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(130)
        log_layout.addWidget(self.log_text)
        layout.addWidget(log_group)

        layout.addStretch()

        self._update_undo_btn()
        return w

    def _build_module_status_row(self, mid: str, cls) -> QWidget:
        module = cls()
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(8)

        enabled_cb = QCheckBox()
        enabled_cb.setEnabled(False)  # Display only — editing done in editor dialog
        layout.addWidget(enabled_cb)

        icon_lbl = QLabel(module.icon)
        icon_lbl.setFont(QFont("Segoe UI Emoji", 13))
        layout.addWidget(icon_lbl)

        name_lbl = QLabel(module.display_name)
        name_lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.Medium))
        layout.addWidget(name_lbl)

        layout.addStretch()

        status_lbl = QLabel("●")
        status_lbl.setStyleSheet("color: #404060; font-size: 16px;")
        status_lbl.setToolTip("Not running")
        layout.addWidget(status_lbl)

        self._module_rows[mid] = {
            "checkbox": enabled_cb,
            "status_dot": status_lbl,
        }
        return row

    # ------------------------------------------------------------------
    # Profile list management
    # ------------------------------------------------------------------

    def _refresh_profile_list(self):
        self.profile_list.blockSignals(True)
        self.profile_list.clear()
        profiles = self.pm.list_profiles()
        for p in profiles:
            item = ProfileListItem(p)
            self.profile_list.addItem(item)
        self.profile_list.blockSignals(False)

        # Re-select last used
        last = self.settings.get("last_profile", "")
        if last:
            for i in range(self.profile_list.count()):
                item = self.profile_list.item(i)
                if isinstance(item, ProfileListItem) and item.profile.name == last:
                    self.profile_list.setCurrentItem(item)
                    break

        if self.profile_list.currentItem() is None and self.profile_list.count() > 0:
            self.profile_list.setCurrentRow(0)

        self._update_undo_btn()

    def _on_profile_selected(self, current: QListWidgetItem, previous):
        if not isinstance(current, ProfileListItem):
            self._set_no_profile()
            return
        profile = current.profile
        self._current_profile = profile
        self._show_profile(profile)
        self.settings.set("last_profile", profile.name)

    def _show_profile(self, profile: Profile):
        self.profile_name_lbl.setText(profile.name)
        self.notes_lbl.setText(profile.notes or "")
        self.edit_btn.setEnabled(True)
        self.dup_btn.setEnabled(True)
        self.del_btn.setEnabled(True)
        self.backup_btn.setEnabled(True)
        self.partial_backup_btn.setEnabled(True)
        self.load_btn.setEnabled(True)

        # Update module checkboxes
        for mid, widgets in self._module_rows.items():
            widgets["checkbox"].setChecked(profile.is_module_enabled(mid))

        self._refresh_status_indicators()

    def _set_no_profile(self):
        self._current_profile = None
        self.profile_name_lbl.setText("Select a profile →")
        self.notes_lbl.setText("")
        self.edit_btn.setEnabled(False)
        self.dup_btn.setEnabled(False)
        self.del_btn.setEnabled(False)
        self.backup_btn.setEnabled(False)
        self.load_btn.setEnabled(False)
        for widgets in self._module_rows.values():
            widgets["checkbox"].setChecked(False)

    def _refresh_status_indicators(self):
        """Update the running-status dots for each module."""
        if not self._current_profile:
            return
        profile = self._current_profile
        for mid, widgets in self._module_rows.items():
            dot: QLabel = widgets["status_dot"]
            if not profile.is_module_enabled(mid):
                dot.setStyleSheet("color: #202035; font-size: 16px;")
                dot.setToolTip("Disabled in this profile")
                continue
            try:
                module = get_module(mid, profile.get_module_options(mid))
                status = module.get_status()
                if status.is_running:
                    dot.setStyleSheet("color: #40e080; font-size: 16px;")
                    dot.setToolTip(f"Running (PID: {', '.join(str(p) for p in status.process_pids)})")
                else:
                    dot.setStyleSheet("color: #404060; font-size: 16px;")
                    dot.setToolTip("Not running")
            except Exception:
                dot.setStyleSheet("color: #604040; font-size: 16px;")
                dot.setToolTip("Status check failed")

    # ------------------------------------------------------------------
    # Profile actions
    # ------------------------------------------------------------------

    def _on_new_profile(self):
        existing = [p.name for p in self.pm.list_profiles()]
        dlg = ProfileEditorDialog(self, profile=None, existing_names=existing)
        if dlg.exec():
            profile = dlg.profile
            try:
                created = self.pm.create_profile(profile.name, profile.notes)
                created.modules = profile.modules
                self.pm.save_profile_meta(created)
                self._refresh_profile_list()
                self._log(f"✅ Created profile '{profile.name}'")
                self.status_bar.showMessage(f"Profile '{profile.name}' created — saving current settings...")

                # Immediately snapshot current live settings into the new profile
                self._set_busy(True)
                self._log(f"💾 Capturing current settings into '{profile.name}'...")

                def do_initial_backup(progress):
                    return self.switcher.backup_to_profile(created, progress=progress)

                def on_initial_backup_done(result: OperationResult):
                    self._set_busy(False)
                    if result.success:
                        self._log(f"✅ Current settings saved to '{created.name}' — {result.summary}")
                        self.status_bar.showMessage(f"Profile '{created.name}' created and populated")
                    else:
                        self._log(f"⚠ Profile created but some modules failed to save:")
                        self._log_errors(result)
                        self.status_bar.showMessage(f"Profile '{created.name}' created (some modules had errors)")

                self._run_worker(do_initial_backup, on_done=on_initial_backup_done)

            except ValueError as e:
                QMessageBox.warning(self, "Error", str(e))

    def _on_duplicate_profile(self):
        if not self._current_profile:
            return
        src = self._current_profile
        existing = [p.name for p in self.pm.list_profiles()]

        # Suggest a name
        base = src.name
        candidate = f"{base} (copy)"
        n = 2
        while candidate in existing:
            candidate = f"{base} (copy {n})"
            n += 1

        name, ok = QInputDialog.getText(
            self, "Duplicate Profile",
            "Name for the duplicate profile:",
            text=candidate,
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        if name in existing:
            QMessageBox.warning(self, "Error", f"A profile named '{name}' already exists.")
            return

        try:
            self.pm.duplicate_profile(src.name, name)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to duplicate profile: {e}")
            return

        self._refresh_profile_list()
        # Select the new profile
        for i in range(self.profile_list.count()):
            item = self.profile_list.item(i)
            if isinstance(item, ProfileListItem) and item.profile.name == name:
                self.profile_list.setCurrentItem(item)
                break
        self._log(f"✅ Duplicated '{src.name}' → '{name}'")
        self.status_bar.showMessage(f"Profile duplicated as '{name}'")

    def _on_edit_profile(self):
        if not self._current_profile:
            return
        existing = [p.name for p in self.pm.list_profiles() if p.name != self._current_profile.name]
        dlg = ProfileEditorDialog(self, profile=self._current_profile, existing_names=existing)
        if dlg.exec():
            updated = dlg.profile
            if updated.name != self._current_profile.name:
                try:
                    self.pm.rename_profile(self._current_profile.name, updated.name)
                except Exception as e:
                    QMessageBox.warning(self, "Rename failed", str(e))
                    return
            updated_profile = self.pm.get_profile(updated.name)
            if updated_profile:
                updated_profile.notes = updated.notes
                updated_profile.modules = updated.modules
                self.pm.save_profile_meta(updated_profile)
            self._refresh_profile_list()
            self._log(f"✅ Updated profile '{updated.name}'")

    def _on_delete_profile(self):
        if not self._current_profile:
            return
        name = self._current_profile.name
        reply = QMessageBox.question(
            self, "Delete Profile",
            f"Delete profile '{name}' and all its saved configs?\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.pm.delete_profile(name)
            self._set_no_profile()
            self._refresh_profile_list()
            self._log(f"🗑 Deleted profile '{name}'")
            self.status_bar.showMessage(f"Profile '{name}' deleted")

    def _show_profile_context_menu(self, pos):
        item = self.profile_list.itemAt(pos)
        if not isinstance(item, ProfileListItem):
            return
        menu = QMenu(self)
        menu.addAction("✏ Edit", self._on_edit_profile)
        menu.addAction("⧉ Duplicate", self._on_duplicate_profile)
        menu.addAction("💾 Save Current → This Profile", self._on_backup)
        menu.addAction("▶ Load This Profile", self._on_load_profile)
        menu.addSeparator()
        menu.addAction("🗑 Delete", self._on_delete_profile)
        menu.exec(self.profile_list.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------
    # Backup action
    # ------------------------------------------------------------------

    def _on_backup(self):
        if not self._current_profile:
            return
        profile = self._current_profile
        if self.settings.get("confirm_before_restore", True):
            reply = QMessageBox.question(
                self, "Save Current Config",
                f"Overwrite the saved config in profile '{profile.name}' with the current live config?\n\n"
                f"Modules: {', '.join(profile.enabled_modules()) or 'none'}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self._set_busy(True)
        self._log(f"💾 Backing up to profile '{profile.name}'...")

        def do_backup(progress):
            return self.switcher.backup_to_profile(profile, progress=progress)

        self._run_worker(do_backup, on_done=self._on_backup_done)

    def _on_partial_backup(self):
        """Show a dialog to pick which modules to save, then back up only those."""
        if not self._current_profile:
            return
        profile = self._current_profile

        dlg = PartialSaveDialog(self, profile=profile)
        if not dlg.exec():
            return

        selected_modules = dlg.selected_modules()
        if not selected_modules:
            self.status_bar.showMessage("No modules selected — nothing saved")
            return

        self._set_busy(True)
        names = ", ".join(selected_modules)
        self._log(f"💾 Saving selected modules to '{profile.name}': {names}...")

        def do_partial_backup(progress):
            # Temporarily override enabled modules for this backup
            import copy
            from core.switcher import OperationResult
            result = OperationResult(success=True)
            dest_dir = self.pm.profile_dir(profile.name)
            for mid in selected_modules:
                if progress:
                    progress(mid, "backup", f"Backing up {mid}...")
                try:
                    from modules import get_module
                    module = get_module(mid, profile.get_module_options(mid))
                    ok, msg = module.backup(dest_dir)
                    result.module_results[mid] = (ok, msg)
                    if not ok:
                        result.success = False
                        result.errors.append(f"{module.display_name}: {msg}")
                except Exception as e:
                    result.module_results[mid] = (False, str(e))
                    result.success = False
                    result.errors.append(f"{mid}: {e}")
            return result

        self._run_worker(do_partial_backup, on_done=self._on_backup_done)

    def _on_backup_done(self, result: OperationResult):
        self._set_busy(False)
        if result.success:
            self._log(f"✅ Backup complete — {result.summary}")
            self.status_bar.showMessage("Backup complete")
        else:
            self._log_errors(result)
            self.status_bar.showMessage("Backup had errors — check log")

    # ------------------------------------------------------------------
    # Load profile action
    # ------------------------------------------------------------------

    def _on_load_profile(self):
        if not self._current_profile:
            return
        profile = self._current_profile

        if not profile.enabled_modules():
            QMessageBox.information(self, "No Modules", "This profile has no modules enabled. Edit it first.")
            return

        # Conflict check
        conflicts = self.switcher.check_conflicts(profile)
        if conflicts:
            forced = self._show_conflict_dialog(conflicts, profile)
            if not forced:
                return

        if self.settings.get("confirm_before_restore", True):
            auto_note = " The current state will be auto-backed up first." if self.settings.get("auto_backup_before_restore", True) else ""
            reply = QMessageBox.question(
                self, "Load Profile",
                f"Load profile '{profile.name}'?{auto_note}\n\n"
                f"Modules: {', '.join(profile.enabled_modules())}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self._set_busy(True)
        self._log(f"▶ Loading profile '{profile.name}'...")

        auto_backup = self.settings.get("auto_backup_before_restore", True)

        def do_load(progress):
            return self.switcher.load_profile(profile, auto_backup_first=auto_backup, progress=progress)

        self._run_worker(do_load, on_done=self._on_load_done)

    def _show_conflict_dialog(self, conflicts: list[ModuleConflict], profile: Profile) -> bool:
        """Returns True if user chose to proceed (either conflicts cleared or forced)."""
        def recheck():
            return self.switcher.check_conflicts(profile)

        dlg = ConflictDialog(self, conflicts=conflicts, recheck_fn=recheck)
        dlg.exec()
        return dlg.result() in (1, 2)  # QDialog.Accepted or forced

    def _on_load_done(self, result: OperationResult):
        self._set_busy(False)
        self._update_undo_btn()
        if result.success:
            self._log(f"✅ Profile loaded — {result.summary}")
            if result.warnings:
                for w in result.warnings:
                    self._log(f"⚠ {w}")
            self.status_bar.showMessage(f"Profile '{self._current_profile.name}' loaded")
            self._refresh_status_indicators()
        else:
            self._log_errors(result)
            self.status_bar.showMessage("Load had errors — check log")

    # ------------------------------------------------------------------
    # Undo last switch
    # ------------------------------------------------------------------

    def _on_undo_last(self):
        auto_backup = self.pm.get_auto_backup()
        if not auto_backup:
            QMessageBox.information(self, "No Backup", "No auto-backup found.")
            return

        reply = QMessageBox.question(
            self, "Undo Last Switch",
            "Restore the state that was auto-backed up before the last profile load?\n"
            "This will overwrite the current live config.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._set_busy(True)
        self._log("↩ Undoing last switch...")

        def do_undo(progress):
            return self.switcher.load_profile(auto_backup, auto_backup_first=False, progress=progress)

        self._run_worker(do_undo, on_done=lambda r: (self._set_busy(False), self._log("✅ Undo complete" if r.success else f"⚠ Undo had errors")))

    def _update_undo_btn(self):
        has_backup = self.pm.auto_backup_dir().exists()
        self.undo_btn.setEnabled(has_backup)

    # ------------------------------------------------------------------
    # Worker / progress
    # ------------------------------------------------------------------

    def _run_worker(self, fn, on_done):
        self._worker = WorkerThread(fn, parent=self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(on_done)
        self._worker.finished.connect(lambda _: setattr(self, '_worker', None))
        self._worker.start()

    def _on_progress(self, module_id: str, step: str, message: str):
        self._log(f"  [{module_id}] {message}")
        self.status_bar.showMessage(message)

    def _set_busy(self, busy: bool):
        self.progress_bar.setVisible(busy)
        has_profile = not busy and bool(self._current_profile)
        self.backup_btn.setEnabled(has_profile)
        self.partial_backup_btn.setEnabled(has_profile)
        self.load_btn.setEnabled(has_profile)
        self.undo_btn.setEnabled(not busy and self.pm.auto_backup_dir().exists())

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _log(self, message: str):
        self.log_text.append(message)
        logger.info(message.strip())

    def _log_errors(self, result: OperationResult):
        for err in result.errors:
            self._log(f"❌ {err}")
        for mod_id, (ok, msg) in result.module_results.items():
            if not ok:
                self._log(f"   {mod_id}: {msg}")

    # ------------------------------------------------------------------
    # Window lifecycle
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        geom = self.saveGeometry().toHex().data().decode()
        self.settings.set("window_geometry", geom)
        super().closeEvent(event)
