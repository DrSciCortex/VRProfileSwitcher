"""
Profile Editor Dialog
Shown when creating a new profile or clicking "Edit" on an existing one.
Allows setting name, notes, and toggling which modules are active.
For SteamVR, shows driver selection dropdown.
"""

from __future__ import annotations
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QTextEdit, QCheckBox, QComboBox,
    QDialogButtonBox, QLabel, QGroupBox, QScrollArea,
    QWidget, QFrame,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont

from core.profile_manager import Profile
from modules import MODULE_REGISTRY, get_module


STEAMVR_DRIVERS = [
    ("(none / default)", None),
    ("cyberfinger", "cyberfinger"),
    ("handtracking", "handtracking"),
    ("leapmotion", "leapmotion"),
    ("ultraleap", "ultraleap"),
]


class ProfileEditorDialog(QDialog):
    """
    Modal dialog to create or edit a profile's metadata and module config.
    On accept, the updated Profile object is available via .profile
    """

    def __init__(self, parent=None, profile: Profile | None = None, existing_names: list[str] | None = None):
        super().__init__(parent)
        self.is_new = profile is None
        self.existing_names = [n.lower() for n in (existing_names or [])]
        if self.is_new:
            from core.profile_manager import Profile as P
            self.profile = P(name="")
        else:
            import copy
            self.profile = copy.deepcopy(profile)

        self.setWindowTitle("New Profile" if self.is_new else f"Edit — {self.profile.name}")
        self.setMinimumWidth(480)
        self.setModal(True)
        self._build_ui()
        self._populate()

    # ------------------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)

        # --- Identity ---
        form = QFormLayout()
        form.setSpacing(8)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. Alice, BobVR, Gaming Rig...")
        self.name_edit.setMaxLength(64)
        form.addRow("Profile name:", self.name_edit)

        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText("Optional notes about this profile...")
        self.notes_edit.setMaximumHeight(70)
        form.addRow("Notes:", self.notes_edit)

        layout.addLayout(form)

        # --- Modules ---
        modules_group = QGroupBox("Active Modules")
        modules_layout = QVBoxLayout(modules_group)
        modules_layout.setSpacing(10)

        self._module_widgets: dict[str, dict] = {}

        for mid, cls in MODULE_REGISTRY.items():
            module = cls()
            row = self._build_module_row(mid, module)
            modules_layout.addWidget(row)

        layout.addWidget(modules_group)

        # --- Validation label ---
        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #e05c5c; font-size: 12px;")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)

        # --- Buttons ---
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _build_module_row(self, mid: str, module) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Header row: checkbox + icon + name
        header = QHBoxLayout()
        cb = QCheckBox(f"{module.icon}  {module.display_name}")
        cb.setFont(QFont("Segoe UI", 10, QFont.Weight.Medium))
        header.addWidget(cb)
        header.addStretch()

        # Description
        desc = QLabel(module.description)
        desc.setStyleSheet("color: #888; font-size: 11px; padding-left: 22px;")
        desc.setWordWrap(True)

        layout.addLayout(header)
        layout.addWidget(desc)

        widgets = {"checkbox": cb, "extra": {}}

        # Module-specific options
        if mid == "steamvr":
            opt_row = QHBoxLayout()
            opt_row.setContentsMargins(22, 0, 0, 0)
            opt_row.addWidget(QLabel("Active driver:"))
            driver_combo = QComboBox()
            for label, val in STEAMVR_DRIVERS:
                driver_combo.addItem(label, val)
            opt_row.addWidget(driver_combo)
            opt_row.addStretch()
            opt_widget = QWidget()
            opt_widget.setLayout(opt_row)
            layout.addWidget(opt_widget)
            widgets["extra"]["driver_combo"] = driver_combo

            def _toggle_driver(state, ow=opt_widget):
                ow.setEnabled(bool(state))
            cb.stateChanged.connect(_toggle_driver)

        elif mid == "resolute":
            opt_row = QHBoxLayout()
            opt_row.setContentsMargins(22, 0, 0, 0)
            save_dlls_cb = QCheckBox("Include mod DLL files (rml_mods/ & rml_libs/)")
            save_dlls_cb.setToolTip(
                "When enabled, the actual .dll files are saved with the profile so switching "
                "profiles truly changes which mods are active. Profiles may be 10-100 MB larger."
            )
            opt_row.addWidget(save_dlls_cb)
            opt_row.addStretch()
            opt_widget = QWidget()
            opt_widget.setLayout(opt_row)
            layout.addWidget(opt_widget)
            widgets["extra"]["save_dlls_cb"] = save_dlls_cb

            def _toggle_resolute(state, ow=opt_widget):
                ow.setEnabled(bool(state))
            cb.stateChanged.connect(_toggle_resolute)

        elif mid in ("eyetrackvr", "babble"):
            opt_row = QHBoxLayout()
            opt_row.setContentsMargins(22, 0, 0, 0)
            vrcft_cb = QCheckBox("Include VRCFT module config")
            vrcft_cb.setToolTip(
                "Also save/restore the VRCFaceTracking module config for this app "
                "(ETVRModuleConfig.json / VRCFaceTracking.Babble.json)"
            )
            opt_row.addWidget(vrcft_cb)
            opt_row.addStretch()
            opt_widget = QWidget()
            opt_widget.setLayout(opt_row)
            layout.addWidget(opt_widget)
            widgets["extra"]["vrcft_cb"] = vrcft_cb

            def _toggle_vrcft(state, ow=opt_widget):
                ow.setEnabled(bool(state))
            cb.stateChanged.connect(_toggle_vrcft)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #333;")
        layout.addWidget(sep)

        self._module_widgets[mid] = widgets
        return container

    # ------------------------------------------------------------------
    def _populate(self):
        self.name_edit.setText(self.profile.name)
        self.notes_edit.setPlainText(self.profile.notes)

        for mid, widgets in self._module_widgets.items():
            cb: QCheckBox = widgets["checkbox"]
            cb.setChecked(self.profile.is_module_enabled(mid))
            opts = self.profile.get_module_options(mid)

            if "driver_combo" in widgets.get("extra", {}):
                combo: QComboBox = widgets["extra"]["driver_combo"]
                current_driver = opts.get("active_driver")
                for i in range(combo.count()):
                    if combo.itemData(i) == current_driver:
                        combo.setCurrentIndex(i)
                        break
                combo.setEnabled(self.profile.is_module_enabled(mid))

            if "save_dlls_cb" in widgets.get("extra", {}):
                dlls_cb: QCheckBox = widgets["extra"]["save_dlls_cb"]
                dlls_cb.setChecked(bool(opts.get("save_dlls", True)))
                dlls_cb.setEnabled(self.profile.is_module_enabled(mid))

            if "vrcft_cb" in widgets.get("extra", {}):
                vrcft_cb: QCheckBox = widgets["extra"]["vrcft_cb"]
                vrcft_cb.setChecked(bool(opts.get("include_vrcft_module", True)))
                vrcft_cb.setEnabled(self.profile.is_module_enabled(mid))

    def _on_accept(self):
        name = self.name_edit.text().strip()
        if not name:
            self.error_label.setText("⚠ Profile name is required.")
            return
        if self.is_new and name.lower() in self.existing_names:
            self.error_label.setText(f"⚠ A profile named '{name}' already exists.")
            return

        self.profile.name = name
        self.profile.notes = self.notes_edit.toPlainText().strip()

        for mid, widgets in self._module_widgets.items():
            cb: QCheckBox = widgets["checkbox"]
            self.profile.set_module_enabled(mid, cb.isChecked())
            if "driver_combo" in widgets.get("extra", {}):
                combo: QComboBox = widgets["extra"]["driver_combo"]
                self.profile.set_module_option(mid, "active_driver", combo.currentData())
            if "save_dlls_cb" in widgets.get("extra", {}):
                dlls_cb: QCheckBox = widgets["extra"]["save_dlls_cb"]
                self.profile.set_module_option(mid, "save_dlls", dlls_cb.isChecked())
            if "vrcft_cb" in widgets.get("extra", {}):
                vrcft_cb: QCheckBox = widgets["extra"]["vrcft_cb"]
                self.profile.set_module_option(mid, "include_vrcft_module", vrcft_cb.isChecked())

        self.accept()
