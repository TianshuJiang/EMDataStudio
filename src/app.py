"""
app.py
Main application window.
"""
import os
from datetime import datetime
import numpy as np
from PyQt5.QtWidgets import (
    QMainWindow, QSplitter, QAction, QFileDialog,
    QStatusBar, QApplication, QMessageBox, QLabel, QInputDialog,
    QDialog, QComboBox, QLineEdit, QCheckBox, QDialogButtonBox,
    QVBoxLayout, QFormLayout, QHBoxLayout,
    QPushButton, QSpinBox, QDoubleSpinBox, QListWidget, QListWidgetItem, QGroupBox,
    QWidget, QHBoxLayout as _QHB, QStyle,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QIcon

from .config import AppConfig
from .widgets.data_list_widget import DataListWidget
from .widgets.viewer_widget import ViewerWidget
from .widgets.settings_dialog import SettingsDialog
from .data_manager import (
    get_signal_title, load_hyperspy_file,
    export_eelspack, load_eelspack,
    classify_signal,
)


class _UndoStack:
    """Lightweight command-pattern undo/redo stack."""

    MAX_DEPTH = 50

    def __init__(self):
        self._stack = []   # list of (undo_fn, redo_fn, label)
        self._pos   = -1   # index of last executed command

    def push(self, undo_fn, redo_fn, label: str):
        del self._stack[self._pos + 1:]
        self._stack.append((undo_fn, redo_fn, label))
        if len(self._stack) > self.MAX_DEPTH:
            self._stack.pop(0)
        else:
            self._pos += 1

    def undo(self):
        if self._pos < 0:
            return None
        undo_fn, _, label = self._stack[self._pos]
        self._pos -= 1
        undo_fn()
        return label

    def redo(self):
        if self._pos >= len(self._stack) - 1:
            return None
        self._pos += 1
        _, redo_fn, label = self._stack[self._pos]
        redo_fn()
        return label

    def can_undo(self):
        return self._pos >= 0

    def can_redo(self):
        return self._pos < len(self._stack) - 1

    def undo_label(self):
        return self._stack[self._pos][2] if self.can_undo() else ""

    def redo_label(self):
        return self._stack[self._pos + 1][2] if self.can_redo() else ""

    def clear(self):
        self._stack.clear()
        self._pos = -1


class _MultiRoiPanel(QDialog):
    """Floating panel for managing multiple simultaneous 2D ROIs."""

    def __init__(self, parent, viewer):
        super().__init__(parent)
        self.viewer = viewer
        self.setWindowTitle("Multiple 2D ROIs")
        self.setMinimumWidth(340)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)

        root = QVBoxLayout(self)
        root.setSpacing(8)
        root.setContentsMargins(12, 12, 12, 10)

        # Size input
        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("ROI size (px):"))
        self._size_spin = QSpinBox()
        self._size_spin.setRange(1, 4096)
        self._size_spin.setValue(3)
        self._size_spin.setFixedWidth(80)
        size_row.addWidget(self._size_spin)
        size_row.addStretch()
        root.addLayout(size_row)

        # Add-ROI button
        self._btn_add = QPushButton("+ Add ROI")
        self._btn_add.setToolTip("Place a new ROI on all open image panels")
        self._btn_add.clicked.connect(self._add_roi)
        root.addWidget(self._btn_add)

        # ROI list
        grp = QGroupBox("Active ROIs")
        grp_layout = QVBoxLayout(grp)
        grp_layout.setContentsMargins(6, 6, 6, 6)
        grp_layout.setSpacing(4)
        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SingleSelection)
        grp_layout.addWidget(self._list)

        rm_row = QHBoxLayout()
        rm_row.addStretch()
        self._btn_remove = QPushButton("Remove selected")
        self._btn_remove.clicked.connect(self._remove_selected)
        rm_row.addWidget(self._btn_remove)
        self._btn_clear = QPushButton("Clear all")
        self._btn_clear.clicked.connect(self._clear_all)
        rm_row.addWidget(self._btn_clear)
        grp_layout.addLayout(rm_row)
        root.addWidget(grp)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        root.addWidget(close_btn)

        self._refresh_list()

    def _add_roi(self):
        size = self._size_spin.value()
        ok, result = self.viewer.add_multi_roi(initial_size_px=size)
        if not ok:
            QMessageBox.warning(self, "Add ROI", str(result))
            return
        self._refresh_list()
        try:
            self.parent().statusBar().showMessage(
                f"Added ROI #{result}  ({size}\u00d7{size} px)."
            )
        except Exception:
            pass

    def _remove_selected(self):
        item = self._list.currentItem()
        if item is None:
            return
        roi_index = item.data(Qt.UserRole)
        self.viewer.remove_multi_roi(roi_index)
        self._refresh_list()

    def _clear_all(self):
        self.viewer.clear_multi_rois()
        self._refresh_list()

    def _refresh_list(self):
        self._list.clear()
        colors = [
            "#ef476f", "#06d6a0", "#118ab2", "#ffd166", "#e040fb",
            "#ff9a3c", "#4fc3f7", "#a5d6a7", "#f48fb1", "#ce93d8",
        ]
        for entry in self.viewer.get_multi_roi_payload():
            idx = entry["index"]
            roi = entry["roi"]
            color = colors[(idx - 1) % len(colors)]
            lbl = (f"ROI #{idx}  "
                   f"({roi.left:.1f}, {roi.top:.1f}) → "
                   f"({roi.right:.1f}, {roi.bottom:.1f})")
            item = QListWidgetItem(lbl)
            item.setData(Qt.UserRole, idx)
            item.setForeground(Qt.white)
            item.setBackground(__import__("PyQt5.QtGui", fromlist=["QColor"]).QColor(color + "44"))
            self._list.addItem(item)
        n = self.viewer.get_multi_roi_count()
        self.setWindowTitle(f"Multiple 2D ROIs  ({n} active)")


class _RoiExportDialog(QDialog):
    """Dialog for configuring a 2D ROI export destination."""

    def __init__(self, parent, workspaces, preselected_ws_id=None):
        super().__init__(parent)
        self.setWindowTitle("Export 2D ROI Crops")
        self.setMinimumWidth(400)
        self._workspaces = workspaces
        self._new_ws_label = "— New workspace…"

        root = QVBoxLayout(self)
        root.setSpacing(12)
        root.setContentsMargins(16, 16, 16, 12)

        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)

        # Workspace selector
        self._ws_combo = QComboBox()
        for ws in workspaces:
            self._ws_combo.addItem(ws["name"], userData=ws["id"])
        self._ws_combo.addItem(self._new_ws_label, userData=None)
        # Pre-select
        if preselected_ws_id:
            for i in range(self._ws_combo.count()):
                if self._ws_combo.itemData(i) == preselected_ws_id:
                    self._ws_combo.setCurrentIndex(i)
                    break
        form.addRow("Destination workspace:", self._ws_combo)

        # Dataset name
        from datetime import datetime as _dt
        timestamp = _dt.now().strftime("%Y-%m-%d %H-%M-%S")
        self._name_edit = QLineEdit(f"ROI Crops {timestamp}")
        form.addRow("Dataset name:", self._name_edit)

        root.addLayout(form)

        # Skip-dialog checkbox
        self._skip_cb = QCheckBox("Remember this workspace and skip this dialog next time")
        root.addWidget(self._skip_cb)

        # Buttons
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    def _on_accept(self):
        # If "New workspace…" is chosen, prompt now and create it.
        if self._ws_combo.currentData() is None:
            name, ok = QInputDialog.getText(
                self, "New Workspace", "Workspace name:",
                text=f"Workspace {len(self._workspaces) + 1}",
            )
            if not ok:
                return
            ws_id = self.parent().data_list.add_workspace(name.strip() or f"Workspace {len(self._workspaces) + 1}")
            self._resolved_ws_id = ws_id
        else:
            self._resolved_ws_id = self._ws_combo.currentData()
        self.accept()

    def workspace_id(self):
        return getattr(self, "_resolved_ws_id", None)

    def dataset_name(self):
        return self._name_edit.text().strip() or self._name_edit.placeholderText()

    def skip_next_time(self):
        return self._skip_cb.isChecked()


