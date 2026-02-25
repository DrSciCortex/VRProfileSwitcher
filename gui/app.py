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
    QCheckBox, QSizePolicy, QDialog, QDialogButtonBox, QFileDialog, QGridLayout,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QSize
from PyQt6.QtGui import QFont, QColor, QPalette, QAction, QIcon

from core.profile_manager import Profile, ProfileManager
from core.settings import AppSettings
from core.switcher import Switcher, ModuleConflict, StackConflict, OperationResult
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
QToolTip {
    background-color: #1e1e3a;
    color: #d4d4e8;
    border: 1px solid #4040a0;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 12px;
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


class _SeparatorItem(QListWidgetItem):
    """Non-selectable, non-draggable divider between active and inactive profiles."""
    def __init__(self, text: str = "─── other profiles ───"):
        super().__init__(text)
        self.setFlags(Qt.ItemFlag.NoItemFlags)
        self.setForeground(QColor("#404060"))
        font = QFont("Segoe UI", 9)
        font.setItalic(True)
        self.setFont(font)
        self.setSizeHint(QSize(0, 28))


class _ProfileListWidget(QListWidget):
    """
    Active profiles pinned to top in priority order (#1 at top = highest priority).
    Separator divides active from inactive. Drag-to-reorder within active section only.
    """
    def __init__(self, on_reorder, parent=None):
        super().__init__(parent)
        self._on_reorder = on_reorder
        self.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QListWidget.SelectionMode.SingleSelection)

    def _separator_row(self) -> int:
        for i in range(self.count()):
            if isinstance(self.item(i), _SeparatorItem):
                return i
        return -1

    def dropEvent(self, event):
        target_row = self.indexAt(event.position().toPoint()).row()
        sep = self._separator_row()
        source_row = self.currentRow()
        source_item = self.item(source_row)
        is_active = (
            isinstance(source_item, ProfileListItem)
            and source_item.stack_priority is not None
        )
        # Only active profiles can be dragged, and only within the active section
        if not is_active or (sep >= 0 and target_row >= sep):
            event.ignore()
            return
        before = self._active_order()
        super().dropEvent(event)
        after = self._active_order()
        if before != after:
            self._on_reorder(after)

    def _active_order(self) -> list[str]:
        """Active profile names in visual order (index 0 = top = highest priority)."""
        names = []
        for i in range(self.count()):
            item = self.item(i)
            if isinstance(item, ProfileListItem) and item.stack_priority is not None:
                names.append(item.profile.name)
        return names