class _AlignZlpDialog(QDialog):
    """Dialog to choose low-loss signal, optional core-loss target, and alignment options."""

    def __init__(self, parent, low_entries, core_entries):
        super().__init__(parent)
        self.setWindowTitle("Align Zero Loss Peak")
        self.setMinimumWidth(560)

        self._low_entries = list(low_entries)
        self._core_entries = list(core_entries)

        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(14, 14, 14, 10)

        hint = QLabel(
            "Choose a low-loss signal to align. Optionally align one core-loss "
            "signal together using also_align=[core_loss_signal]."
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

        # ── Signal selection ──────────────────────────────────────────────────
        sig_form = QFormLayout()
        sig_form.setHorizontalSpacing(10)
        sig_form.setVerticalSpacing(8)

        self._low_combo = QComboBox()
        for i, e in enumerate(self._low_entries):
            self._low_combo.addItem(e["label"], userData=i)
        sig_form.addRow("Low-loss signal:", self._low_combo)

        self._also_core_cb = QCheckBox("Also align one core-loss signal")
        self._also_core_cb.setChecked(bool(self._core_entries))
        self._also_core_cb.setEnabled(bool(self._core_entries))
        root.addLayout(sig_form)
        root.addWidget(self._also_core_cb)

        core_form = QFormLayout()
        core_form.setHorizontalSpacing(10)
        core_form.setVerticalSpacing(8)
        self._core_combo = QComboBox()
        self._core_combo.addItem("None", userData=None)
        for i, e in enumerate(self._core_entries):
            self._core_combo.addItem(e["label"], userData=i)
        self._core_combo.setEnabled(bool(self._core_entries) and self._also_core_cb.isChecked())
        core_form.addRow("Core-loss signal:", self._core_combo)
        root.addLayout(core_form)

        # ── Advanced options group ────────────────────────────────────────────
        adv_grp = QGroupBox("Advanced options")
        adv_grp.setCheckable(True)
        adv_grp.setChecked(False)   # collapsed by default
        adv_layout = QVBoxLayout(adv_grp)
        adv_layout.setSpacing(6)
        adv_layout.setContentsMargins(10, 6, 10, 8)

        adv_form = QFormLayout()
        adv_form.setHorizontalSpacing(10)
        adv_form.setVerticalSpacing(6)

        # signal_range  ── restrict ZLP search window
        range_row = QHBoxLayout()
        self._range_cb = QCheckBox("Restrict search to range:")
        self._range_cb.setChecked(False)
        range_row.addWidget(self._range_cb)
        range_row.addStretch()
        adv_layout.addLayout(range_row)

        range_spin_form = QFormLayout()
        range_spin_form.setHorizontalSpacing(10)
        range_spin_form.setVerticalSpacing(4)

        self._range_start = QDoubleSpinBox()
        self._range_start.setRange(-10000.0, 10000.0)
        self._range_start.setDecimals(2)
        self._range_start.setSuffix(" eV")
        self._range_start.setValue(-10.0)
        self._range_start.setEnabled(False)
        range_spin_form.addRow("    From:", self._range_start)

        self._range_end = QDoubleSpinBox()
        self._range_end.setRange(-10000.0, 10000.0)
        self._range_end.setDecimals(2)
        self._range_end.setSuffix(" eV")
        self._range_end.setValue(10.0)
        self._range_end.setEnabled(False)
        range_spin_form.addRow("    To:", self._range_end)

        adv_layout.addLayout(range_spin_form)

        # calibrate, subpixel, crop, print_stats
        self._calibrate_cb   = QCheckBox("Calibrate axis after alignment  (set ZLP offset → 0)")
        self._calibrate_cb.setChecked(True)
        self._subpixel_cb    = QCheckBox("Subpixel accuracy  (cross-correlation)")
        self._subpixel_cb.setChecked(True)
        self._crop_cb        = QCheckBox("Crop signal axis at both ends if needed")
        self._crop_cb.setChecked(True)
        self._print_stats_cb = QCheckBox("Print alignment statistics to console")
        self._print_stats_cb.setChecked(True)

        for cb in (self._calibrate_cb, self._subpixel_cb, self._crop_cb, self._print_stats_cb):
            adv_layout.addWidget(cb)

        root.addWidget(adv_grp)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        # connections
        self._also_core_cb.toggled.connect(self._on_toggle_core)
        self._low_combo.currentIndexChanged.connect(self._apply_default_core_choice)
        self._range_cb.toggled.connect(self._on_toggle_range)
        adv_grp.toggled.connect(self._on_adv_toggled)
        self._adv_grp = adv_grp

        self._apply_default_core_choice()

    def _on_adv_toggled(self, checked):
        """Show/hide advanced widgets when group box is toggled."""
        for child in self._adv_grp.findChildren(QCheckBox) + \
                     self._adv_grp.findChildren(QDoubleSpinBox):
            child.setVisible(checked)
        # Re-apply range-enable state.
        if checked:
            self._on_toggle_range(self._range_cb.isChecked())

    def _on_toggle_range(self, checked):
        self._range_start.setEnabled(checked)
        self._range_end.setEnabled(checked)

    def _on_toggle_core(self, checked):
        self._core_combo.setEnabled(bool(self._core_entries) and checked)

    def _apply_default_core_choice(self):
        if not self._core_entries:
            return
        low = self.selected_low_entry()
        if not low:
            return

        target_dataset_id = low.get("dataset_id")
        target_signal = low.get("signal")

        # Prefer a core-loss signal from the same dataset as the chosen low-loss.
        preferred_idx = None
        for i, e in enumerate(self._core_entries):
            if e.get("dataset_id") == target_dataset_id and e.get("signal") is not target_signal:
                preferred_idx = i
                break

        if preferred_idx is None:
            # Fallback: first available core-loss not identical to selected low-loss.
            for i, e in enumerate(self._core_entries):
                if e.get("signal") is not target_signal:
                    preferred_idx = i
                    break

        if preferred_idx is None:
            self._core_combo.setCurrentIndex(0)
        else:
            self._core_combo.setCurrentIndex(preferred_idx + 1)

    def selected_low_entry(self):
        idx = self._low_combo.currentData()
        if idx is None:
            return None
        if 0 <= int(idx) < len(self._low_entries):
            return self._low_entries[int(idx)]
        return None

    def selected_core_entry(self):
        if not self._also_core_cb.isChecked() or not self._core_entries:
            return None
        idx = self._core_combo.currentData()
        if idx is None:
            return None
        if 0 <= int(idx) < len(self._core_entries):
            return self._core_entries[int(idx)]
        return None

    def align_kwargs(self):
        """Return kwargs dict to pass to align_zero_loss_peak."""
        kw = dict(
            calibrate=self._calibrate_cb.isChecked(),
            subpixel=self._subpixel_cb.isChecked(),
            crop=self._crop_cb.isChecked(),
            print_stats=self._print_stats_cb.isChecked(),
        )
        if self._range_cb.isChecked():
            kw["signal_range"] = (self._range_start.value(), self._range_end.value())
        return kw


class _SumAxesDialog(QDialog):
    """Dialog to choose which axes of a signal to sum over."""

    def __init__(self, parent, signal):
        super().__init__(parent)
        self.setWindowTitle("Sum Along Axes")
        self.setMinimumWidth(560)
        self._axis_checks = []

        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(14, 14, 14, 10)

        hint = QLabel(
            f"Select the navigation and/or signal axes to sum for:\n{get_signal_title(signal)}"
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

        nav_axes = list(getattr(signal.axes_manager, "navigation_axes", []) or [])
        sig_axes = list(getattr(signal.axes_manager, "signal_axes", []) or [])

        root.addWidget(self._build_axis_group("Navigation axes", nav_axes, checked=True))
        root.addWidget(self._build_axis_group("Signal axes", sig_axes, checked=False))

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    def _build_axis_group(self, title, axes, checked):
        grp = QGroupBox(title)
        layout = QVBoxLayout(grp)
        layout.setSpacing(6)
        layout.setContentsMargins(10, 8, 10, 8)

        if not axes:
            empty = QLabel("No axes in this group.")
            empty.setEnabled(False)
            layout.addWidget(empty)
            return grp

        for axis in axes:
            cb = QCheckBox(self._axis_label(axis))
            cb.setChecked(checked)
            layout.addWidget(cb)
            self._axis_checks.append((cb, axis))

        return grp

    @staticmethod
    def _axis_label(axis):
        try:
            name = str(getattr(axis, "name", "") or "unnamed")
            size = getattr(axis, "size", None)
            scale = getattr(axis, "scale", None)
            offset = getattr(axis, "offset", None)
            units = str(getattr(axis, "units", "") or "")
            unit_txt = f" {units}" if units else ""
            return (
                f"{name}  "
                f"(size={size}, scale={scale}, offset={offset}{unit_txt})"
            )
        except Exception:
            return str(axis)

    def _on_accept(self):
        if not self.selected_axes():
            QMessageBox.warning(self, "Sum Along Axes", "Select at least one axis to sum.")
            return
        self.accept()

    def selected_axes(self):
        return tuple(axis for cb, axis in self._axis_checks if cb.isChecked())


class _RebinDialog(QDialog):
    """Dialog to configure HyperSpy rebin() per axis."""

    class _TrimmedDoubleSpinBox(QDoubleSpinBox):
        """QDoubleSpinBox that removes trailing zeros in its text display."""

        def textFromValue(self, value):
            txt = f"{float(value):.{self.decimals()}f}".rstrip("0").rstrip(".")
            return txt if txt else "0"

    _DTYPES = [
        "Auto",
        "float32",
        "float64",
        "int16",
        "int32",
        "uint16",
        "uint32",
        "complex64",
        "complex128",
    ]

    def __init__(self, parent, signal):
        super().__init__(parent)
        self.setWindowTitle("Rebin Signal")
        self.setMinimumWidth(700)
        self._axis_spins = []
        am = getattr(signal, "axes_manager", None)
        axes = []
        if am is not None:
            try:
                # Keep HyperSpy's native axis order for rebin(scale=...).
                axes = list(getattr(am, "_axes", []) or [])
            except Exception:
                axes = []
            if not axes:
                try:
                    axes = list(getattr(am, "navigation_axes", []) or []) + list(
                        getattr(am, "signal_axes", []) or []
                    )
                except Exception:
                    axes = []
        self._axes = axes

        try:
            nav_ids = {id(ax) for ax in (getattr(am, "navigation_axes", []) or [])}
        except Exception:
            nav_ids = set()

        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(14, 14, 14, 10)

        hint = QLabel(
            "Set rebin scale for any axis. Use 1.0 to keep an axis unchanged.\n"
            f"Signal: {get_signal_title(signal)}"
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

        axis_grp = QGroupBox("Axis Scales")
        axis_form = QFormLayout(axis_grp)
        axis_form.setHorizontalSpacing(10)
        axis_form.setVerticalSpacing(8)

        if not self._axes:
            empty = QLabel("No axes available.")
            empty.setEnabled(False)
            axis_form.addRow(empty)
        else:
            for axis in self._axes:
                spin = self._TrimmedDoubleSpinBox()
                spin.setRange(1e-9, 1e9)
                spin.setDecimals(6)
                spin.setValue(1.0)
                spin.setSingleStep(0.1)
                spin.setKeyboardTracking(False)
                axis_form.addRow(self._axis_label(axis, nav_ids), spin)
                self._axis_spins.append(spin)

        root.addWidget(axis_grp)

        adv_grp = QGroupBox("Advanced")
        adv_form = QFormLayout(adv_grp)
        adv_form.setHorizontalSpacing(10)
        adv_form.setVerticalSpacing(8)

        self._dtype_combo = QComboBox()
        self._dtype_combo.addItems(self._DTYPES)
        adv_form.addRow("dtype:", self._dtype_combo)

        self._crop_cb = QCheckBox("crop")
        self._crop_cb.setChecked(True)
        self._crop_cb.setToolTip("If checked, trim edges so rebinned shape is exact.")
        adv_form.addRow("", self._crop_cb)

        root.addWidget(adv_grp)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

    @staticmethod
    def _axis_label(axis, nav_ids):
        try:
            role = "nav" if id(axis) in nav_ids else "sig"
            name = str(getattr(axis, "name", "") or "unnamed")
            size = getattr(axis, "size", None)
            units = str(getattr(axis, "units", "") or "")
            unit_txt = f" {units}" if units else ""
            return f"[{role}] {name}  (size={size}{unit_txt})"
        except Exception:
            return str(axis)

    def _on_accept(self):
        if not self._axes:
            QMessageBox.warning(self, "Rebin", "Selected signal has no axes to rebin.")
            return
        if all(abs(spin.value() - 1.0) < 1e-12 for spin in self._axis_spins):
            QMessageBox.warning(
                self,
                "Rebin",
                "At least one axis scale must be different from 1.0.",
            )
            return
        self.accept()

    def scales(self):
        return tuple(float(spin.value()) for spin in self._axis_spins)

    def crop_enabled(self):
        return bool(self._crop_cb.isChecked())

    def dtype_value(self):
        txt = self._dtype_combo.currentText()
        if txt == "Auto":
            return None
        try:
            return np.dtype(txt).type
        except Exception:
            return None


class EMDataStudioApp(QMainWindow):
    """Main application window for EMDataStudio."""

    LOAD_FORMATS = [
        "HyperSpy / HDF5 (*.hspy *.zspy *.h5 *.hdf5 *.emd *.nxs)",
        "DigitalMicrograph (*.dm3 *.dm4)",
        "MRC family (*.mrc *.mrcs *.mrcz)",
        "Electron microscopy data (*.emi *.ser *.blo *.rpl *.unf *.tvips *.tvf *.prz *.mib *.bcf *.spc *.spd *.elid *.de5 *.app5 *.wdf)",
        "Images and spectra (*.tif *.tiff *.png *.jpg *.jpeg *.msa *.emsa *.npy *.nc *.sur *.pro *.img *.xml *.raw *.dens *.csv *.log)",
    ]

    SAVE_FORMATS = [
        ("HyperSpy HDF5 (*.hspy)", ".hspy"),
        ("HyperSpy Zarr (*.zspy)", ".zspy"),
        ("HDF5 / USID / EMD (*.h5 *.hdf5 *.emd)", ".h5"),
        ("NeXus (*.nxs)", ".nxs"),
        ("NumPy (*.npy)", ".npy"),
        ("EMSA / MSA (*.msa)", ".msa"),
        ("TIFF (*.tif *.tiff)", ".tif"),
        ("PNG (*.png)", ".png"),
        ("JPEG (*.jpg *.jpeg)", ".jpg"),
        ("MRCZ (*.mrcz)", ".mrcz"),
        ("Ripple (*.rpl)", ".rpl"),
        ("SEMPER UNF (*.unf)", ".unf"),
        ("Blockfile (*.blo)", ".blo"),
        ("DigitalSurf (*.sur *.pro)", ".sur"),
        ("TVIPS (*.tvips)", ".tvips"),
        ("Phanta Rhei (*.prz)", ".prz"),
    ]

    def __init__(self):
        super().__init__()
        
        # Initialize configuration
        self.config = AppConfig()
        
        self.setWindowTitle("EMDataStudio  —  HyperSpy Data Visualizer")
        self.resize(1400, 860)
        self._apply_stylesheet()
        self._load_thread = None
        self._load_queue = []
        self._current_loading_path = ""
        self._current_loading_batch_id = None
        self._load_batch_next_id = 1
        self._load_batch_pending = {}
        self._load_batch_signals = {}
        self._load_batch_files = {}
        self._load_batch_failed = {}
        self._selected_signal = None
        self._undo_recording = True   # set False during undo/redo to suppress re-recording
        self._undo_stack = _UndoStack()

        self._setup_ui()
        self._setup_menu()
        self._setup_statusbar()

    def _apply_stylesheet(self):
        """Apply stylesheet based on current configuration."""
        self.setStyleSheet(self.config.get_stylesheet())

    def _refresh_ui_style(self):
        """Refresh UI styling after settings change."""
        self._apply_stylesheet()
        if hasattr(self, 'data_list'):
            self.data_list.update_styling(self.config)
        if hasattr(self, 'viewer'):
            self.viewer.update_styling(self.config)

    # ── UI Layout ─────────────────────────────────────────────────────────────
    def _setup_ui(self):
        splitter = QSplitter(Qt.Horizontal)
        self.setCentralWidget(splitter)

        self.data_list = DataListWidget(self.config)
        self.data_list.setMinimumWidth(260)
        self.data_list.setMaximumWidth(380)
        self.data_list.signal_selected.connect(self._on_signal_selected)
        self.data_list.context_action.connect(self._handle_context_action)
        self.data_list.workspace_added.connect(self._undo_on_workspace_added)
        self.data_list.workspace_renamed.connect(self._undo_on_workspace_renamed)
        self.data_list.dataset_renamed.connect(self._undo_on_dataset_renamed)
        self.data_list.signal_renamed.connect(self._undo_on_signal_renamed)
        self.data_list.signal_moved.connect(self._undo_on_signal_moved)
        self.data_list.dataset_moved.connect(self._undo_on_dataset_moved)
        self.data_list.signals_copied.connect(self._undo_on_signals_copied)
        self.data_list.signal_created.connect(self._undo_on_signal_created)
        self.data_list.dataset_sorted.connect(self._undo_on_dataset_sorted)
        splitter.addWidget(self.data_list)

        self.viewer = ViewerWidget(self.config)
        self.viewer.elemental_map_exported.connect(self._on_elemental_map_exported)
        self.viewer.background_removed_exported.connect(self._on_background_removed)
        self.viewer.cropped_signals_exported.connect(self._on_cropped_signals_exported)
        self.viewer.pca_exported.connect(self._on_pca_exported)
        self.viewer.deconvolution_exported.connect(self._on_deconvolution_done)
        splitter.addWidget(self.viewer)

        splitter.setSizes([300, 1100])

    def _setup_menu(self):
        mb = self.menuBar()

        # ── File ──────────────────────────────────────────────────────────────
        file_menu = mb.addMenu("&File")

        act_load = QAction("&Load File(s)…", self)
        act_load.setShortcut("Ctrl+O")
        act_load.setStatusTip("Open one or more HyperSpy/electron microscopy files")
        act_load.triggered.connect(self._load_file)
        file_menu.addAction(act_load)

        act_load_pack = QAction("Load .&eelspack…", self)
        act_load_pack.setStatusTip("Open an EELS pack container (.eelspack)")
        act_load_pack.triggered.connect(self._load_eelspack)
        file_menu.addAction(act_load_pack)

        file_menu.addSeparator()

        act_exit = QAction("E&xit", self)
        act_exit.setShortcut("Ctrl+Q")
        act_exit.triggered.connect(self.close)
        file_menu.addAction(act_exit)

        # ── Edit ─────────────────────────────────────────────────────────────
        edit_menu = mb.addMenu("&Edit")

        self._act_undo = QAction(self.style().standardIcon(QStyle.SP_ArrowBack), "&Undo", self)
        self._act_undo.setShortcut("Ctrl+Z")
        self._act_undo.setEnabled(False)
        self._act_undo.triggered.connect(self._do_undo)
        edit_menu.addAction(self._act_undo)

        self._act_redo = QAction(self.style().standardIcon(QStyle.SP_ArrowForward), "&Redo", self)
        self._act_redo.setShortcut("Ctrl+Y")
        self._act_redo.setEnabled(False)
        self._act_redo.triggered.connect(self._do_redo)
        edit_menu.addAction(self._act_redo)

        edit_menu.addSeparator()

        # ── View ──────────────────────────────────────────────────────────────
        view_menu = mb.addMenu("&View")

        act_clear = QAction("&Clear Viewer", self)
        act_clear.triggered.connect(self.viewer.clear_display)
        view_menu.addAction(act_clear)

        view_menu.addSeparator()

        act_plot_manager = QAction("&Plot Manager", self)
        act_plot_manager.setShortcut("Ctrl+Shift+M")
        act_plot_manager.setStatusTip("Show or hide the Plot Manager panel (lists all open plot windows)")
        act_plot_manager.triggered.connect(self.viewer.toggle_plot_manager)
        view_menu.addAction(act_plot_manager)

        # ── Functions ─────────────────────────────────────────────────────────
        functions_menu = mb.addMenu("F&unctions")

        act_sort = QAction("&Sort Signals by Frame", self)
        act_sort.setStatusTip("Group signals by frame index (HAADF/CoreL/LowL)")
        act_sort.triggered.connect(self._sort_signals)
        functions_menu.addAction(act_sort)

        act_sum = QAction("&Sum", self)
        act_sum.setStatusTip("Sum the selected signal along chosen navigation and/or signal axes")
        act_sum.triggered.connect(self._sum_signal_axes)
        functions_menu.addAction(act_sum)

        functions_menu.addSeparator()

        act_crop = QAction("&Crop signals", self)
        act_crop.setStatusTip("Interactively crop selected signal on signal axes and export results")
        act_crop.triggered.connect(self._crop_signals)
        functions_menu.addAction(act_crop)

        act_rebin = QAction("&Rebin", self)
        act_rebin.setStatusTip("Rebin selected signal along chosen navigation and/or signal axes")
        act_rebin.triggered.connect(self._rebin_signal)
        functions_menu.addAction(act_rebin)

        act_fft = QAction("&FFT", self)
        act_fft.setStatusTip("Fast Fourier transform (placeholder)")
        act_fft.triggered.connect(lambda: self._feature_placeholder("FFT"))
        functions_menu.addAction(act_fft)

        functions_menu.addSeparator()

        self.act_create_roi = QAction("Create &2D ROI", self)
        self.act_create_roi.triggered.connect(self._toggle_2d_roi)
        functions_menu.addAction(self.act_create_roi)

        self.act_export_roi = QAction("Export 2D ROI Crops…", self)
        self.act_export_roi.setStatusTip("Export current HyperSpy 2D ROI crops into a new dataset")
        self.act_export_roi.triggered.connect(self._export_roi_crops)
        functions_menu.addAction(self.act_export_roi)

        functions_menu.addSeparator()

        self.act_multi_roi = QAction("Create &Multiple 2D ROIs…", self)
        self.act_multi_roi.setStatusTip("Open the multi-ROI panel to place and manage several ROIs simultaneously")
        self.act_multi_roi.triggered.connect(self._open_multi_roi_panel)
        functions_menu.addAction(self.act_multi_roi)

        self.act_export_multi_roi = QAction("Export Multiple 2D ROI Crops…", self)
        self.act_export_multi_roi.setStatusTip("Export crops for all numbered multi-ROIs into a new dataset")
        self.act_export_multi_roi.triggered.connect(self._export_multi_roi_crops)
        functions_menu.addAction(self.act_export_multi_roi)

        self.viewer.roi_state_changed.connect(self._update_roi_action)
        self._update_roi_action(self.viewer.has_shared_2d_roi())
        self._multi_roi_panel = None

        # ── EELS ─────────────────────────────────────────────────────────────
        eels_menu = mb.addMenu("&EELS")

        act_align_zlp = QAction("Align zero loss peak", self)
        act_align_zlp.setStatusTip("Align low-loss zero-loss peak; optionally align a core-loss signal together")
        act_align_zlp.triggered.connect(self._align_zero_loss_peak)
        eels_menu.addAction(act_align_zlp)

        act_pca = QAction("&PCA / Decomposition", self)
        act_pca.setStatusTip("Run PCA / decomposition on selected signal and interactively choose components")
        act_pca.triggered.connect(self._run_pca)
        eels_menu.addAction(act_pca)

        act_elemental_map = QAction("Elemental mapping", self)
        act_elemental_map.setStatusTip(
            "Open an interactive elemental map — drag the SpanROI on the mean spectrum to choose the integration window"
        )
        act_elemental_map.triggered.connect(self._elemental_mapping)
        eels_menu.addAction(act_elemental_map)

        act_retract_bg = QAction("Retract background", self)
        act_retract_bg.setStatusTip(
            "Interactively fit and subtract background from an EELS signal"
        )
        act_retract_bg.triggered.connect(self._retract_background)
        eels_menu.addAction(act_retract_bg)

        act_deconv = QAction("Deconvolution", self)
        act_deconv.setStatusTip(
            "Open interactive EELS deconvolution panel (Fourier-Log, Fourier-Ratio, Richardson-Lucy)"
        )
        act_deconv.triggered.connect(self._deconvolution)
        eels_menu.addAction(act_deconv)

        eels_menu.addSeparator()
        act_mark_eels = QAction("&Mark as EELS signal", self)
        act_mark_eels.setStatusTip(
            "Set signal_type to 'EELS' on selected signal(s) so exspy EELS tools apply correctly"
        )
        act_mark_eels.triggered.connect(self._mark_signals_as_eels)
        eels_menu.addAction(act_mark_eels)

        # ── Settings ──────────────────────────────────────────────────────────
        settings_menu = mb.addMenu("&Settings")

        act_preferences = QAction("&Preferences…", self)
        act_preferences.setShortcut("Ctrl+,")
        act_preferences.setStatusTip("Open application settings")
        act_preferences.triggered.connect(self._open_settings)
        settings_menu.addAction(act_preferences)

        # ── Help ──────────────────────────────────────────────────────────────
        help_menu = mb.addMenu("&Help")
        act_about = QAction("&About", self)
        act_about.triggered.connect(self._show_about)
        help_menu.addAction(act_about)

    def _setup_statusbar(self):
        sb = QStatusBar()
        self.setStatusBar(sb)
        sb.showMessage("Ready.  Use  File → Load File  to open a dataset.")

    def _feature_placeholder(self, feature_name):
        """Temporary placeholder action for not-yet-implemented features."""
        QMessageBox.information(
            self,
            "Coming Soon",
            f"{feature_name} is not implemented yet.",
        )
        self.statusBar().showMessage(f"Placeholder clicked: {feature_name}", 3000)

    # ── Undo / Redo ───────────────────────────────────────────────────────────

    def _refresh_undo_actions(self):
        can_undo = self._undo_stack.can_undo()
        self._act_undo.setEnabled(can_undo)
        self._act_undo.setText(
            f"&Undo  {self._undo_stack.undo_label()}" if can_undo else "&Undo"
        )
        can_redo = self._undo_stack.can_redo()
        self._act_redo.setEnabled(can_redo)
        self._act_redo.setText(
            f"&Redo  {self._undo_stack.redo_label()}" if can_redo else "&Redo"
        )

    def _do_undo(self):
        self._undo_recording = False
        try:
            label = self._undo_stack.undo()
        finally:
            self._undo_recording = True
        if label:
            self.statusBar().showMessage(f"Undid: {label}", 4000)
        self._refresh_undo_actions()

    def _do_redo(self):
        self._undo_recording = False
        try:
            label = self._undo_stack.redo()
        finally:
            self._undo_recording = True
        if label:
            self.statusBar().showMessage(f"Redid: {label}", 4000)
        self._refresh_undo_actions()

    def _add_dataset_undoable(self, name: str, signals: list):
        """Call add_dataset_to_active_workspace and record an undo command."""
        ws_id = self.data_list.active_workspace_id
        dataset_id = self.data_list.add_dataset_to_active_workspace(name, signals)

        def _undo():
            self.data_list.remove_dataset_by_id(dataset_id)

        def _redo():
            self.data_list._set_active_workspace(ws_id)
            self.data_list.add_dataset_to_active_workspace(name, signals)

        self._undo_stack.push(_undo, _redo, f"Add '{name}'")
        self._refresh_undo_actions()
        return dataset_id

    # ── Undo handlers for DataListWidget-internal mutations ───────────────────

    def _undo_on_workspace_added(self, ws_id: int, name: str):
        if not self._undo_recording:
            return

        def _undo():
            self.data_list.close_workspace_by_id(ws_id)

        def _redo():
            self.data_list.add_workspace(name)

        self._undo_stack.push(_undo, _redo, f"Add workspace '{name}'")
        self._refresh_undo_actions()

    def _undo_on_workspace_renamed(self, ws_id: int, old_name: str, new_name: str):
        if not self._undo_recording:
            return

        def _undo():
            self.data_list._rename_workspace_by_id(ws_id, old_name)

        def _redo():
            self.data_list._rename_workspace_by_id(ws_id, new_name)

        self._undo_stack.push(_undo, _redo, f"Rename workspace \u2018{old_name}\u2019 \u2192 \u2018{new_name}\u2019")
        self._refresh_undo_actions()

    def _undo_on_dataset_renamed(self, ds_id: int, old_name: str, new_name: str):
        if not self._undo_recording:
            return

        def _undo():
            self.data_list._rename_dataset_by_id(ds_id, old_name)

        def _redo():
            self.data_list._rename_dataset_by_id(ds_id, new_name)

        self._undo_stack.push(_undo, _redo, f"Rename \u2018{old_name}\u2019 \u2192 \u2018{new_name}\u2019")
        self._refresh_undo_actions()

    def _undo_on_signal_renamed(self, sig, old_name: str, new_name: str):
        if not self._undo_recording:
            return

        def _apply(display_name):
            sig._ev_display_name = display_name
            for ds in self.data_list.datasets.values():
                if self.data_list._find_signal_index(ds["signals"], sig) is not None:
                    self.data_list._render_dataset(ds)
                    break

        self._undo_stack.push(
            lambda: _apply(old_name),
            lambda: _apply(new_name),
            f"Rename signal \u2018{old_name}\u2019 \u2192 \u2018{new_name}\u2019",
        )
        self._refresh_undo_actions()

    def _undo_on_signal_moved(self, sig, src_ds_id: int, tgt_ds_id: int):
        if not self._undo_recording:
            return

        try:
            short = get_signal_title(sig)
        except Exception:
            short = "signal"

        self._undo_stack.push(
            lambda: self.data_list._move_signal_to_dataset(sig, tgt_ds_id, src_ds_id),
            lambda: self.data_list._move_signal_to_dataset(sig, src_ds_id, tgt_ds_id),
            f"Move signal \u2018{short}\u2019",
        )
        self._refresh_undo_actions()

    def _undo_on_dataset_moved(self, ds_id: int, src_ws_id: int, tgt_ws_id: int):
        if not self._undo_recording:
            return

        ds = self.data_list.datasets.get(ds_id)
        name = ds["name"] if ds else str(ds_id)

        self._undo_stack.push(
            lambda: self.data_list._move_dataset_to_workspace(ds_id, src_ws_id),
            lambda: self.data_list._move_dataset_to_workspace(ds_id, tgt_ws_id),
            f"Move dataset \u2018{name}\u2019",
        )
        self._refresh_undo_actions()

    def _undo_on_signals_copied(self, clones: list, tgt_ds_id: int):
        if not self._undo_recording:
            return

        n = len(clones)

        def _undo():
            self.data_list.remove_signals(clones)

        def _redo():
            self.data_list.restore_signals_to_dataset(tgt_ds_id, clones)

        self._undo_stack.push(_undo, _redo, f"Copy {n} signal(s)")
        self._refresh_undo_actions()

    def _undo_on_signal_created(self, sig, ds_id: int):
        if not self._undo_recording:
            return

        try:
            name = get_signal_title(sig)
        except Exception:
            name = "signal"

        self._undo_stack.push(
            lambda: self.data_list.remove_signals([sig]),
            lambda: self.data_list.restore_signals_to_dataset(ds_id, [sig]),
            f"Create signal \u2018{name}\u2019",
        )
        self._refresh_undo_actions()

    def _undo_on_dataset_sorted(self, ds_id: int, old_signals: list, was_grouped: bool):
        if not self._undo_recording:
            return

        dataset = self.data_list.datasets.get(ds_id)
        name = dataset["name"] if dataset else str(ds_id)

        def _undo():
            ds = self.data_list.datasets.get(ds_id)
            if ds is None:
                return
            ds["signals"] = list(old_signals)
            ds["grouped"] = was_grouped
            ds["grouped_signals"] = None
            self.data_list._render_dataset(ds)
            self.data_list._sync_active_signals()

        def _redo():
            old_current = self.data_list.current_dataset_id
            self.data_list.current_dataset_id = ds_id
            self.data_list.sort_current_dataset_by_frame()
            self.data_list.current_dataset_id = old_current

        self._undo_stack.push(_undo, _redo, f"Sort \u2018{name}\u2019 by frame")
        self._refresh_undo_actions()

    # ── File loading ──────────────────────────────────────────────────────────
    def _load_file(self):
        filepaths, _ = QFileDialog.getOpenFileNames(
            self,
            "Open HyperSpy / Electron Microscopy File(s)",
            "",
            self._load_filters(),
        )
        if not filepaths:
            return

        # Keep user selection order while avoiding duplicate loads.
        deduped = []
        seen = set()
        for path in filepaths:
            if path in seen:
                continue
            seen.add(path)
            deduped.append(path)

        batch_id = self._load_batch_next_id
        self._load_batch_next_id += 1
        self._load_batch_pending[batch_id] = len(deduped)
        self._load_batch_signals[batch_id] = []
        self._load_batch_files[batch_id] = list(deduped)
        self._load_batch_failed[batch_id] = []

        for path in deduped:
            self._load_queue.append((batch_id, path))

        if len(deduped) == 1:
            self.statusBar().showMessage(
                f"Queued  {os.path.basename(deduped[0])}  for loading."
            )
        else:
            self.statusBar().showMessage(
                f"Queued  {len(deduped)} files for loading."
            )
        QApplication.processEvents()

        self._start_next_file_load()

    def _start_next_file_load(self):
        if self._load_thread is not None and self._load_thread.isRunning():
            return
        if not self._load_queue:
            return

        batch_id, filepath = self._load_queue.pop(0)
        self._current_loading_batch_id = batch_id
        self._current_loading_path = filepath

        self.statusBar().showMessage(
            f"Loading  {os.path.basename(filepath)} …  (please wait)"
        )
        QApplication.processEvents()

        # Run in background thread to keep UI responsive
        self._load_thread = LoadThread(filepath)
        self._load_thread.loaded.connect(self._on_loaded)
        self._load_thread.error.connect(self._on_load_error)
        self._load_thread.start()

    def _on_loaded(self, signals):
        n = len(signals)
        batch_id = self._current_loading_batch_id
        fname = os.path.basename(self._current_loading_path) if self._current_loading_path else ""

        if batch_id in self._load_batch_signals:
            self._load_batch_signals[batch_id].extend(signals)
            self._load_batch_pending[batch_id] = max(0, self._load_batch_pending.get(batch_id, 0) - 1)

        remaining = len(self._load_queue)
        if remaining > 0:
            self.statusBar().showMessage(
                f"Loaded  {n} signal{'s' if n != 1 else ''}  from  {fname}.  {remaining} file{'s' if remaining != 1 else ''} remaining…"
            )
        else:
            self.statusBar().showMessage(
                f"Loaded  {n} signal{'s' if n != 1 else ''}  from  {fname}"
            )

        self._finalize_load_batch_if_done(batch_id)
        self._load_thread = None
        self._current_loading_path = ""
        self._current_loading_batch_id = None
        self._start_next_file_load()

    def _on_load_error(self, msg):
        batch_id = self._current_loading_batch_id
        fname = os.path.basename(self._current_loading_path) if self._current_loading_path else "(unknown file)"
        QMessageBox.critical(self, "Error Loading File", f"{fname}\n\n{msg}")
        if batch_id in self._load_batch_pending:
            self._load_batch_pending[batch_id] = max(0, self._load_batch_pending.get(batch_id, 0) - 1)
            self._load_batch_failed.setdefault(batch_id, []).append(fname)
        remaining = len(self._load_queue)
        if remaining > 0:
            self.statusBar().showMessage(
                f"Failed to load  {fname}.  Continuing with {remaining} remaining file{'s' if remaining != 1 else ''}…"
            )
        else:
            self.statusBar().showMessage(f"Failed to load  {fname}.")

        self._finalize_load_batch_if_done(batch_id)
        self._load_thread = None
        self._current_loading_path = ""
        self._current_loading_batch_id = None
        self._start_next_file_load()

    def _finalize_load_batch_if_done(self, batch_id):
        if batch_id is None:
            return
        if self._load_batch_pending.get(batch_id, 0) > 0:
            return

        signals = self._load_batch_signals.get(batch_id, [])
        filepaths = self._load_batch_files.get(batch_id, [])
        failed = self._load_batch_failed.get(batch_id, [])

        if signals:
            if len(filepaths) <= 1:
                dataset_name = os.path.basename(filepaths[0]) if filepaths else "Dataset"
            else:
                first_name = os.path.basename(filepaths[0])
                dataset_name = f"{first_name} (+{len(filepaths) - 1} files)"
            self._add_dataset_undoable(dataset_name, signals)

            if failed:
                self.statusBar().showMessage(
                    f"Loaded {len(signals)} signal(s) from {len(filepaths) - len(failed)} file(s) into one dataset; {len(failed)} file(s) failed."
                )
            else:
                self.statusBar().showMessage(
                    f"Loaded {len(signals)} signal(s) from {len(filepaths)} file(s) into one dataset."
                )
        else:
            self.statusBar().showMessage("No signals were loaded from selected files.")

        self._load_batch_pending.pop(batch_id, None)
        self._load_batch_signals.pop(batch_id, None)
        self._load_batch_files.pop(batch_id, None)
        self._load_batch_failed.pop(batch_id, None)

    def _load_eelspack(self):
        """Load signals from a native .eelspack container."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open EELS Pack",
            "",
            "EELS Pack (*.eelspack *.zip);;All Files (*)",
        )
        if not path:
            return

        self.statusBar().showMessage(
            f"Loading EELS pack  {os.path.basename(path)} …  (please wait)"
        )
        QApplication.processEvents()

        try:
            signals, manifest = load_eelspack(path)
        except Exception as e:
            QMessageBox.critical(self, "Error Loading EELS Pack", str(e))
            self.statusBar().showMessage("Failed to load EELS pack.")
            return

        if not signals:
            QMessageBox.warning(self, "Load EELS Pack", "No signals were found in the pack.")
            self.statusBar().showMessage("EELS pack contained no signals.")
            return

        pack_name = os.path.splitext(os.path.basename(path))[0]
        if isinstance(manifest, dict) and manifest.get("name"):
            pack_name = str(manifest.get("name"))

        groups = {}
        manifest_entries = []
        if isinstance(manifest, dict):
            manifest_entries = manifest.get("signals") or []

        # Pair each loaded signal with its manifest entry, then group by
        # workspace/dataset.  Tuples carry the ordering keys so we can sort
        # strictly before inserting into datasets.
        for idx, sig in enumerate(signals):
            entry = manifest_entries[idx] if idx < len(manifest_entries) else {}
            ws_name = (entry.get("source_workspace") or "Imported Workspace").strip()
            ds_name = (entry.get("source_dataset") or "Imported Dataset").strip()
            ws_order = entry.get("workspace_order", 0)
            ds_order = entry.get("dataset_order", 0)
            ds_sig_order = entry.get("dataset_signal_order", idx)
            groups.setdefault(ws_name, {"_ws_order": ws_order, "_datasets": {}})
            ds_map = groups[ws_name]["_datasets"]
            ds_map.setdefault(ds_name, {"_ds_order": ds_order, "_sigs": []})
            ds_map[ds_name]["_sigs"].append((ds_sig_order, sig))

        total_datasets = 0
        created_workspace_ids = []
        # Reconstruct workspaces in original workspace_order.
        self._undo_recording = False
        try:
            for ws_name in sorted(groups, key=lambda k: groups[k]["_ws_order"]):
                import_ws_name = f"{pack_name} - {ws_name}"
                ws_id = self.data_list.add_workspace(import_ws_name)
                created_workspace_ids.append(ws_id)
                self.data_list._set_active_workspace(ws_id)
                ds_map = groups[ws_name]["_datasets"]
                # Reconstruct datasets in original dataset_order.
                for ds_name in sorted(ds_map, key=lambda k: ds_map[k]["_ds_order"]):
                    # Sort signals within the dataset by dataset_signal_order.
                    ordered_sigs = [
                        sig for _, sig in
                        sorted(ds_map[ds_name]["_sigs"], key=lambda t: t[0])
                    ]
                    self.data_list.add_dataset_to_active_workspace(ds_name, ordered_sigs)
                    total_datasets += 1
        finally:
            self._undo_recording = True

        if created_workspace_ids:
            _ws_ids = list(created_workspace_ids)
            label = f"Load eelspack '{pack_name}' ({total_datasets} dataset(s))"

            def _undo_pack():
                for wid in _ws_ids:
                    self.data_list.close_workspace_by_id(wid)

            def _redo_pack():
                pass  # re-loading from file not supported here

            self._undo_stack.push(_undo_pack, _redo_pack, label)
            self._refresh_undo_actions()

        self.statusBar().showMessage(
            f"Loaded {len(signals)} signal(s) from EELS pack into {len(groups)} workspace(s), {total_datasets} dataset(s)."
        )

    # ── Signal selection ──────────────────────────────────────────────────────
    def _on_signal_selected(self, signal):
        self._selected_signal = signal
        title = get_signal_title(signal)
        self.statusBar().showMessage(f"Selected:  {title}  (use right-click -> Plot)")

    def _selected_tree_signal(self):
        try:
            item = self.data_list.tree_widget.currentItem()
        except Exception:
            return None
        if item is None:
            return None
        try:
            kind = item.data(0, self.data_list.ROLE_KIND)
        except Exception:
            return None
        if kind != "signal":
            return None
        try:
            dataset_id = item.data(0, self.data_list.ROLE_DATASET_ID)
            token = item.data(0, self.data_list.ROLE_SIGNAL_TOKEN)
            return self.data_list._resolve_signal(token, dataset_id)
        except Exception:
            return None

    def _active_viewer_signal(self):
        try:
            sub = self.viewer.desktop.activeSubWindow()
            if sub is not None:
                widget = sub.widget()
                sig = getattr(widget, "signal", None)
                if sig is not None:
                    return sig
        except Exception:
            pass
        return getattr(self.viewer, "current_signal", None)

    def _current_transform_signal(self):
        sig = self._selected_tree_signal()
        if sig is not None:
            return sig
        sig = self._active_viewer_signal()
        if sig is not None:
            return sig
        return self._selected_signal

    def _open_plot_signals(self):
        """Return unique signals currently open in MDI subwindows."""
        out = []
        seen = set()
        try:
            subs = self.viewer.desktop.subWindowList()
        except Exception:
            subs = []
        for sub in subs:
            try:
                widget = sub.widget()
                sig = getattr(widget, "signal", None)
            except Exception:
                sig = None
            if sig is None:
                continue
            sid = id(sig)
            if sid in seen:
                continue
            seen.add(sid)
            out.append(sig)
        return out

    def _signal_source_map(self):
        """Map signal identity -> workspace/dataset/source metadata."""
        ws_name_by_id = {ws.get("id"): ws.get("name", "") for ws in self.data_list.workspaces}
        source = {}
        for dataset_id, ds in self.data_list.datasets.items():
            ws_id   = ds.get("workspace_id")
            ws_name = ws_name_by_id.get(ws_id, "")
            ds_name = ds.get("name") or ""
            for sig in ds.get("signals", []):
                sid = id(sig)
                if sid not in source:
                    source[sid] = {
                        "workspace_name": ws_name,
                        "workspace_id":   ws_id,
                        "dataset_name": ds_name,
                        "dataset_id": dataset_id,
                        "from_dataset": True,
                    }
        for sig in self._open_plot_signals():
            sid = id(sig)
            if sid not in source:
                source[sid] = {
                    "workspace_name": "",
                    "workspace_id":   None,
                    "dataset_name": "",
                    "dataset_id": None,
                    "from_dataset": False,
                }
        return source

    def _signal_source_entry(self, signal):
        if signal is None:
            return None
        return self._signal_source_map().get(id(signal))

    def _collect_zlp_candidates(self):
        """Build low-loss/core-loss candidate entries from dataset and viewer context."""
        current_dataset_id = getattr(self.data_list, "current_dataset_id", None)
        active_dataset_signals = []
        if current_dataset_id is not None:
            active_dataset = self.data_list.datasets.get(current_dataset_id)
            if active_dataset is not None:
                active_dataset_signals = list(active_dataset.get("signals", []))

        combined = []
        seen = set()
        for sig in active_dataset_signals + self._open_plot_signals():
            sid = id(sig)
            if sid in seen:
                continue
            seen.add(sid)
            combined.append(sig)

        src_map = self._signal_source_map()

        entries = []
        for sig in combined:
            sid = id(sig)
            src = src_map.get(sid, {})
            cls_name = type(sig).__name__
            kind = classify_signal(sig)
            if cls_name != "EELSSpectrum" and "EELS" not in kind:
                continue

            where = "viewer-only"
            if src.get("from_dataset"):
                where = f"{src.get('workspace_name', '')} / {src.get('dataset_name', '')}".strip(" /")

            entries.append({
                "signal": sig,
                "title": get_signal_title(sig),
                "kind": kind,
                "dataset_id": src.get("dataset_id"),
                "label": f"{get_signal_title(sig)}   [{kind}]   ({where})",
                "in_current_dataset": src.get("dataset_id") == current_dataset_id,
            })

        # Prefer true low-loss classification first; fallback to EELS spectrum candidates.
        low = [e for e in entries if e["kind"] == "EELS LowLoss"]
        if not low:
            low = [e for e in entries if type(e["signal"]).__name__ == "EELSSpectrum"]

        core = [e for e in entries if e["kind"] == "EELS CoreLoss"]

        def _sort_key(e):
            return (0 if e["in_current_dataset"] else 1, e["title"].lower())

        low.sort(key=_sort_key)
        core.sort(key=_sort_key)
        return low, core

    def _refresh_plots_for_signals(self, signals):
        """Re-render open MDI plots that display any signal in signals."""
        target_ids = {id(s) for s in signals if s is not None}
        if not target_ids:
            return
        try:
            subs = self.viewer.desktop.subWindowList()
        except Exception:
            subs = []
        for sub in subs:
            widget = None
            try:
                widget = sub.widget()
            except Exception:
                pass
            sig = getattr(widget, "signal", None) if widget is not None else None
            if sig is None or id(sig) not in target_ids:
                continue
            try:
                widget.render()
            except Exception:
                pass

    def _align_zero_loss_peak(self):
        """Align selected low-loss ZLP, optionally aligning one core-loss signal too."""
        low_entries, core_entries = self._collect_zlp_candidates()
        if not low_entries:
            QMessageBox.warning(
                self,
                "Align Zero Loss Peak",
                "No suitable low-loss EELS signal found.\n\n"
                "Open or select a dataset containing low-loss EELS data first.",
            )
            return

        dlg = _AlignZlpDialog(self, low_entries, core_entries)
        if dlg.exec_() != QDialog.Accepted:
            return

        low_entry = dlg.selected_low_entry()
        if not low_entry:
            QMessageBox.warning(self, "Align Zero Loss Peak", "No low-loss signal selected.")
            return

        low_sig = low_entry["signal"]
        core_entry = dlg.selected_core_entry()
        core_sig = core_entry["signal"] if core_entry else None

        self.statusBar().showMessage("Running Align Zero Loss Peak…")
        QApplication.processEvents()

        kw = dlg.align_kwargs()

        try:
            if not hasattr(low_sig, "align_zero_loss_peak"):
                raise AttributeError("Selected low-loss signal does not support align_zero_loss_peak.")
            if core_sig is not None:
                low_sig.align_zero_loss_peak(also_align=[core_sig], **kw)
            else:
                low_sig.align_zero_loss_peak(**kw)
        except Exception as e:
            QMessageBox.critical(
                self,
                "Align Zero Loss Peak",
                f"Alignment failed:\n{e}",
            )
            self.statusBar().showMessage("Align Zero Loss Peak failed.")
            return

        self._refresh_plots_for_signals([low_sig, core_sig])

        if core_sig is not None:
            self.statusBar().showMessage(
                f"Aligned ZLP for '{get_signal_title(low_sig)}' and also aligned '{get_signal_title(core_sig)}'."
            )
        else:
            self.statusBar().showMessage(
                f"Aligned ZLP for '{get_signal_title(low_sig)}'."
            )

    def _sum_signal_axes(self):
        sig = self._current_transform_signal()
        if sig is None:
            QMessageBox.warning(
                self,
                "Sum Along Axes",
                "No active signal found. Select a signal in the data list or activate a plotted signal first.",
            )
            return

        if not hasattr(sig, "sum"):
            QMessageBox.warning(
                self,
                "Sum Along Axes",
                "The selected object does not support HyperSpy sum(axis=...).",
            )
            return

        dlg = _SumAxesDialog(self, sig)
        if dlg.exec_() != QDialog.Accepted:
            return

        axes = dlg.selected_axes()
        axis_names = [str(getattr(axis, "name", "") or "unnamed") for axis in axes]
        src_entry = self._signal_source_entry(sig)
        source_ws_id = None
        if isinstance(src_entry, dict):
            source_ws_id = src_entry.get("workspace_id")

        self.statusBar().showMessage("Summing selected axes…")
        QApplication.processEvents()

        try:
            result = sig.sum(axis=axes)
        except Exception as e:
            QMessageBox.critical(
                self,
                "Sum Along Axes",
                f"Summation failed:\n{e}",
            )
            self.statusBar().showMessage("Summation failed.")
            return

        if result is None:
            QMessageBox.information(
                self,
                "Sum Along Axes",
                "HyperSpy sum returned no output signal.",
            )
            self.statusBar().showMessage("Summation returned no output.")
            return

        # HyperSpy's sum() may demote the result to BaseSignal when all
        # navigation axes are removed.  Restore the original signal_type so
        # the viewer dispatches it correctly (e.g. EELSSpectrum → "EELS").
        try:
            orig_signal_type = sig.metadata.Signal.signal_type
            if orig_signal_type:
                result.set_signal_type(orig_signal_type)
        except Exception:
            pass

        out_name = f"{get_signal_title(sig)} (sum)"
        try:
            result.metadata.General.title = out_name
        except Exception:
            pass

        if source_ws_id is not None:
            self.data_list.active_workspace_id = source_ws_id
        self._add_dataset_undoable(out_name, [result])

        axes_txt = ", ".join(axis_names)
        self.statusBar().showMessage(
            f"Summed '{get_signal_title(sig)}' over {axes_txt} → '{out_name}'."
        )

    def _crop_signals(self):
        """Open an interactive crop panel for Signal1D/Signal2D signal-axis cropping."""
        sig = self._current_transform_signal()
        if sig is None:
            QMessageBox.warning(
                self,
                "Crop signals",
                "No active signal found. Select a signal in the data list or activate a plotted signal first.",
            )
            return

        am = getattr(sig, "axes_manager", None)
        if am is None:
            QMessageBox.warning(self, "Crop signals", "Selected signal has no axes_manager.")
            return

        sig_dim = int(getattr(am, "signal_dimension", 0) or 0)
        if sig_dim not in (1, 2):
            QMessageBox.warning(
                self,
                "Crop signals",
                f"Crop signals supports Signal1D or Signal2D only.\n\n"
                f"Selected signal dimension: {sig_dim}",
            )
            return

        n, ok = QInputDialog.getInt(
            self,
            "Crop signals",
            "How many crops to create?",
            value=1,
            min=1,
            max=128,
            step=1,
        )
        if not ok:
            self.statusBar().showMessage("Crop signals cancelled.")
            return

        title = f"Crop signals — {get_signal_title(sig)}"
        self.viewer.add_crop_signals_panel(sig, crop_count=int(n), title=title)
        self.statusBar().showMessage(
            f"Opened crop panel for '{get_signal_title(sig)}' with {int(n)} crop(s)."
        )

    def _run_pca(self):
        """Open an interactive PCA / decomposition panel for the selected signal."""
        try:
            sig = self._current_transform_signal()
            if sig is None:
                QMessageBox.warning(
                    self, "PCA / Decomposition",
                    "No active signal found. Select a signal in the data list "
                    "or activate a plotted signal first.",
                )
                return

            if not hasattr(sig, "decomposition"):
                QMessageBox.warning(
                    self, "PCA / Decomposition",
                    "The selected object does not support HyperSpy decomposition().",
                )
                return

            title = f"PCA — {get_signal_title(sig)}"
            self.viewer.add_pca_panel(sig, title=title)
            self.statusBar().showMessage(
                f"Opened PCA panel for '{get_signal_title(sig)}'."
            )
        except Exception as e:
            QMessageBox.critical(self, "PCA / Decomposition",
                                 f"Unexpected error opening PCA panel:\n{e}")

    def _on_pca_exported(self, signals, dataset_name):
        """Receive exported PCA result(s) and add them to the data list."""
        try:
            self._add_dataset_undoable(
                dataset_name, list(signals)
            )
            self.statusBar().showMessage(
                f"Exported PCA result → '{dataset_name}'."
            )
        except Exception as e:
            QMessageBox.critical(self, "PCA Export",
                                 f"Failed to add PCA result to data list:\n{e}")

    def _rebin_signal(self):
        try:
            sig = self._current_transform_signal()
            if sig is None:
                QMessageBox.warning(
                    self,
                    "Rebin",
                    "No active signal found. Select a signal in the data list or activate a plotted signal first.",
                )
                return

            if not hasattr(sig, "rebin"):
                QMessageBox.warning(
                    self,
                    "Rebin",
                    "The selected object does not support HyperSpy rebin(...).",
                )
                return

            dlg = _RebinDialog(self, sig)
            if dlg.exec_() != QDialog.Accepted:
                return

            source_ws_id = None
            src_entry = self._signal_source_entry(sig)
            if isinstance(src_entry, dict):
                source_ws_id = src_entry.get("workspace_id")

            kwargs = {
                "scale": dlg.scales(),
                "crop": dlg.crop_enabled(),
            }
            dtype = dlg.dtype_value()
            if dtype is not None:
                kwargs["dtype"] = dtype

            self.statusBar().showMessage("Rebinning selected signal…")
            QApplication.processEvents()

            try:
                result = sig.rebin(**kwargs)
            except Exception as e:
                QMessageBox.critical(self, "Rebin", f"Rebin failed:\n{e}")
                self.statusBar().showMessage("Rebin failed.")
                return

            if result is None:
                QMessageBox.information(self, "Rebin", "HyperSpy rebin returned no output signal.")
                self.statusBar().showMessage("Rebin returned no output.")
                return

            try:
                orig_signal_type = sig.metadata.Signal.signal_type
                if orig_signal_type:
                    result.set_signal_type(orig_signal_type)
            except Exception:
                pass

            out_name = f"{get_signal_title(sig)} (rebin)"
            try:
                result.metadata.General.title = out_name
            except Exception:
                pass

            if source_ws_id is not None:
                self.data_list.active_workspace_id = source_ws_id
            self._add_dataset_undoable(out_name, [result])

            self.statusBar().showMessage(
                f"Rebinned '{get_signal_title(sig)}' -> '{out_name}'."
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Rebin",
                f"Unexpected error before/after rebin:\n{e}",
            )
            self.statusBar().showMessage("Rebin failed unexpectedly.")

    def _elemental_mapping(self):
        """Open an interactive elemental mapping panel for the active Signal1D.

        Resolution order
        ----------------
        1. The signal selected in the data-list tree.
        2. The signal in the currently active MDI subwindow.
        3. The last cached selected signal.

        The signal must be a Signal1D (1-D signal axis) with at least one
        navigation dimension so that an integration map can be computed.
        """
        sig = self._current_transform_signal()

        if sig is None:
            # No selection — check whether any plots are open at all.
            subs = self.viewer.desktop.subWindowList()
            if not subs:
                QMessageBox.warning(
                    self,
                    "Elemental Mapping",
                    "No signal is plotted.\n\n"
                    "Please plot a Signal1D (e.g. an EELS spectrum image) first.",
                )
                return
            QMessageBox.warning(
                self,
                "Elemental Mapping",
                "No signal is selected.\n\n"
                "Select a signal in the data list or bring its plot window into focus.",
            )
            return

        am = getattr(sig, "axes_manager", None)
        if am is None:
            QMessageBox.warning(self, "Elemental Mapping", "Selected signal has no axes_manager.")
            return

        sig_dim = am.signal_dimension
        nav_dim = am.navigation_dimension

        if sig_dim != 1:
            QMessageBox.warning(
                self,
                "Elemental Mapping",
                f"Elemental mapping requires a Signal1D (1-D signal axis).\n\n"
                f"The selected signal has a {sig_dim}-D signal axis.\n"
                f"Type: {type(sig).__name__}",
            )
            return

        if nav_dim < 1:
            QMessageBox.warning(
                self,
                "Elemental Mapping",
                "Elemental mapping requires at least one navigation dimension.\n\n"
                "The selected signal has no navigation axes (it is a single spectrum).\n"
                "Load or select a spectrum image or line-scan instead.",
            )
            return

        title = f"Elemental Map — {get_signal_title(sig)}"
        self.viewer.add_elemental_map(sig, title)
        self.statusBar().showMessage(f"Opened elemental map for: {get_signal_title(sig)}")

    def _retract_background(self):
        """Open an interactive background-retraction panel for the active Signal1D."""
        sig = self._current_transform_signal()

        if sig is None:
            subs = self.viewer.desktop.subWindowList()
            if not subs:
                QMessageBox.warning(
                    self,
                    "Retract Background",
                    "No signal is plotted.\n\n"
                    "Please plot a Signal1D (e.g. an EELS spectrum) first.",
                )
            else:
                QMessageBox.warning(
                    self,
                    "Retract Background",
                    "No signal is selected.\n\n"
                    "Select a signal in the data list or bring its plot window into focus.",
                )
            return

        am = getattr(sig, "axes_manager", None)
        if am is None:
            QMessageBox.warning(self, "Retract Background", "Selected signal has no axes_manager.")
            return

        if am.signal_dimension != 1:
            QMessageBox.warning(
                self,
                "Retract Background",
                f"Background retraction requires a Signal1D (1-D signal axis).\n\n"
                f"The selected signal has a {am.signal_dimension}-D signal axis.\n"
                f"Type: {type(sig).__name__}",
            )
            return

        title = f"Retract Background — {get_signal_title(sig)}"
        self.viewer.add_retract_background(sig, title)
        self.statusBar().showMessage(f"Opened background retraction panel for: {get_signal_title(sig)}")

    def _deconvolution(self):
        """Open the interactive EELS deconvolution panel."""
        sig = self._current_transform_signal()
        if sig is None:
            QMessageBox.warning(
                self, "Deconvolution",
                "No signal is selected.\n\nSelect a Signal1D in the data list first.",
            )
            return
        am = getattr(sig, "axes_manager", None)
        if am is None or am.signal_dimension != 1:
            QMessageBox.warning(
                self, "Deconvolution",
                "Deconvolution requires a 1-D signal (Signal1D).",
            )
            return

        # Collect all other loaded signals as reference candidates
        available_signals = []
        seen = set()
        for _ds_id, ds in self.data_list.datasets.items():
            ds_name = ds.get("name", "")
            for s in ds.get("signals", []):
                sid = id(s)
                if sid in seen or sid == id(sig):
                    continue
                seen.add(sid)
                try:
                    s_title = s.metadata.General.title or ds_name
                except Exception:
                    s_title = ds_name
                label = f"{s_title}  [{type(s).__name__}]"
                available_signals.append((label, s))

        if not available_signals:
            QMessageBox.warning(
                self, "Deconvolution",
                "No other signals are loaded to use as reference "
                "(ZLP / low-loss / PSF).\n\nLoad the reference signal first.",
            )
            return

        title = f"Deconvolution \u2014 {get_signal_title(sig)}"
        self.viewer.add_deconvolution_panel(sig, available_signals, title)
        self.statusBar().showMessage(
            f"Opened deconvolution panel for: {get_signal_title(sig)}"
        )

    def _on_deconvolution_done(self, result_signal, out_name: str):
        """Insert a deconvolved signal as a new dataset in the data list."""
        if result_signal is None:
            QMessageBox.warning(self, "Deconvolution", "No result signal received.")
            return
        title = (out_name or "signal (deconvolved)").strip()
        try:
            result_signal.metadata.General.title = title
        except Exception:
            pass
        self._add_dataset_undoable(title, [result_signal])
        self.statusBar().showMessage(
            f"Deconvolution: exported \u2018{title}\u2019 to data list."
        )

    def _on_background_removed(self, result_signal, out_name: str):
        """Insert background-removed signal as a new dataset in the data list."""
        if result_signal is None:
            QMessageBox.warning(self, "Retract Background", "No result signal received.")
            return
        title = (out_name or "signal (bg removed)").strip()
        try:
            result_signal.metadata.General.title = title
        except Exception:
            pass
        self._add_dataset_undoable(title, [result_signal])
        self.statusBar().showMessage(f"Retract background: exported \u2018{title}\u2019 to data list.")

    def _on_elemental_map_exported(self, map_signal, map_title: str):
        """Insert exported elemental map as a new Signal2D dataset in data list."""
        if map_signal is None:
            QMessageBox.warning(self, "Export Elemental Map", "No map signal received.")
            return

        title = (map_title or "Elemental Map").strip()
        try:
            map_signal.metadata.General.title = title
        except Exception:
            pass

        dataset_name = f"{title}"
        self._add_dataset_undoable(dataset_name, [map_signal])
        self.statusBar().showMessage(f"Exported elemental map to data list: {title}")

    def _on_cropped_signals_exported(self, cropped_signals, dataset_name: str):
        """Insert cropped signals as one dataset into the data list."""
        if not cropped_signals:
            QMessageBox.warning(self, "Crop signals", "No cropped signals received.")
            return

        name = (dataset_name or "Crops").strip()
        if "(N=" not in name:
            name = f"{name} (N={len(cropped_signals)})"

        self._add_dataset_undoable(name, list(cropped_signals))
        self.statusBar().showMessage(
            f"Crop signals: exported {len(cropped_signals)} crop(s) to dataset '{name}'."
        )

    def _mark_signals_as_eels(self):
        """Set signal_type='EELS' on all signals selected in the tree,
        or fall back to the single active/cached signal if nothing is selected."""
        dl = self.data_list
        tw = dl.tree_widget

        # Collect all signal-kind items currently highlighted in the tree.
        signals = []
        for item in tw.selectedItems():
            try:
                if item.data(0, dl.ROLE_KIND) != "signal":
                    continue
                dataset_id = item.data(0, dl.ROLE_DATASET_ID)
                token = item.data(0, dl.ROLE_SIGNAL_TOKEN)
                sig = dl._resolve_signal(token, dataset_id)
                if sig is not None:
                    signals.append(sig)
            except Exception:
                continue

        # Fall back to the single active/cached signal.
        if not signals:
            sig = self._current_transform_signal()
            if sig is not None:
                signals = [sig]

        if not signals:
            QMessageBox.warning(
                self,
                "Mark as EELS signal",
                "No signal selected.\n"
                "Select one or more signals in the data list first, "
                "or activate a plotted signal.",
            )
            return

        failed = []
        for sig in signals:
            try:
                sig.set_signal_type("EELS")
            except Exception as e:
                title = get_signal_title(sig)
                failed.append(f"{title}: {e}")

        n_ok = len(signals) - len(failed)
        if failed:
            QMessageBox.warning(
                self,
                "Mark as EELS signal",
                f"{n_ok} signal(s) updated.\n"
                f"The following could not be converted:\n" + "\n".join(failed),
            )
        self.statusBar().showMessage(
            f"Set signal_type='EELS' on {n_ok} signal(s)."
        )

    # ── Settings ───────────────────────────────────────────────────────────────
    def _open_settings(self):
        """Open the settings dialog."""
        dialog = SettingsDialog(self.config, self)
        if dialog.exec_() == dialog.Accepted:
            # Update configuration with new settings
            settings = dialog.get_settings()
            for key, value in settings.items():
                self.config.set(key, value)
            
            # Save settings to file
            self.config.save_settings()
            
            # Refresh UI with new settings
            self._refresh_ui_style()
            self.statusBar().showMessage("Settings applied and saved.")
    # ── Functions menu actions ────────────────────────────────────────────
    def _sort_signals(self):
        """Sort and group only the currently selected dataset by frame."""
        try:
            ok, info = self.data_list.sort_current_dataset_by_frame()
            if not ok:
                QMessageBox.warning(self, "Sort Signals", info)
                return
            self.statusBar().showMessage(
                f"Grouped current dataset into {info} frame(s)."
            )
        except Exception as e:
            QMessageBox.critical(
                self, "Error Sorting Signals", f"Failed to sort current dataset:\n{str(e)}"
            )

    def _toggle_2d_roi(self):
        """Create or clear the shared 2D ROI across open image panels."""
        if self.viewer.has_shared_2d_roi():
            active, message = self.viewer.toggle_shared_2d_roi()
            self._update_roi_action(active)
            self.statusBar().showMessage(message)
            return

        default_size = 3
        if self.config:
            try:
                default_size = int(self.config.get("roi2d_initial_size_px", 3))
            except Exception:
                default_size = 3
        default_size = max(1, default_size)

        size_px, ok = QInputDialog.getInt(
            self,
            "Create 2D ROI",
            "Initial ROI size (pixels):",
            value=default_size,
            min=1,
            max=4096,
            step=1,
        )
        if not ok:
            self.statusBar().showMessage("Create 2D ROI cancelled.")
            return

        if self.config:
            self.config.set("roi2d_initial_size_px", int(size_px))
            self.config.save_settings()

        active, message = self.viewer.toggle_shared_2d_roi(initial_size_px=int(size_px))
        self._update_roi_action(active)
        self.statusBar().showMessage(message)

    def _update_roi_action(self, active: bool):
        """Reflect current ROI state in the Functions menu action."""
        if not hasattr(self, "act_create_roi"):
            return
        if hasattr(self, "act_export_roi"):
            self.act_export_roi.setEnabled(active)

        if active:
            self.act_create_roi.setText("Clear &2D ROI")
            self.act_create_roi.setStatusTip("Clear the synchronized 2D ROI from all open image panels")
        else:
            self.act_create_roi.setText("Create &2D ROI")
            self.act_create_roi.setStatusTip("Create synchronized 2D ROI across open image panels")

    def _make_cropped_signal(self, roi, source_signal, axes):
        """Crop source_signal directly from a shared HyperSpy RectangularROI."""
        if roi is None or source_signal is None:
            return None

        if axes is not None:
            cropped = roi(source_signal, axes=axes).copy()
        else:
            cropped = roi(source_signal).copy()

        try:
            src_title = get_signal_title(source_signal)
            cropped.metadata.General.title = f"ROI crop — {src_title}"
        except Exception:
            pass

        try:
            sig_type = source_signal.metadata.Signal.signal_type
            if sig_type:
                cropped.set_signal_type(sig_type)
        except Exception:
            pass
        return cropped

    def _export_roi_crops(self):
        """Export current shared HyperSpy ROI crops for corresponding signals into a new dataset."""
        payload = self.viewer.get_shared_2d_roi_payload()
        if not isinstance(payload, dict):
            QMessageBox.warning(self, "ROI Export", "Create a 2D ROI first.")
            return

        roi = payload.get("roi")
        targets = payload.get("targets") or []
        if roi is None or not targets:
            QMessageBox.warning(self, "ROI Export", "No ROI/signal data available for export.")
            return

        crops = []
        failed = []
        for target in targets:
            sig = target.get("signal")
            axes = target.get("axes")
            try:
                cropped = self._make_cropped_signal(roi, sig, axes)
                if cropped is not None:
                    crops.append(cropped)
                else:
                    failed.append(get_signal_title(sig))
            except Exception:
                failed.append(get_signal_title(sig))

        if not crops:
            QMessageBox.warning(self, "ROI Export", "No compatible signals were available for ROI export.")
            return

        # Check whether the user previously chose to skip the dialog.
        skip = False
        saved_ws_id = None
        if self.config:
            skip = bool(self.config.get("roi_export_skip_dialog", False))
            saved_ws_id = self.config.get("roi_export_workspace_id")

        # Validate saved workspace still exists before using skip.
        if skip and saved_ws_id:
            existing_ids = {ws["id"] for ws in self.data_list.workspaces}
            if saved_ws_id not in existing_ids:
                skip = False  # workspace was removed; must ask again
        else:
            skip = False

        if skip:
            target_workspace_id = saved_ws_id
            timestamp = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
            dataset_name = f"ROI Crops {timestamp}"
        else:
            dlg = _RoiExportDialog(self, self.data_list.workspaces, saved_ws_id)
            if dlg.exec_() != QDialog.Accepted:
                return
            target_workspace_id = dlg.workspace_id()
            if target_workspace_id is None:
                return
            dataset_name = dlg.dataset_name()

            if self.config:
                self.config.set("roi_export_skip_dialog", dlg.skip_next_time())
                if dlg.skip_next_time():
                    self.config.set("roi_export_workspace_id", target_workspace_id)
                self.config.save_settings()

        self.data_list._set_active_workspace(target_workspace_id)
        self._add_dataset_undoable(dataset_name, crops)

        msg = f"Exported {len(crops)} ROI-cropped signal(s) → '{dataset_name}'."
        if failed:
            msg += f"  Skipped {len(failed)} incompatible signal(s)."
        self.statusBar().showMessage(msg)
    # ── Multi-ROI actions ───────────────────────────────────────────────

    def _open_multi_roi_panel(self):
        """Show (or raise) the multi-ROI management panel."""
        if self._multi_roi_panel is None or not self._multi_roi_panel.isVisible():
            self._multi_roi_panel = _MultiRoiPanel(self, self.viewer)
            self._multi_roi_panel.show()
        else:
            self._multi_roi_panel.raise_()
            self._multi_roi_panel.activateWindow()

    def _export_multi_roi_crops(self):
        """Export crops for every numbered multi-ROI into a new dataset."""
        payload = self.viewer.get_multi_roi_payload()
        if not payload:
            QMessageBox.warning(
                self, "Export Multiple ROI Crops",
                "No multiple ROIs active.  Use Functions \u2192 Create Multiple 2D ROIs\u2026 first."
            )
            return

        # Compute crops for each ROI index across its targets.
        all_crops = {}   # roi_index -> list of cropped signals
        all_failed = []
        for entry in payload:
            roi_index = entry["index"]
            roi = entry["roi"]
            crops_for_roi = []
            for target in entry["targets"]:
                sig = target.get("signal")
                axes = target.get("axes")
                try:
                    cropped = self._make_cropped_signal(roi, sig, axes)
                    if cropped is not None:
                        # Tag with ROI number in title
                        try:
                            src_title = get_signal_title(sig)
                            cropped.metadata.General.title = f"ROI#{roi_index} crop \u2014 {src_title}"
                        except Exception:
                            pass
                        crops_for_roi.append(cropped)
                    else:
                        all_failed.append(f"#{roi_index}/{get_signal_title(sig)}")
                except Exception:
                    all_failed.append(f"#{roi_index}/{get_signal_title(sig)}")
            all_crops[roi_index] = crops_for_roi

        total = sum(len(v) for v in all_crops.values())
        if total == 0:
            QMessageBox.warning(self, "Export Multiple ROI Crops",
                                "No compatible signals were available for export.")
            return

        # Choose destination workspace.
        saved_ws_id = self.config.get("roi_export_workspace_id") if self.config else None
        dlg = _RoiExportDialog(self, self.data_list.workspaces, saved_ws_id)
        dlg.setWindowTitle("Export Multiple 2D ROI Crops")
        # Override suggested name
        timestamp = datetime.now().strftime("%Y-%m-%d %H-%M-%S")
        dlg._name_edit.setText(f"Multi-ROI Crops {timestamp}")
        if dlg.exec_() != QDialog.Accepted:
            return
        target_workspace_id = dlg.workspace_id()
        if target_workspace_id is None:
            return
        base_name = dlg.dataset_name()

        if self.config and dlg.skip_next_time():
            self.config.set("roi_export_workspace_id", target_workspace_id)
            self.config.save_settings()

        self.data_list._set_active_workspace(target_workspace_id)

        # Create one dataset per ROI index: "<base_name> — ROI #1", etc.
        created = 0
        created_dataset_ids = []
        self._undo_recording = False
        try:
            for roi_index, crops in sorted(all_crops.items()):
                if not crops:
                    continue
                dataset_name = f"{base_name} \u2014 ROI #{roi_index}"
                ds_id = self.data_list.add_dataset_to_active_workspace(dataset_name, crops)
                created_dataset_ids.append(ds_id)
                created += 1
        finally:
            self._undo_recording = True

        if created_dataset_ids:
            _ids = list(created_dataset_ids)
            label = f"Multi-ROI export ({created} dataset(s))"

            def _undo_multi():
                for did in _ids:
                    self.data_list.remove_dataset_by_id(did)

            self._undo_stack.push(_undo_multi, lambda: None, label)
            self._refresh_undo_actions()

        msg = (f"Exported {total} cropped signal(s) across {created} dataset(s) "
               f"(one per ROI number).")
        if all_failed:
            msg += f"  Skipped {len(all_failed)} incompatible signal(s)."
        self.statusBar().showMessage(msg)
    def _sanitize_filename(self, title: str, max_len: int = 80) -> str:
        import re
        name = re.sub(r"[^A-Za-z0-9_.-]", "_", title)
        if len(name) > max_len:
            name = name[:max_len].rstrip("_")
        return name

    def _save_filters(self) -> str:
        filters = [label for label, _ext in self.SAVE_FORMATS]
        all_patterns = []
        for label, _ext in self.SAVE_FORMATS:
            start = label.find("(")
            end = label.rfind(")")
            if start != -1 and end != -1 and end > start:
                all_patterns.extend(label[start + 1:end].split())
        return "All supported writable formats ({});;{}".format(
            " ".join(all_patterns),
            ";;".join(filters),
        )

    def _load_filters(self) -> str:
        return "{};;All Files (*)".format(
            ";;".join(self.LOAD_FORMATS),
        )

    def _default_extension_for_filter(self, selected_filter: str) -> str:
        for label, extension in self.SAVE_FORMATS:
            if selected_filter == label:
                return extension
        return ".hspy"

    def _ensure_extension(self, path: str, selected_filter: str) -> str:
        root, ext = os.path.splitext(path)
        if ext:
            return path
        return root + self._default_extension_for_filter(selected_filter)

    def _select_batch_save_format(self):
        labels = [label for label, _ext in self.SAVE_FORMATS]
        selected, ok = QInputDialog.getItem(
            self,
            "Select Output Format",
            "Save selected signals as:",
            labels,
            0,
            False,
        )
        if not ok or not selected:
            return None, None
        return selected, self._default_extension_for_filter(selected)

    def _count_datasets_for_signals(self, signals: list) -> int:
        """Count how many datasets contain the selected signal objects."""
        if not signals:
            return 0

        target_ids = {id(sig) for sig in signals}
        dataset_ids = set()
        for dataset_id, dataset in self.data_list.datasets.items():
            for sig in dataset.get("signals", []):
                if id(sig) in target_ids:
                    dataset_ids.add(dataset_id)
                    break
        return len(dataset_ids)

    def _select_multi_save_mode(self, signals: list):
        """Ask whether multiple signals should be saved together or separately."""
        dataset_count = self._count_datasets_for_signals(signals)

        msg = QMessageBox(self)
        msg.setWindowTitle("Save Multiple Signals")
        msg.setText("Choose how to save the selected signals:")
        msg.setInformativeText(
            f"Selected {len(signals)} signal(s) from {dataset_count} dataset(s)."
        )
        btn_pack = msg.addButton("Single .eelspack container", QMessageBox.ActionRole)
        btn_separate = msg.addButton("Multiple files", QMessageBox.ActionRole)
        msg.addButton(QMessageBox.Cancel)
        msg.exec_()

        clicked = msg.clickedButton()
        if clicked == btn_pack:
            return "pack"
        if clicked == btn_separate:
            return "separate"
        return None

    def _is_mixed_signal_types(self, signals: list) -> bool:
        classes = {type(sig).__name__ for sig in signals}
        return len(classes) > 1

    def _build_signal_context_entries(self, signals: list) -> list:
        """Build per-signal source metadata for .eelspack manifest."""
        context_by_id = {}

        workspace_name_by_id = {}
        for ws in self.data_list.workspaces:
            workspace_name_by_id[ws.get("id")] = ws.get("name") or ""

        # Collect workspace order (index in workspace list).
        ws_order_by_id = {}
        for ws_idx, ws in enumerate(self.data_list.workspaces):
            ws_order_by_id[ws.get("id")] = ws_idx

        for dataset in self.data_list.datasets.values():
            ws_id = dataset.get("workspace_id")
            ws_name = workspace_name_by_id.get(ws_id, "")
            ws_order = ws_order_by_id.get(ws_id, 0)
            ds_name = dataset.get("name") or ""
            # dataset_order = its position among datasets in that workspace.
            ds_ws = next(
                (ws for ws in self.data_list.workspaces if ws.get("id") == ws_id),
                None,
            )
            ds_ids_in_ws = [d["id"] for d in (ds_ws.get("datasets") or [])] if ds_ws else []
            ds_order = ds_ids_in_ws.index(dataset["id"]) if dataset["id"] in ds_ids_in_ws else 0

            for ds_sig_idx, sig in enumerate(dataset.get("signals", [])):
                sid = id(sig)
                if sid not in context_by_id:
                    context_by_id[sid] = {
                        "source_workspace": ws_name,
                        "source_dataset": ds_name,
                        "workspace_order": ws_order,
                        "dataset_order": ds_order,
                        "dataset_signal_order": ds_sig_idx,
                    }

        out = []
        for sig in signals:
            entry = dict(context_by_id.get(id(sig), {}))
            entry["title"] = get_signal_title(sig)
            entry["signal_class"] = type(sig).__name__
            out.append(entry)
        return out

    def _confirm_overwrite_source(self, sig, save_path: str) -> bool:
        """Return True if the save should proceed.

        Shows a confirmation dialog when *save_path* would overwrite the
        original file the signal was loaded from.  For any other path the
        method returns True immediately without showing a dialog.
        """
        src = getattr(sig, "_ev_source_path", None)
        if not src:
            return True
        try:
            if os.path.abspath(save_path) != os.path.abspath(src):
                return True
        except Exception:
            return True

        reply = QMessageBox.warning(
            self,
            "Overwrite Source File?",
            f"The save path matches the original source file:\n\n{src}\n\n"
            "Saving here will permanently overwrite your experimental data.\n"
            "Are you sure you want to continue?",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        return reply == QMessageBox.Yes

    def _save_single_signal(self, sig) -> bool:
        title = get_signal_title(sig)
        default_name = self._sanitize_filename(title)
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            f"Save Signal - {title}",
            default_name,
            self._save_filters(),
        )
        if not path:
            return False

        path = self._ensure_extension(path, selected_filter)
        # Warn if the chosen path would overwrite the signal's source file.
        if not self._confirm_overwrite_source(sig, path):
            return False
        try:
            sig.save(path, overwrite=True)
        except Exception as e:
            fmt = selected_filter or os.path.splitext(path)[1] or "selected format"
            QMessageBox.warning(
                self,
                "Save Error",
                f"{title} cannot be saved in {fmt}.\n\nDetails:\n{e}",
            )
            return False
        self.statusBar().showMessage(f"Saved signal to {path}")
        return True

    def _save_multiple_signals(self, signals: list) -> int:
        mode = self._select_multi_save_mode(signals)
        if mode is None:
            return 0
        if mode == "pack":
            return self._save_multiple_signals_eelspack(signals)

        return self._save_multiple_signals_separate_files(signals)

    def _save_multiple_signals_eelspack(self, signals: list) -> int:
        default_name = "signals_batch.eelspack"
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Multiple Signals (.eelspack)",
            default_name,
            "EELS Pack (*.eelspack)",
        )
        if not path:
            return 0

        if not path.lower().endswith(".eelspack"):
            path += ".eelspack"

        entries = self._build_signal_context_entries(signals)
        try:
            export_eelspack(
                path,
                signals,
                entries=entries,
                pack_name=os.path.splitext(os.path.basename(path))[0],
            )
        except Exception as e:
            QMessageBox.warning(
                self,
                "Save Error",
                f"Could not save .eelspack container.\n\nDetails:\n{e}",
            )
            return 0

        self.statusBar().showMessage(
            f"Saved {len(signals)} signal(s) into EELS pack: {path}"
        )
        return len(signals)

    def _save_multiple_signals_single_file(self, signals: list) -> int:
        default_name = "signals_batch"
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Save Multiple Signals (Single File)",
            default_name,
            self._save_filters(),
        )
        if not path:
            return 0

        path = self._ensure_extension(path, selected_filter)
        try:
            # Save a collection of signals into one container file.
            # HyperSpy exposes this via hyperspy.io.save, not hyperspy.api.save.
            from hyperspy.io import save as hs_save
            hs_save(path, signals, overwrite=True)
        except Exception as e:
            fmt = selected_filter or os.path.splitext(path)[1] or "selected format"
            QMessageBox.warning(
                self,
                "Save Error",
                "Cannot save the selected signals in a single file with "
                f"{fmt}.\n"
                "Try .hspy/.h5 for single-file datasets, or choose Separate files.\n\n"
                f"Details:\n{e}",
            )
            return 0

        self.statusBar().showMessage(
            f"Saved {len(signals)} signal(s) into one file: {path}"
        )
        return len(signals)

    def _save_multiple_signals_separate_files(self, signals: list) -> int:
        directory = QFileDialog.getExistingDirectory(self, "Select folder to save signals")
        if not directory:
            return 0

        selected_filter, extension = self._select_batch_save_format()
        if not selected_filter or not extension:
            return 0

        saved = 0
        failed = []
        skipped = []
        for sig in signals:
            name = self._sanitize_filename(get_signal_title(sig))
            path = os.path.join(directory, f"{name}{extension}")
            # Check for accidental overwrite of the original source file.
            src = getattr(sig, "_ev_source_path", None)
            if src and os.path.abspath(path) == os.path.abspath(src):
                skipped.append(get_signal_title(sig))
                continue
            try:
                sig.save(path, overwrite=True)
                saved += 1
            except Exception as e:
                failed.append(f"{get_signal_title(sig)} cannot be saved in {selected_filter}. ({e})")

        if skipped:
            QMessageBox.warning(
                self,
                "Source File Protection",
                "The following signal(s) were NOT saved because the computed output path "
                "matched their original source file.\n\n"
                "Use 'Save signal' (single-signal save) and choose a different filename "
                "if you intentionally want to overwrite the source:\n\n"
                + "\n".join(skipped[:10]),
            )

        if failed:
            QMessageBox.warning(
                self,
                "Save Error",
                "Some signals could not be saved:\n\n" + "\n".join(failed[:10]),
            )

        self.statusBar().showMessage(
            f"Saved {saved} signal(s) to {directory} as {selected_filter}"
        )
        return saved

    def _format_signal_metadata(self, sig) -> str:
        try:
            info = str(sig)
        except Exception:
            info = repr(sig)
        try:
            meta = str(sig.metadata)
            info += "\n\nMetadata:\n" + meta
        except Exception:
            pass
        return info

    def _format_axes_info(self, sig) -> str:
        try:
            lines = []
            am = sig.axes_manager
            lines.append("Navigation axes:")
            for ax in getattr(am, 'navigation_axes', []):
                try:
                    lines.append(f" - {getattr(ax,'name',ax)}: size={getattr(ax,'size',None)}, scale={getattr(ax,'scale',None)}, offset={getattr(ax,'offset',None)}, units={getattr(ax,'units',None)}")
                except Exception:
                    lines.append(f" - {ax}")
            lines.append("\nSignal axes:")
            for ax in getattr(am, 'signal_axes', []):
                try:
                    lines.append(f" - {getattr(ax,'name',ax)}: size={getattr(ax,'size',None)}, scale={getattr(ax,'scale',None)}, offset={getattr(ax,'offset',None)}, units={getattr(ax,'units',None)}")
                except Exception:
                    lines.append(f" - {ax}")
            return "\n".join(lines)
        except Exception:
            try:
                return str(sig.axes_manager)
            except Exception:
                return "<axes info unavailable>"

    @staticmethod
    def _contains_signal_identity(signal_list, target_signal) -> bool:
        """Return True if target_signal is the same object as any item in signal_list.

        HyperSpy signal equality can trigger data-aware operations and may raise
        dimension errors, so membership checks must use identity (`is`) instead.
        """
        if target_signal is None:
            return False
        try:
            return any(sig is target_signal for sig in signal_list)
        except Exception:
            return False

    def _handle_context_action(self, action: str, signals: list):
        """Handle context menu actions emitted by the data list.

        Actions: 'plot', 'metadata', 'axes', 'save', 'remove', 'close_dataset', 'close_workspace'
        """
        if action in ('plot', 'metadata', 'axes', 'save', 'remove') and not signals:
            return

        if action == 'plot':
            if len(signals) > 10:
                reply = QMessageBox.question(
                    self,
                    "Plot Many Signals",
                    f"You are about to open {len(signals)} plot windows. Continue?",
                    QMessageBox.Yes | QMessageBox.No,
                )
                if reply != QMessageBox.Yes:
                    return

            self.viewer.plot_signals(signals)
            self.statusBar().showMessage(
                f"Opened {len(signals)} plot window(s)."
            )
            return

        if action == 'close_dataset':
            dataset_name = self.data_list.get_current_dataset_name()
            if not dataset_name:
                QMessageBox.warning(self, "Close Dataset", "Please select a dataset first.")
                return

            reply = QMessageBox.question(
                self,
                "Close Dataset",
                f"Close dataset '{dataset_name}' and release its signals from memory?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

            # Capture dataset info before closing (for undo)
            _dataset_for_undo = self.data_list._get_current_dataset()
            _saved_ws_id = _dataset_for_undo["workspace_id"] if _dataset_for_undo else self.data_list.active_workspace_id
            _saved_ds_signals = list(_dataset_for_undo["signals"]) if _dataset_for_undo else []

            closed_name, removed_signals = self.data_list.close_current_dataset()
            if not closed_name:
                return

            if self._contains_signal_identity(removed_signals, getattr(self.viewer, 'current_signal', None)):
                self.viewer.clear_display()
            self.statusBar().showMessage(
                f"Closed dataset '{closed_name}' ({len(removed_signals)} signal(s) released from memory)."
            )

            # Push undo
            saved_ws_id = _saved_ws_id
            saved_signals = _saved_ds_signals
            saved_name = closed_name

            def _undo_close_ds():
                prev_ws = self.data_list.active_workspace_id
                self.data_list._set_active_workspace(saved_ws_id)
                self.data_list.add_dataset_to_active_workspace(saved_name, saved_signals)
                self.data_list._set_active_workspace(prev_ws)

            self._undo_stack.push(_undo_close_ds, lambda: None, f"Close '{saved_name}'")
            self._refresh_undo_actions()
            return

        if action == 'close_workspace':
            workspace_name = self.data_list.get_active_workspace_name()
            if not workspace_name:
                QMessageBox.warning(self, "Close Workspace", "Please select a workspace first.")
                return

            reply = QMessageBox.question(
                self,
                "Close Workspace",
                f"Close workspace '{workspace_name}' and release all datasets/signals from memory?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

            # Capture workspace structure before closing (for undo)
            ws = self.data_list._get_workspace(self.data_list.active_workspace_id)
            _saved_ws_datasets = [
                {"name": ds["name"], "signals": list(ds["signals"])}
                for ds in ws["datasets"]
            ] if ws else []

            closed_name, removed_signals, dataset_count = self.data_list.close_active_workspace()
            if not closed_name:
                return

            if self._contains_signal_identity(removed_signals, getattr(self.viewer, 'current_signal', None)):
                self.viewer.clear_display()
            self.statusBar().showMessage(
                f"Closed workspace '{closed_name}' ({dataset_count} dataset(s), {len(removed_signals)} signal(s) released from memory)."
            )

            # Push undo (restores workspace with all original datasets)
            saved_ws_name = closed_name
            saved_datasets = list(_saved_ws_datasets)  # captured below

            def _undo_close_ws():
                new_ws_id = self.data_list.add_workspace(saved_ws_name)
                self.data_list._set_active_workspace(new_ws_id)
                for ds_info in saved_datasets:
                    self.data_list.add_dataset_to_active_workspace(ds_info["name"], ds_info["signals"])

            self._undo_stack.push(_undo_close_ws, lambda: None, f"Close workspace '{saved_ws_name}'")
            self._refresh_undo_actions()
            return

        if action == 'metadata':
            for sig in signals:
                title = get_signal_title(sig)
                content = self._format_signal_metadata(sig)
                self.viewer.add_info_panel(f"Metadata — {title}", content)
            self.statusBar().showMessage(f"Opened metadata for {len(signals)} signal(s)")
            return

        if action == 'axes':
            if len(signals) == 1:
                # Single signal: normal editor
                sig = signals[0]
                title = get_signal_title(sig)
                self.viewer.add_axes_editor(f"Axes — {title}", sig)
            else:
                # Multiple signals: first signal gets batch-apply option
                first_sig = signals[0]
                other_sigs = signals[1:]
                title = get_signal_title(first_sig)
                self.viewer.add_axes_editor(f"Axes — {title} (+ {len(other_sigs)} more)", first_sig, apply_to_signals=other_sigs)
            self.statusBar().showMessage(f"Opened axes editor for {len(signals)} signal(s)")
            return

        if action == 'save':
            if len(signals) == 1:
                self._save_single_signal(signals[0])
            else:
                self._save_multiple_signals(signals)
            return

        if action == 'remove':
            # Ask before removing multiple signals
            if len(signals) > 1:
                reply = QMessageBox.question(self, "Remove Signals", f"Remove {len(signals)} signals from the list?", QMessageBox.Yes | QMessageBox.No)
                if reply != QMessageBox.Yes:
                    return

            # Capture which dataset each signal belongs to (for undo)
            signal_ids = {id(s) for s in signals}
            saved_locations = {}
            for ds_id, ds in self.data_list.datasets.items():
                matched = [s for s in ds["signals"] if id(s) in signal_ids]
                if matched:
                    saved_locations[ds_id] = list(matched)

            # Remove from data_list and clear viewer if needed
            self.data_list.remove_signals(signals)
            if self._contains_signal_identity(signals, getattr(self.viewer, 'current_signal', None)):
                self.viewer.clear_display()
            self.statusBar().showMessage(f"Removed {len(signals)} signal(s) from list")

            # Push undo
            _locs = dict(saved_locations)

            def _undo_remove():
                for did, sigs in _locs.items():
                    self.data_list.restore_signals_to_dataset(did, sigs)

            self._undo_stack.push(_undo_remove, lambda: None, f"Remove {len(signals)} signal(s)")
            self._refresh_undo_actions()
            return
    # ── About ─────────────────────────────────────────────────────────────────
    def _show_about(self):
        QMessageBox.about(
            self,
            "About EMDataStudio",
            "<b>EMDataStudio v1.0</b><br>"
            "HyperSpy-based electron microscopy data visualizer.<br><br>"
            "Built for HAADF-STEM, DF4, and EELS Spectrum Image data.<br>"
            "TU Darmstadt — Advanced Electron Microscopy Division",
        )


# ── Background loader (module-level so it can be imported cleanly) ─────────
class LoadThread(QThread):
    loaded = pyqtSignal(list)
    error  = pyqtSignal(str)

    def __init__(self, filepath):
        super().__init__()
        self.filepath = filepath

    def run(self):
        try:
            signals = load_hyperspy_file(self.filepath)
            self.loaded.emit(signals)
        except Exception as e:
            self.error.emit(str(e))