class ProfileListItem(QListWidgetItem):
    def __init__(self, profile: Profile, stack_priority: int | None = None):
        super().__init__()
        self.profile = profile
        self.stack_priority = stack_priority  # None = not active; 1 = highest, 2 = next, etc.
        self._refresh()

    def _refresh(self):
        enabled = self.profile.enabled_modules()
        icons = []
        for mid in enabled:
            cls = MODULE_REGISTRY.get(mid)
            if cls:
                icons.append(cls.icon)
        icon_str = " ".join(icons) if icons else "○"

        if self.stack_priority is not None:
            badge = f"  🟢 #{self.stack_priority} ACTIVE"
            self.setText(f"  {self.profile.name}{badge}\n  {icon_str}")
            self.setForeground(QColor("#80ffb0"))
        else:
            self.setText(f"  {self.profile.name}\n  {icon_str}")
            self.setForeground(QColor("#d4d4e8"))
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
        # Active stack: ordered list of Profile objects (index 0 = lowest priority)
        self._active_stack: list[Profile] = []

        self.setWindowTitle("VRProfile Switcher")
        self.setMinimumSize(820, 560)
        self.setStyleSheet(DARK_STYLESHEET)

        self._build_ui()
        self._load_active_stack()
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

        # Profile list — drag-to-reorder active stack priority
        self.profile_list = _ProfileListWidget(on_reorder=self._on_stack_reorder)
        self.profile_list.setFont(QFont("Segoe UI", 10))
        self.profile_list.currentItemChanged.connect(self._on_profile_selected)
        self.profile_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.profile_list.customContextMenuRequested.connect(self._show_profile_context_menu)
        layout.addWidget(self.profile_list)

        # Sidebar action buttons
        btn_area = QWidget()
        btn_area.setStyleSheet("background: #0d0d18; border-top: 1px solid #1a1a28;")
        btn_layout = QGridLayout(btn_area)
        btn_layout.setContentsMargins(6, 6, 6, 6)
        btn_layout.setSpacing(4)

        new_btn = QPushButton("＋ New")
        new_btn.clicked.connect(self._on_new_profile)
        new_btn.setToolTip("Create a new profile and snapshot current settings")
        new_btn.setFixedHeight(30)
        new_btn.setStyleSheet("font-size: 11px; padding: 4px 6px;")
        btn_layout.addWidget(new_btn, 0, 0)

        restore_del_btn = QPushButton("↩ Recover")
        restore_del_btn.clicked.connect(self._on_restore_deleted)
        restore_del_btn.setToolTip("Restore a recently deleted profile (last 5 kept)")
        restore_del_btn.setFixedHeight(30)
        restore_del_btn.setStyleSheet("font-size: 11px; padding: 4px 6px;")
        btn_layout.addWidget(restore_del_btn, 0, 1)

        self.dup_btn = QPushButton("⧉ Duplicate")
        self.dup_btn.clicked.connect(self._on_duplicate_profile)
        self.dup_btn.setEnabled(False)
        self.dup_btn.setToolTip("Duplicate this profile including all saved module data")
        self.dup_btn.setFixedHeight(30)
        self.dup_btn.setStyleSheet("font-size: 11px; padding: 4px 6px;")
        btn_layout.addWidget(self.dup_btn, 1, 0)

        self.del_btn = QPushButton("🗑 Delete")
        self.del_btn.setObjectName("danger")
        self.del_btn.clicked.connect(self._on_delete_profile)
        self.del_btn.setEnabled(False)
        self.del_btn.setToolTip("Move this profile to the recoverable deleted history")
        self.del_btn.setFixedHeight(30)
        self.del_btn.setStyleSheet("font-size: 11px; padding: 4px 6px; background-color: #501818; color: #ffa0a0; border-color: #803030;")
        btn_layout.addWidget(self.del_btn, 1, 1)

        import_btn = QPushButton("📂 Import from…")
        import_btn.clicked.connect(self._on_import_profiles)
        import_btn.setToolTip("Import profiles from another VRProfileSwitcher data directory\n(e.g. a network share or backup folder)")
        import_btn.setFixedHeight(30)
        import_btn.setStyleSheet("font-size: 11px; padding: 4px 6px;")
        btn_layout.addWidget(import_btn, 2, 0, 1, 2)  # full width, spans both columns

        btn_layout.setColumnStretch(0, 1)
        btn_layout.setColumnStretch(1, 1)

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

        self.load_btn = QPushButton("▶  Load / Add to Stack")
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

        # Active profiles: top of list in priority order (#1 at top = highest priority)
        # Internal stack is low→high, so reversed() gives highest first
        active_in_order = list(reversed(self._active_stack))  # [highest, ..., lowest]
        active_names = {p.name for p in self._active_stack}

        priority_map: dict[str, int] = {}
        for i, p in enumerate(active_in_order):
            priority_map[p.name] = i + 1  # 1 = highest

        # Add active profiles first (in priority order)
        for p in active_in_order:
            item = ProfileListItem(p, stack_priority=priority_map[p.name])
            self.profile_list.addItem(item)

        # Separator (only if there are both active and inactive profiles)
        all_profiles = self.pm.list_profiles()
        inactive = [p for p in all_profiles if p.name not in active_names]
        if active_in_order and inactive:
            self.profile_list.addItem(_SeparatorItem())

        # Inactive profiles below separator, sorted by last_used as before
        for p in inactive:
            item = ProfileListItem(p, stack_priority=None)
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
        self._update_stack_status_bar()

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

        # Load / Unload button state
        in_stack = any(p.name == profile.name for p in self._active_stack)
        if in_stack:
            self.load_btn.setText("⏏  Unload from Stack")
            self.load_btn.setObjectName("danger")
        else:
            self.load_btn.setText("▶  Load / Add to Stack")
            self.load_btn.setObjectName("success")
        self.load_btn.setEnabled(True)
        # Force style refresh
        self.load_btn.style().unpolish(self.load_btn)
        self.load_btn.style().polish(self.load_btn)

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
        self.load_btn.setText("▶  Load / Add to Stack")
        self.load_btn.setObjectName("success")
        self.load_btn.style().unpolish(self.load_btn)
        self.load_btn.style().polish(self.load_btn)
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

    def _on_import_profiles(self):
        """Let the user pick a foreign VRProfileSwitcher data dir and import profiles from it."""
        src_dir = QFileDialog.getExistingDirectory(
            self,
            "Select VRProfileSwitcher data directory to import from",
            "",
            QFileDialog.Option.ShowDirsOnly,
        )
        if not src_dir:
            return

        src_path = Path(src_dir)
        # Accept either the data/ dir itself or its profiles/ subdirectory
        profiles_path = src_path / "profiles" if (src_path / "profiles").exists() else src_path

        # Scan for valid profiles (dirs containing profile.json)
        candidates = [
            d for d in profiles_path.iterdir()
            if d.is_dir()
            and not d.name.startswith("__")
            and (d / "profile.json").exists()
        ]

        if not candidates:
            QMessageBox.warning(
                self, "No Profiles Found",
                f"No valid profiles found in:\n{profiles_path}\n\n"
                "Make sure you selected the 'data' or 'data/profiles' folder "
                "of a VRProfileSwitcher installation."
            )
            return

        # Show a checklist dialog for the user to pick which to import
        dlg = QDialog(self)
        dlg.setWindowTitle("Import Profiles")
        dlg.setModal(True)
        dlg.setMinimumWidth(420)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        existing_names = {p.name for p in self.pm.list_profiles()}

        header = QLabel(f"Found {len(candidates)} profile(s) in:\n{profiles_path}")
        header.setWordWrap(True)
        header.setStyleSheet("color: #a0a0c0; font-size: 12px;")
        layout.addWidget(header)

        layout.addWidget(QLabel("Select profiles to import:"))

        checkboxes: dict[str, tuple[QCheckBox, Path]] = {}
        for d in sorted(candidates, key=lambda x: x.name):
            clash = d.name in existing_names
            label = d.name + (" (will be renamed — name already exists)" if clash else "")
            cb = QCheckBox(label)
            cb.setChecked(True)
            cb.setFont(QFont("Segoe UI", 10))
            if clash:
                cb.setStyleSheet("color: #c0a040;")
            layout.addWidget(cb)
            checkboxes[d.name] = (cb, d)

        sel_row = QHBoxLayout()
        all_btn = QPushButton("Select All")
        all_btn.setFixedWidth(90)
        all_btn.clicked.connect(lambda: [v[0].setChecked(True) for v in checkboxes.values()])
        none_btn = QPushButton("Select None")
        none_btn.setFixedWidth(90)
        none_btn.clicked.connect(lambda: [v[0].setChecked(False) for v in checkboxes.values()])
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
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("📂  Import Selected")
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        if not dlg.exec():
            return

        selected = [(name, path) for name, (cb, path) in checkboxes.items() if cb.isChecked()]
        if not selected:
            return

        imported, skipped, errors = [], [], []
        for name, src in selected:
            try:
                final_name = self.pm.import_profile(src)
                imported.append(final_name)
            except Exception as e:
                errors.append(f"{name}: {e}")

        self._refresh_profile_list()

        summary_parts = []
        if imported:
            summary_parts.append(f"Imported: {', '.join(imported)}")
        if errors:
            summary_parts.append(f"Errors: {'; '.join(errors)}")

        self._log(f"📂 Import complete — " + " | ".join(summary_parts))
        self.status_bar.showMessage(f"Imported {len(imported)} profile(s)")

        if errors:
            QMessageBox.warning(self, "Import Errors",
                "Some profiles could not be imported:\n" + "\n".join(errors))

    def _on_restore_deleted(self):
        deleted = self.pm.list_deleted_profiles()
        if not deleted:
            QMessageBox.information(
                self, "Restore Deleted",
                "No deleted profiles in history.\n\n"
                "Deleted profiles are kept until the 5-profile limit is exceeded."
            )
            return

        # Build a dialog listing deleted profiles to pick from
        dlg = QDialog(self)
        dlg.setWindowTitle("Restore Deleted Profile")
        dlg.setModal(True)
        dlg.setMinimumWidth(380)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        layout.addWidget(QLabel("Select a deleted profile to restore:"))

        from PyQt6.QtWidgets import QListWidget
        lst = QListWidget()
        for display_name, path in deleted:
            # Show the timestamp prefix in a friendly way
            parts = path.name.split("_", 2)
            if len(parts) == 3:
                try:
                    from datetime import datetime as dt
                    ts = dt.strptime(f"{parts[0]}_{parts[1]}", "%Y%m%d_%H%M%S")
                    friendly = ts.strftime("%d %b %Y %H:%M")
                except Exception:
                    friendly = parts[0]
            else:
                friendly = ""
            lst.addItem(f"{display_name}  ({friendly})")
        lst.setCurrentRow(0)
        layout.addWidget(lst)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("↩  Restore")
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        if not dlg.exec():
            return

        idx = lst.currentRow()
        if idx < 0:
            return

        display_name, deleted_path = deleted[idx]
        try:
            restored = self.pm.restore_deleted_profile(deleted_path)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to restore: {e}")
            return

        self._refresh_profile_list()
        # Select the restored profile
        for i in range(self.profile_list.count()):
            item = self.profile_list.item(i)
            if isinstance(item, ProfileListItem) and item.profile.name == restored.name:
                self.profile_list.setCurrentItem(item)
                break
        self._log(f"✅ Restored deleted profile '{restored.name}'")
        self.status_bar.showMessage(f"Profile '{restored.name}' restored")

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
            f"Delete profile '{name}'?\n\n"
            f"It will be kept in a rolling history (last 5 deleted profiles) "
            f"and can be recovered via ↩ Restore Deleted…",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply == QMessageBox.StandardButton.Yes:
            # Unload from stack first so module state is properly reverted
            # (e.g. Resonite launch args handed to next stack entry or cleared)
            was_active = any(p.name == name for p in self._active_stack)
            if was_active:
                profile_obj = self._current_profile
                remaining = [p for p in self._active_stack if p.name != name]
                self.settings.stack_remove(name)
                self._active_stack = remaining[:]
                def _do_cleanup(progress):
                    return self.switcher.unload_from_stack(
                        profile=profile_obj,
                        remaining_stack=remaining,
                        progress=progress,
                    )
                def _on_cleanup_done(result):
                    self._set_busy(False)
                    for w in result.warnings:
                        self._log(f"⚠ {w}")
                    if result.errors:
                        self._log_errors(result)
                self._set_busy(True)
                self._log(f"⏏ Unloading '{name}' from stack before delete...")
                self._run_worker(_do_cleanup, on_done=_on_cleanup_done)

            self.pm.delete_profile(name)
            self._set_no_profile()
            self._refresh_profile_list()
            self._log(f"🗑 Deleted profile '{name}' (recoverable via Restore Deleted…)")
            self.status_bar.showMessage(f"Profile '{name}' deleted — recoverable")

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

        profile = self._choose_save_target(self._current_profile, "all")
        if profile is None:
            return

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

        profile = self._choose_save_target(self._current_profile, "selected")
        if profile is None:
            return

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

    def _choose_save_target(self, selected_profile: Profile, mode: str) -> Profile | None:
        """
        When multiple profiles are active in the stack, ask the user which one
        to save current live config into. Returns the chosen Profile, or None to cancel.
        If only one profile is active (or none), returns `selected_profile` directly.
        """
        active_names = {p.name for p in self._active_stack}
        if len(self._active_stack) <= 1:
            return selected_profile

        # If the currently selected profile is in the stack, suggest it as default
        if selected_profile.name in active_names:
            default = selected_profile
        else:
            default = self._active_stack[-1]  # highest priority

        # Build choice list: active stack members (high→low), plus currently selected if not in stack
        candidates = list(reversed(self._active_stack))
        if selected_profile.name not in active_names:
            candidates.insert(0, selected_profile)

        items = [
            f"{p.name}  [{', '.join(p.enabled_modules()) or 'no modules'}]"
            for p in candidates
        ]
        default_idx = next((i for i, p in enumerate(candidates) if p.name == default.name), 0)

        from PyQt6.QtWidgets import QInputDialog
        item, ok = QInputDialog.getItem(
            self, "Save Into Which Profile?",
            f"Multiple profiles are active. Choose which profile to save {'modules' if mode == 'all' else 'selected modules'} into:",
            items,
            default_idx,
            editable=False,
        )
        if not ok:
            return None
        chosen_idx = items.index(item)
        return candidates[chosen_idx]

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

        # Toggle: if already in stack, unload it
        if any(p.name == profile.name for p in self._active_stack):
            self._do_unload_profile(profile)
            return

        self._do_load_profile(profile)

    def _do_load_profile(self, profile: Profile):
        """Add `profile` to the active stack (or replace if it overlaps)."""
        if not profile.enabled_modules():
            QMessageBox.information(self, "No Modules", "This profile has no modules enabled. Edit it first.")
            return

        # Check for module overlaps with current stack
        stack_conflicts = self.switcher.check_stack_conflicts(profile, self._active_stack)
        if stack_conflicts:
            conflicting_profiles = sorted({sc.active_profile for sc in stack_conflicts})
            conflict_lines = "\n".join(
                f"  • {sc.display_name}  (currently owned by '{sc.active_profile}')"
                for sc in stack_conflicts
            )
            reply = QMessageBox.question(
                self, "Module Overlap",
                f"'{profile.name}' shares modules with profiles already in the stack:\n\n"
                f"{conflict_lines}\n\n"
                f"'{profile.name}' will take priority and override those modules.\n"
                f"The overlapping profiles stay in the stack at lower priority.\n\n"
                f"Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        # Check for running-app conflicts
        app_conflicts = self.switcher.check_conflicts(profile)
        if app_conflicts:
            forced = self._show_conflict_dialog(app_conflicts, profile)
            if not forced:
                return

        if self.settings.get("confirm_before_restore", True):
            auto_note = " The current state will be auto-backed up first." if self.settings.get("auto_backup_before_restore", True) else ""
            stack_desc = ""
            if self._active_stack:
                names = ", ".join(p.name for p in reversed(self._active_stack))
                stack_desc = f"\n\nCurrently active: {names}"
            reply = QMessageBox.question(
                self, "Add to Stack",
                f"Load '{profile.name}' (modules: {', '.join(profile.enabled_modules())})?{auto_note}{stack_desc}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self._set_busy(True)
        self._log(f"▶ Loading '{profile.name}' into stack...")

        current_stack = list(self._active_stack)
        auto_backup = self.settings.get("auto_backup_before_restore", True)

        def do_load(progress):
            return self.switcher.load_into_stack(
                incoming=profile,
                current_stack=current_stack,
                auto_backup_first=auto_backup,
                progress=progress,
            )

        def on_done(result: OperationResult):
            self._set_busy(False)
            self._update_undo_btn()
            if result.success:
                # Commit stack change
                self.settings.stack_push(profile.name)
                self._load_active_stack()
                self._refresh_profile_list()
                self._force_show_profile(profile.name)
                self._log(f"✅ '{profile.name}' added to stack — {result.summary}")
                for w in result.warnings:
                    self._log(f"⚠ {w}")
                self.status_bar.showMessage(f"Stack: {self._stack_summary()}")
                self._refresh_status_indicators()
            else:
                self._log_errors(result)
                self.status_bar.showMessage("Load had errors — check log")

        self._run_worker(do_load, on_done=on_done)

    def _do_unload_profile(self, profile: Profile):
        """Remove `profile` from the active stack, falling back to lower-priority profiles."""
        reply = QMessageBox.question(
            self, "Unload Profile",
            f"Unload '{profile.name}' from the active stack?\n\n"
            f"Modules it owns will revert to the next lower profile in the stack,\n"
            f"or to defaults if nothing else covers them.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Build remaining stack (without this profile)
        remaining = [p for p in self._active_stack if p.name != profile.name]

        self._set_busy(True)
        self._log(f"⏏ Unloading '{profile.name}' from stack...")

        def do_unload(progress):
            return self.switcher.unload_from_stack(
                profile=profile,
                remaining_stack=remaining,
                progress=progress,
            )

        def on_done(result: OperationResult):
            self._set_busy(False)
            # Commit stack change regardless of partial errors
            self.settings.stack_remove(profile.name)
            self._load_active_stack()
            self._refresh_profile_list()
            if self._current_profile:
                self._force_show_profile(self._current_profile.name)
            if result.success or not result.errors:
                self._log(f"✅ '{profile.name}' unloaded — {result.summary}")
            else:
                self._log_errors(result)
            for w in result.warnings:
                self._log(f"⚠ {w}")
            self.status_bar.showMessage(f"Stack: {self._stack_summary()}")
            self._refresh_status_indicators()

        self._run_worker(do_unload, on_done=on_done)

    def _show_conflict_dialog(self, conflicts: list[ModuleConflict], profile: Profile) -> bool:
        """Returns True if user chose to proceed (either conflicts cleared or forced)."""
        def recheck():
            return self.switcher.check_conflicts(profile)

        dlg = ConflictDialog(self, conflicts=conflicts, recheck_fn=recheck)
        dlg.exec()
        return dlg.result() in (1, 2)  # QDialog.Accepted or forced

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
    # Active stack helpers
    # ------------------------------------------------------------------

    def _on_stack_reorder(self, new_active_order: list[str]):
        """
        Called by _ProfileListWidget when the user drags active profiles into a new order.
        new_active_order is the names of active profiles in new visual order (top = shown first,
        but we need to decide convention). We treat visual top = lowest priority so that
        dragging a profile UP means it now loads LATER (higher priority).
        Actually: visual top-to-bottom = high-to-low priority makes more intuitive sense
        (profile at top "wins"). So: new_active_order[0] = highest priority = last in stack.
        """
        if not new_active_order:
            return

        # new_active_order: top of list = index 0 = highest priority shown first
        # internal stack: last = highest priority
        # So reverse: stack order = reversed(new_active_order)
        new_stack_order = list(reversed(new_active_order))  # [lowest, ..., highest]

        old_stack_order = [p.name for p in self._active_stack]
        if new_stack_order == old_stack_order:
            return

        # Check if Resonite module is involved — requires Steam to be closed
        resonite_profiles = [
            name for name in new_stack_order
            if (p := self.pm.get_profile(name)) and p.is_module_enabled("resonite")
        ]
        if resonite_profiles:
            # Check Steam running
            try:
                from modules.resonite import _steam_is_running
                if _steam_is_running():
                    from PyQt6.QtWidgets import QMessageBox
                    QMessageBox.warning(
                        self, "Steam is Running",
                        "Reordering Resonite profiles requires updating Steam launch options.\n\n"
                        "Please close Steam first, then drag to reorder.",
                    )
                    self._refresh_profile_list()  # revert visual order
                    return
            except Exception as e:
                logger.warning(f"Steam check failed: {e}")

        # Commit new order to settings
        # Keep non-active profiles out of stack list — only active ones get reordered
        self.settings.set("active_stack", new_stack_order)
        self._load_active_stack()

        # If Resonite is in the stack, re-apply the winning profile's launch args
        if resonite_profiles:
            resolution = self.switcher.resolve_stack(self._active_stack)
            winning = resolution.get("resonite")
            if winning:
                self._set_busy(True)
                self._log(f"🔄 Reordered stack — re-applying Resonite args from '{winning.name}'...")
                src_dir = self.pm.profile_dir(winning.name)

                def do_reapply(progress):
                    from core.switcher import OperationResult
                    result = OperationResult(success=True)
                    try:
                        from modules import get_module
                        mod = get_module("resonite", winning.get_module_options("resonite"))
                        ok, msg = mod.restore(src_dir)
                        result.module_results["resonite"] = (ok, msg)
                        if not ok:
                            result.success = False
                            result.errors.append(f"Resonite: {msg}")
                    except Exception as e:
                        result.success = False
                        result.errors.append(str(e))
                    return result

                def on_done(result):
                    self._set_busy(False)
                    if result.success:
                        self._log(f"✅ Resonite launch args updated to '{winning.name}'")
                    else:
                        self._log_errors(result)
                    self._refresh_profile_list()
                    if self._current_profile:
                        self._force_show_profile(self._current_profile.name)

                self._run_worker(do_reapply, on_done=on_done)
                return

        self._refresh_profile_list()
        if self._current_profile:
            self._force_show_profile(self._current_profile.name)
        self.status_bar.showMessage(f"Stack reordered — {self._stack_summary()}")

    def _force_show_profile(self, name: str):
        """Re-load profile from disk and show it, ensuring fresh stack state is reflected."""
        p = self.pm.get_profile(name)
        if p:
            self._current_profile = p
            self._show_profile(p)

    def _load_active_stack(self):
        """Re-build _active_stack from settings, dropping any profiles that no longer exist."""
        names = self.settings.active_stack
        stack = []
        cleaned = False
        for name in names:
            p = self.pm.get_profile(name)
            if p:
                stack.append(p)
            else:
                cleaned = True
                logger.warning(f"Active stack: profile '{name}' no longer exists — removing")
        self._active_stack = stack
        if cleaned:
            self.settings.set("active_stack", [p.name for p in stack])

    def _stack_summary(self) -> str:
        if not self._active_stack:
            return "No profiles active"
        # High→low
        names = [p.name for p in reversed(self._active_stack)]
        return "Active: " + " › ".join(names)

    def _update_stack_status_bar(self):
        self.status_bar.showMessage(self._stack_summary())

    # ------------------------------------------------------------------
    # Window lifecycle
    # ------------------------------------------------------------------

    def closeEvent(self, event):
        geom = self.saveGeometry().toHex().data().decode()
        self.settings.set("window_geometry", geom)
        super().closeEvent(event)
