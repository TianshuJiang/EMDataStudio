"""
data_list_widget.py
Left-panel widget that shows workspaces, datasets, and signals.
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QLabel, QMenu, QAbstractItemView, QToolButton,
    QDialog, QDialogButtonBox, QComboBox, QLineEdit, QFormLayout,
    QInputDialog, QMessageBox, QCheckBox,
)
from PyQt5.QtCore import pyqtSignal, Qt
from PyQt5.QtGui import QColor, QFont, QBrush
import gc
import copy

from ..data_manager import (
    classify_signal,
    get_signal_title,
    get_dimensions_str,
    extract_frame_number,
    sort_and_group_signals,
    create_hyperspy_signal,
)


# ── Colour coding per signal type ──────────────────────────────────────────
TYPE_COLORS = {
    "Signal2D":     "#2e7d32",   # green  — HAADF / DF4 images
    "EELSSpectrum": "#1565c0",   # blue   — EELS spectrum images
    "EDSSpectrum":  "#6a1b9a",   # purple — EDS
    "Signal1D":     "#e65100",   # orange — 1-D signals
}


# ── Drag-drop enabled tree ──────────────────────────────────────────────────
class _TreeWidget(QTreeWidget):
    """QTreeWidget subclass that emits a signal when items are dropped."""

    items_dropped = pyqtSignal(list, object)  # (list of dragged items, target item)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_items = []
        self._is_internal_drag = False
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        # InternalMove avoids Qt serializing item payloads into MIME data.
        # Our items store live HyperSpy objects, which are not safely picklable.
        self.setDragDropMode(QAbstractItemView.InternalMove)

    def startDrag(self, supported_actions):
        self._is_internal_drag = True
        self._drag_items = list(self.selectedItems())
        super().startDrag(supported_actions)

    def dropEvent(self, event):
        if not self._is_internal_drag:
            event.ignore()
            return

        target_item = self.itemAt(event.pos())
        dragged = list(self._drag_items)
        self._drag_items = []
        self._is_internal_drag = False

        container = self.parent()
        if (
            target_item is None
            or not dragged
            or (
                hasattr(container, "_is_valid_drop")
                and not container._is_valid_drop(dragged, target_item)
            )
        ):
            event.ignore()
            return

        event.accept()          # prevent Qt's own tree restructuring
        self.items_dropped.emit(dragged, target_item)

    def dropMimeData(self, parent, index, data, action):
        # Block base-class MIME deserialization path (which may pickle payloads).
        return False


# ── Create signal dialog ────────────────────────────────────────────────────
class CreateSignalDialog(QDialog):
    """Dialog for creating a new empty HyperSpy signal."""

    SIGNAL_TYPES = [
        ("BaseSignal",         "BaseSignal — generic (all dims as signal)"),
        ("Signal1D",           "Signal1D — 1-D signal (spectral)"),
        ("Signal2D",           "Signal2D — 2-D signal (image)"),
        ("EELSSpectrum",       "EELSSpectrum — EELS spectrum (eXSpy)"),
        ("EDSTEMSpectrum",     "EDSTEMSpectrum — EDS TEM spectrum (eXSpy)"),
        ("EDSSEMSpectrum",     "EDSSEMSpectrum — EDS SEM spectrum (eXSpy)"),
        ("EDSSpectrum",        "EDSSpectrum — generic EDS spectrum (eXSpy)"),
        ("DielectricFunction", "DielectricFunction — dielectric function (eXSpy)"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create Empty Signal")
        self.setMinimumWidth(480)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.type_combo = QComboBox()
        for type_name, label in self.SIGNAL_TYPES:
            self.type_combo.addItem(label, type_name)
        form.addRow("Signal type:", self.type_combo)

        self.name_edit = QLineEdit("New Signal")
        form.addRow("Signal name:", self.name_edit)

        self.shape_edit = QLineEdit("100, 100")
        self.shape_edit.setPlaceholderText("e.g. 100,100  or  10,10,1024")
        form.addRow("Shape (comma-separated):", self.shape_edit)

        layout.addLayout(form)

        hint = QLabel(
            "<small><i>Shape: navigation dim(s) then signal dim(s). "
            "Example EELS spectrum image 10×10 pixels, 1024 channels: "
            "<b>10, 10, 1024</b></i></small>"
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def get_type_name(self):
        return self.type_combo.currentData()

    def get_signal_name(self):
        return self.name_edit.text().strip() or "New Signal"

    def get_shape(self):
        try:
            parts = [p.strip() for p in self.shape_edit.text().split(",") if p.strip()]
            if not parts:
                return None
            return tuple(int(p) for p in parts)
        except ValueError:
            return None


# ── Main widget ─────────────────────────────────────────────────────────────
class DataListWidget(QWidget):
    """Tree widget for displaying workspaces, datasets, and signals."""

    signal_selected = pyqtSignal(object)  # Emits selected signal object
    context_action = pyqtSignal(str, list)  # action name, list of signals

    # ── Undo/Redo notification signals ─────────────────────────────────────
    workspace_added   = pyqtSignal(int, str)         # (ws_id, name)
    workspace_renamed = pyqtSignal(int, str, str)    # (ws_id, old_name, new_name)
    dataset_renamed   = pyqtSignal(int, str, str)    # (ds_id, old_name, new_name)
    signal_renamed    = pyqtSignal(object, str, str) # (sig_obj, old_name, new_name)
    signal_moved      = pyqtSignal(object, int, int) # (sig_obj, src_ds_id, tgt_ds_id)
    dataset_moved     = pyqtSignal(int, int, int)    # (ds_id, src_ws_id, tgt_ws_id)
    signals_copied    = pyqtSignal(list, int)        # (cloned_signals, tgt_ds_id)
    signal_created    = pyqtSignal(object, int)      # (sig_obj, ds_id)
    dataset_sorted    = pyqtSignal(int, list, bool)  # (ds_id, old_signals_copy, was_grouped)

    ROLE_KIND         = Qt.UserRole
    ROLE_SIGNAL_TOKEN = Qt.UserRole + 1
    ROLE_WORKSPACE_ID = Qt.UserRole + 2
    ROLE_DATASET_ID   = Qt.UserRole + 3

    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self.config = config

        self.workspaces = []
        self.datasets = {}
        self.active_workspace_id = None
        self.current_dataset_id = None
        self._workspace_counter = 0
        self._dataset_counter = 0
        self._signal_store = {}

        # Backward-compatible attribute used elsewhere in app.
        self.signals = []

        self._setup_ui()
        self.add_workspace("Workspace 1")

    # ── Styling ─────────────────────────────────────────────────────────────
    def update_styling(self, config):
        self.config = config
        self._apply_styling()

    def _apply_styling(self):
        if not self.config:
            return

        bg_color  = self.config.get("data_list_background", "#f8f8f8")
        text_color = self.config.get("data_list_text", "#000000")
        font_size  = self.config.get("data_list_font_size", 11)

        stylesheet = f"""
            QWidget#DataPanel {{
                background: {bg_color};
                border-right: 2px solid #ddd;
            }}
            QLabel#PanelTitle {{
                color: {text_color};
                font-size: {font_size + 2}px;
                font-weight: bold;
                padding: 6px 8px 4px 8px;
                border-bottom: 1px solid #ccc;
            }}
            QLabel#CountLabel {{
                color: #666;
                font-size: {font_size - 1}px;
                padding: 2px 8px 4px 8px;
            }}
            QTreeWidget {{
                background: {bg_color};
                color: {text_color};
                border: none;
                font-size: {font_size}px;
                outline: none;
            }}
            QTreeWidget::item {{
                padding: 6px 8px;
                border-bottom: 1px solid #eee;
            }}
            QTreeWidget::item:selected {{
                background: #007acc;
                color: white;
            }}
            QTreeWidget::item:hover {{
                background: #e8f4fd;
            }}
            QToolButton#AddWorkspaceButton {{
                border: 1px solid #bbb;
                border-radius: 10px;
                background: #f2f2f2;
                font-weight: bold;
                min-width: 20px;
                max-width: 20px;
                min-height: 20px;
                max-height: 20px;
            }}
            QToolButton#AddWorkspaceButton:hover {{
                background: #e5f3ff;
                border-color: #7da2c2;
            }}
        """
        self.setStyleSheet(stylesheet)

    # ── UI setup ─────────────────────────────────────────────────────────────
    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.setObjectName("DataPanel")

        title = QLabel("DATA SIGNALS")
        title.setObjectName("PanelTitle")
        layout.addWidget(title)

        self.count_label = QLabel("No dataset loaded")
        self.count_label.setObjectName("CountLabel")
        layout.addWidget(self.count_label)

        self.tree_widget = _TreeWidget(self)
        self.tree_widget.setHeaderHidden(True)
        self.tree_widget.setIndentation(14)
        self.tree_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree_widget.itemClicked.connect(self._on_item_clicked)
        self.tree_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree_widget.customContextMenuRequested.connect(self._show_context_menu)
        self.tree_widget.items_dropped.connect(self._on_items_dropped)
        layout.addWidget(self.tree_widget)

        bottom_row = QWidget()
        bottom_layout = QHBoxLayout(bottom_row)
        bottom_layout.setContentsMargins(8, 6, 8, 6)
        bottom_layout.setSpacing(6)

        self.workspace_hint = QLabel("Active: Workspace 1")
        self.workspace_hint.setObjectName("CountLabel")
        bottom_layout.addWidget(self.workspace_hint)
        bottom_layout.addStretch()

        btn_add_workspace = QToolButton()
        btn_add_workspace.setObjectName("AddWorkspaceButton")
        btn_add_workspace.setText("+")
        btn_add_workspace.setToolTip("Add workspace")
        btn_add_workspace.clicked.connect(self._on_add_workspace_clicked)
        bottom_layout.addWidget(btn_add_workspace)

        layout.addWidget(bottom_row)
        self._apply_styling()

    # ── Item-click handler ───────────────────────────────────────────────────
    def _on_item_clicked(self, item: QTreeWidgetItem):
        kind = item.data(0, self.ROLE_KIND)

        if kind == "workspace":
            workspace_id = item.data(0, self.ROLE_WORKSPACE_ID)
            self._set_active_workspace(workspace_id)
            return

        if kind in ("dataset", "frame", "signal"):
            workspace_id = item.data(0, self.ROLE_WORKSPACE_ID)
            if workspace_id is not None:
                self._set_active_workspace(workspace_id)
            dataset_id = item.data(0, self.ROLE_DATASET_ID)
            if dataset_id is not None:
                self.current_dataset_id = dataset_id
                self._sync_active_signals()

        if kind == "signal":
            token = item.data(0, self.ROLE_SIGNAL_TOKEN)
            sig = self._resolve_signal(token)
            if sig is not None:
                self.signal_selected.emit(sig)

    # ── Drag-drop handler ────────────────────────────────────────────────────
    def _on_items_dropped(self, dragged_items: list, target_item: QTreeWidgetItem):
        """Handle drop: move signals between datasets or datasets between workspaces."""
        target_kind = target_item.data(0, self.ROLE_KIND)
        drag_kinds = {it.data(0, self.ROLE_KIND) for it in dragged_items}

        # --- Moving signals to another dataset ---
        if "signal" in drag_kinds:
            target_dataset_id = None
            if target_kind in ("dataset", "signal", "frame"):
                target_dataset_id = target_item.data(0, self.ROLE_DATASET_ID)
            elif target_kind == "workspace":
                target_workspace_id = target_item.data(0, self.ROLE_WORKSPACE_ID)
                target_dataset_id = self._choose_drop_target_dataset_for_workspace(target_workspace_id)

            if target_dataset_id is None:
                return
            moved = 0
            for it in dragged_items:
                if it.data(0, self.ROLE_KIND) != "signal":
                    continue
                token = it.data(0, self.ROLE_SIGNAL_TOKEN)
                sig = self._resolve_signal(token)
                source_dataset_id = it.data(0, self.ROLE_DATASET_ID)
                if self._move_signal_to_dataset(sig, source_dataset_id, target_dataset_id):
                    moved += 1
            if moved:
                self._sync_active_signals()

        # --- Moving a dataset to another workspace ---
        elif "dataset" in drag_kinds:
            target_workspace_id = None
            if target_kind == "workspace":
                target_workspace_id = target_item.data(0, self.ROLE_WORKSPACE_ID)
            elif target_kind == "dataset":
                target_workspace_id = target_item.data(0, self.ROLE_WORKSPACE_ID)

            if target_workspace_id is None:
                return
            for it in dragged_items:
                if it.data(0, self.ROLE_KIND) != "dataset":
                    continue
                dataset_id = it.data(0, self.ROLE_DATASET_ID)
                self._move_dataset_to_workspace(dataset_id, target_workspace_id)

    def _is_valid_drop(self, dragged_items: list, target_item: QTreeWidgetItem) -> bool:
        """Validate allowed drag/drop combinations before accepting the event."""
        if not dragged_items or target_item is None:
            return False

        target_kind = target_item.data(0, self.ROLE_KIND)
        drag_kinds = {it.data(0, self.ROLE_KIND) for it in dragged_items}

        # Keep drag semantics simple: drag only one node kind at a time.
        if len(drag_kinds) != 1:
            return False

        if "signal" in drag_kinds:
            if target_kind not in ("dataset", "signal", "frame", "workspace"):
                return False

            # No-op drop: all dragged signals are dropped back into the same dataset.
            if target_kind in ("dataset", "signal", "frame"):
                target_dataset_id = target_item.data(0, self.ROLE_DATASET_ID)
                if target_dataset_id is None:
                    return False
                source_dataset_ids = {
                    it.data(0, self.ROLE_DATASET_ID)
                    for it in dragged_items
                    if it.data(0, self.ROLE_KIND) == "signal"
                }
                if source_dataset_ids and all(dsid == target_dataset_id for dsid in source_dataset_ids):
                    return False

            return True

        if "dataset" in drag_kinds:
            if target_kind not in ("workspace", "dataset"):
                return False

            # No-op drop: all dragged datasets already belong to target workspace.
            target_workspace_id = target_item.data(0, self.ROLE_WORKSPACE_ID)
            if target_workspace_id is None:
                return False
            source_workspace_ids = {
                it.data(0, self.ROLE_WORKSPACE_ID)
                for it in dragged_items
                if it.data(0, self.ROLE_KIND) == "dataset"
            }
            if source_workspace_ids and all(wsid == target_workspace_id for wsid in source_workspace_ids):
                return False

            return True

        return False

    def _create_empty_dataset_under_workspace(self, workspace_id, dataset_name="Dataset"):
        """Create and return a new empty dataset id under workspace_id."""
        ws = self._get_workspace(workspace_id)
        if ws is None:
            return None

        previous_workspace_id = self.active_workspace_id
        self._set_active_workspace(workspace_id)
        self.add_dataset_to_active_workspace(dataset_name, [])
        created_dataset_id = self.current_dataset_id

        # Keep user context stable by restoring previously active workspace highlight.
        if previous_workspace_id is not None and previous_workspace_id != workspace_id:
            self._set_active_workspace(previous_workspace_id)

        return created_dataset_id

    def _choose_drop_target_dataset_for_workspace(self, workspace_id):
        """Choose a target dataset when signals are dropped onto a workspace node."""
        ws = self._get_workspace(workspace_id)
        if ws is None:
            return None

        # If workspace has no dataset yet, create one directly.
        if not ws["datasets"]:
            return self._create_empty_dataset_under_workspace(workspace_id, "Dataset")

        ask_again = True
        saved_mode = "existing"
        if self.config is not None:
            ask_again = self.config.get("drop_signal_workspace_ask", True)
            saved_mode = self.config.get("drop_signal_workspace_mode", "existing")

        # If user disabled prompts, apply stored default directly.
        if not ask_again:
            if saved_mode == "new":
                return self._create_empty_dataset_under_workspace(workspace_id, "Dataset")
            return ws["datasets"][0]["id"]

        msg = QMessageBox(self)
        msg.setWindowTitle("Move Signals")
        msg.setText(f"Drop target is workspace '{ws['name']}'.")
        msg.setInformativeText("Choose destination for dropped signal(s):")
        btn_new = msg.addButton("Create New Dataset", QMessageBox.AcceptRole)
        btn_existing = msg.addButton("Choose Existing Dataset", QMessageBox.ActionRole)
        msg.addButton(QMessageBox.Cancel)

        dont_ask_checkbox = QCheckBox("Do not ask again later")
        msg.setCheckBox(dont_ask_checkbox)

        msg.exec_()
        clicked = msg.clickedButton()

        if clicked == btn_new:
            suggested = f"Dataset {self._dataset_counter + 1}"
            name, ok = QInputDialog.getText(
                self,
                "New Dataset",
                "Dataset name:",
                text=suggested,
            )
            if not ok:
                return None
            dataset_name = name.strip() or suggested
            dataset_id = self._create_empty_dataset_under_workspace(workspace_id, dataset_name)
            self._update_drop_workspace_pref(dont_ask_checkbox.isChecked(), "new")
            return dataset_id

        if clicked == btn_existing:
            labels = [f"{ds['name']} ({len(ds['signals'])} signals)" for ds in ws["datasets"]]
            selected, ok = QInputDialog.getItem(
                self,
                "Select Existing Dataset",
                "Move dropped signal(s) into:",
                labels,
                0,
                False,
            )
            if not ok or not selected:
                return None

            idx = labels.index(selected)
            dataset_id = ws["datasets"][idx]["id"]
            self._update_drop_workspace_pref(dont_ask_checkbox.isChecked(), "existing")
            return dataset_id

        return None

    def _update_drop_workspace_pref(self, dont_ask_again: bool, mode: str):
        """Persist signal->workspace drop prompt preference and default mode."""
        if self.config is None:
            return
        self.config.set("drop_signal_workspace_ask", not dont_ask_again)
        self.config.set("drop_signal_workspace_mode", mode)
        try:
            self.config.save_settings()
        except Exception:
            pass

    # ── Public API ─────────────────────────────────────────────────────────
    def load_signals(self, signals: list):
        """Backward-compatible API: load as a new dataset in active workspace."""
        self.add_dataset_to_active_workspace("Dataset", signals)

    def add_workspace(self, name=None):
        """Create a new top-level workspace node."""
        self._workspace_counter += 1
        workspace_name = name or f"Workspace {self._workspace_counter}"
        workspace_id   = self._workspace_counter

        item = QTreeWidgetItem([workspace_name])
        item.setData(0, self.ROLE_KIND, "workspace")
        item.setData(0, self.ROLE_WORKSPACE_ID, workspace_id)

        font = item.font(0)
        font.setBold(True)
        item.setFont(0, font)

        self.tree_widget.addTopLevelItem(item)
        self.workspaces.append({
            "id": workspace_id,
            "name": workspace_name,
            "item": item,
            "datasets": [],
        })

        self._set_active_workspace(workspace_id)
        self.tree_widget.expandItem(item)
        self._update_counts()
        self.workspace_added.emit(workspace_id, workspace_name)
        return workspace_id

    def add_dataset_to_active_workspace(self, dataset_name: str, signals: list):
        """Add a dataset under the currently selected workspace."""
        if not self.workspaces:
            self.add_workspace("Workspace 1")

        workspace    = self._get_workspace(self.active_workspace_id) or self.workspaces[0]
        workspace_id = workspace["id"]

        self._dataset_counter += 1
        dataset_id = self._dataset_counter

        base_name    = dataset_name or f"Dataset {dataset_id}"
        display_name = base_name
        existing_names = {d["name"] for d in workspace["datasets"]}
        suffix = 2
        while display_name in existing_names:
            display_name = f"{base_name} ({suffix})"
            suffix += 1

        dataset = {
            "id": dataset_id,
            "name": display_name,
            "workspace_id": workspace_id,
            "signals": list(signals),
            "grouped": False,
            "grouped_signals": None,
            "item": None,
        }
        self.datasets[dataset_id] = dataset
        workspace["datasets"].append(dataset)

        dataset_item = QTreeWidgetItem([f"{display_name}  ({len(dataset['signals'])})"])
        dataset_item.setData(0, self.ROLE_KIND, "dataset")
        dataset_item.setData(0, self.ROLE_WORKSPACE_ID, workspace_id)
        dataset_item.setData(0, self.ROLE_DATASET_ID, dataset_id)

        ws_item = workspace["item"]
        ws_item.addChild(dataset_item)
        dataset["item"] = dataset_item

        self.current_dataset_id = dataset_id
        self._set_active_workspace(workspace_id)
        self._render_dataset(dataset)
        self.tree_widget.expandItem(ws_item)
        self.tree_widget.expandItem(dataset_item)
        self._sync_active_signals()
        self._update_counts()
        return dataset_id

    def sort_current_dataset_by_frame(self):
        """Sort and group signals for the currently active dataset only."""
        dataset = self._get_current_dataset()
        if dataset is None:
            return False, "Please select a dataset or one of its signals first."
        if not dataset["signals"]:
            return False, "Current dataset is empty."

        old_signals = list(dataset["signals"])
        was_grouped = dataset["grouped"]
        ds_id = dataset["id"]

        grouped = sort_and_group_signals(dataset["signals"])
        dataset["grouped"] = True
        dataset["grouped_signals"] = grouped
        self._render_dataset(dataset)
        self.tree_widget.expandItem(dataset["item"])
        self.dataset_sorted.emit(ds_id, old_signals, was_grouped)
        return True, len(grouped)

    def get_current_dataset_name(self):
        dataset = self._get_current_dataset()
        return dataset["name"] if dataset else None

    def get_active_workspace_name(self):
        ws = self._get_workspace(self.active_workspace_id)
        return ws["name"] if ws else None

    # ── Context menu ─────────────────────────────────────────────────────────
    def _show_context_menu(self, pos):
        item = self.tree_widget.itemAt(pos)
        if item is None:
            return

        kind = item.data(0, self.ROLE_KIND)

        # ── Workspace level ───────────────────────────────────────────────
        if kind == "workspace":
            workspace_id = item.data(0, self.ROLE_WORKSPACE_ID)
            if workspace_id is not None:
                self._set_active_workspace(workspace_id)

            menu = QMenu(self)
            menu.addAction("Rename").triggered.connect(
                lambda: self._rename_workspace(workspace_id)
            )
            menu.addAction("Plot").triggered.connect(
                lambda: self.context_action.emit("plot", self._workspace_signals(workspace_id))
            )
            menu.addAction("Save workspace").triggered.connect(
                lambda: self.context_action.emit("save", self._workspace_signals(workspace_id))
            )
            menu.addAction("Create dataset").triggered.connect(
                lambda: self._create_dataset_in_workspace(workspace_id)
            )
            menu.addSeparator()
            menu.addAction("Close workspace").triggered.connect(
                lambda: self.context_action.emit("close_workspace", [])
            )
            menu.exec_(self.tree_widget.mapToGlobal(pos))
            return

        # ── Dataset level ─────────────────────────────────────────────────
        if kind == "dataset":
            workspace_id = item.data(0, self.ROLE_WORKSPACE_ID)
            dataset_id   = item.data(0, self.ROLE_DATASET_ID)
            if workspace_id is not None:
                self._set_active_workspace(workspace_id)
            if dataset_id is not None:
                self.current_dataset_id = dataset_id
                self._sync_active_signals()

            menu = QMenu(self)
            menu.addAction("Rename").triggered.connect(
                lambda: self._rename_dataset(dataset_id)
            )
            menu.addAction("Plot").triggered.connect(
                lambda: self.context_action.emit("plot", self._dataset_signals(dataset_id))
            )
            menu.addAction("Save dataset").triggered.connect(
                lambda: self.context_action.emit("save", self._dataset_signals(dataset_id))
            )
            menu.addAction("Create signal").triggered.connect(
                lambda: self._create_signal_in_dataset(dataset_id)
            )
            menu.addSeparator()
            menu.addAction("Move to...").triggered.connect(
                lambda: self._move_dataset_via_dialog(dataset_id)
            )
            menu.addAction("Copy to...").triggered.connect(
                lambda: self._copy_dataset_via_dialog(dataset_id)
            )
            menu.addSeparator()
            menu.addAction("Close dataset").triggered.connect(
                lambda: self.context_action.emit("close_dataset", [])
            )
            menu.exec_(self.tree_widget.mapToGlobal(pos))
            return

        if kind != "signal":
            return

        # ── Signal level ──────────────────────────────────────────────────
        dataset_id = item.data(0, self.ROLE_DATASET_ID)
        token_right_clicked = item.data(0, self.ROLE_SIGNAL_TOKEN)
        sig_right_clicked = self._resolve_signal(token_right_clicked, dataset_id)

        # Collect selected signal items. If the right-clicked item is selected,
        # use the full selection even across datasets/workspaces.
        selected_items = self.tree_widget.selectedItems()
        if selected_items and item in selected_items:
            items = selected_items
        else:
            items = [item]

        signals = []
        seen_ids = set()
        for it in items:
            if it.data(0, self.ROLE_KIND) != "signal":
                continue
            item_dataset_id = it.data(0, self.ROLE_DATASET_ID)
            token = it.data(0, self.ROLE_SIGNAL_TOKEN)
            sig = self._resolve_signal(token, item_dataset_id)
            if sig is not None and id(sig) not in seen_ids:
                seen_ids.add(id(sig))
                signals.append(sig)

        if not signals:
            return

        # Keep move/copy actions scoped to the right-clicked dataset only.
        dataset_signals = []
        for it in items:
            if it.data(0, self.ROLE_KIND) != "signal":
                continue
            if it.data(0, self.ROLE_DATASET_ID) != dataset_id:
                continue
            token = it.data(0, self.ROLE_SIGNAL_TOKEN)
            sig = self._resolve_signal(token, dataset_id)
            if sig is not None:
                dataset_signals.append(sig)

        self.current_dataset_id = dataset_id
        self._sync_active_signals()

        menu = QMenu(self)
        # Rename only the right-clicked signal (not the whole selection)
        menu.addAction("Rename").triggered.connect(
            lambda: self._rename_signal(sig_right_clicked)
        )
        menu.addAction("Plot").triggered.connect(
            lambda: self.context_action.emit("plot", signals)
        )
        menu.addSeparator()
        menu.addAction("Move to...").triggered.connect(
            lambda: self._move_signals_via_dialog(dataset_signals, dataset_id)
        )
        menu.addAction("Copy to...").triggered.connect(
            lambda: self._copy_signals_via_dialog(dataset_signals, dataset_id)
        )
        menu.addSeparator()
        menu.addAction("Metadata").triggered.connect(
            lambda: self.context_action.emit("metadata", signals)
        )
        menu.addAction("Axes_manager").triggered.connect(
            lambda: self.context_action.emit("axes", signals)
        )
        menu.addAction("Save signals").triggered.connect(
            lambda: self.context_action.emit("save", signals)
        )
        menu.addSeparator()
        menu.addAction("Remove signals").triggered.connect(
            lambda: self.context_action.emit("remove", signals)
        )
        menu.exec_(self.tree_widget.mapToGlobal(pos))

    # ── Rename helpers ────────────────────────────────────────────────────────
    def _rename_workspace(self, workspace_id):
        ws = self._get_workspace(workspace_id)
        if ws is None:
            return
        old_name = ws["name"]
        new_name, ok = QInputDialog.getText(
            self, "Rename Workspace", "New workspace name:", text=ws["name"]
        )
        if ok and new_name.strip():
            new_name = new_name.strip()
            ws["name"] = new_name
            ws["item"].setText(0, new_name)
            if ws["id"] == self.active_workspace_id:
                self.workspace_hint.setText(f"Active: {new_name}")
            self.workspace_renamed.emit(workspace_id, old_name, new_name)

    def _rename_dataset(self, dataset_id):
        dataset = self.datasets.get(dataset_id)
        if dataset is None:
            return
        old_name = dataset["name"]
        new_name, ok = QInputDialog.getText(
            self, "Rename Dataset", "New dataset name:", text=dataset["name"]
        )
        if ok and new_name.strip():
            dataset["name"] = new_name.strip()
            self._render_dataset(dataset)
            self.dataset_renamed.emit(dataset_id, old_name, new_name.strip())

    def _rename_signal(self, sig):
        if sig is None:
            return
        # Read the current display name — prefer the app-level override so
        # the dialog shows what the user last set, not the on-disk metadata.
        current_name = getattr(sig, "_ev_display_name", None)
        if not current_name:
            try:
                current_name = sig.metadata.General.title
            except Exception:
                current_name = ""
        new_name, ok = QInputDialog.getText(
            self, "Rename Signal", "New signal name:", text=current_name
        )
        if ok and new_name.strip():
            # Store the display name as a plain Python attribute on the signal
            # object.  HyperSpy does NOT serialise arbitrary Python attributes,
            # so this will NEVER be written to the source file, even if the
            # signal is later saved.  The original sig.metadata.General.title
            # is left completely untouched.
            sig._ev_display_name = new_name.strip()
            # Re-render the dataset that owns this signal
            for dataset in self.datasets.values():
                if self._find_signal_index(dataset["signals"], sig) is not None:
                    self._render_dataset(dataset)
                    break
            self.signal_renamed.emit(sig, current_name, new_name.strip())

    # ── Create helpers ────────────────────────────────────────────────────────
    def _create_dataset_in_workspace(self, workspace_id):
        ws = self._get_workspace(workspace_id)
        if ws is None:
            return
        self._set_active_workspace(workspace_id)
        suggested = f"Dataset {self._dataset_counter + 1}"
        new_name, ok = QInputDialog.getText(
            self, "Create Dataset", "Dataset name:", text=suggested
        )
        if ok and new_name.strip():
            self.add_dataset_to_active_workspace(new_name.strip(), [])

    def _create_signal_in_dataset(self, dataset_id):
        dataset = self.datasets.get(dataset_id)
        if dataset is None:
            return

        dialog = CreateSignalDialog(self)
        if dialog.exec_() != QDialog.Accepted:
            return

        type_name   = dialog.get_type_name()
        signal_name = dialog.get_signal_name()
        shape       = dialog.get_shape()

        if shape is None:
            QMessageBox.warning(
                self, "Invalid Shape",
                "Please enter a valid shape as comma-separated integers (e.g. 100,100)."
            )
            return

        try:
            sig = create_hyperspy_signal(type_name, shape, signal_name)
        except Exception as e:
            QMessageBox.critical(
                self, "Create Signal Error", f"Failed to create signal:\n{e}"
            )
            return

        dataset["signals"].append(sig)
        if dataset["grouped"]:
            dataset["grouped_signals"] = sort_and_group_signals(dataset["signals"])
        self.current_dataset_id = dataset_id
        self._render_dataset(dataset)
        self._sync_active_signals()
        self._update_counts()
        self.signal_created.emit(sig, dataset_id)

    def _choose_workspace_target(self, title="Choose Workspace"):
        """Return target workspace id, allowing new or existing workspace selection."""
        choice_msg = QMessageBox(self)
        choice_msg.setWindowTitle(title)
        choice_msg.setText("Select destination workspace:")
        btn_new = choice_msg.addButton("New Workspace", QMessageBox.AcceptRole)
        btn_existing = choice_msg.addButton("Existing Workspace", QMessageBox.ActionRole)
        choice_msg.addButton(QMessageBox.Cancel)
        choice_msg.exec_()

        clicked = choice_msg.clickedButton()
        if clicked == btn_new:
            suggested = f"Workspace {self._workspace_counter + 1}"
            name, ok = QInputDialog.getText(self, "New Workspace", "Workspace name:", text=suggested)
            if not ok:
                return None
            return self.add_workspace(name.strip() or suggested)

        if clicked == btn_existing:
            if not self.workspaces:
                return self.add_workspace()
            labels = [ws["name"] for ws in self.workspaces]
            selected, ok = QInputDialog.getItem(
                self,
                "Existing Workspace",
                "Destination workspace:",
                labels,
                0,
                False,
            )
            if not ok or not selected:
                return None
            for ws in self.workspaces:
                if ws["name"] == selected:
                    return ws["id"]
        return None

    def _choose_dataset_in_workspace(self, workspace_id, title="Choose Dataset"):
        """Return destination dataset id under workspace_id, allowing new/existing."""
        ws = self._get_workspace(workspace_id)
        if ws is None:
            return None

        choice_msg = QMessageBox(self)
        choice_msg.setWindowTitle(title)
        choice_msg.setText(f"Destination workspace: '{ws['name']}'")
        choice_msg.setInformativeText("Select destination dataset:")
        btn_new = choice_msg.addButton("New Dataset", QMessageBox.AcceptRole)
        btn_existing = choice_msg.addButton("Existing Dataset", QMessageBox.ActionRole)
        choice_msg.addButton(QMessageBox.Cancel)
        choice_msg.exec_()

        clicked = choice_msg.clickedButton()
        if clicked == btn_new:
            suggested = f"Dataset {self._dataset_counter + 1}"
            name, ok = QInputDialog.getText(self, "New Dataset", "Dataset name:", text=suggested)
            if not ok:
                return None
            return self._create_empty_dataset_under_workspace(workspace_id, name.strip() or suggested)

        if clicked == btn_existing:
            if not ws["datasets"]:
                return self._create_empty_dataset_under_workspace(workspace_id, "Dataset")
            labels = [f"{ds['name']} ({len(ds['signals'])} signals)" for ds in ws["datasets"]]
            selected, ok = QInputDialog.getItem(
                self,
                "Existing Dataset",
                "Destination dataset:",
                labels,
                0,
                False,
            )
            if not ok or not selected:
                return None
            idx = labels.index(selected)
            return ws["datasets"][idx]["id"]

        return None

    def _choose_destination_dataset(self, title="Choose Destination"):
        """Pick destination dataset by selecting workspace then dataset."""
        target_workspace_id = self._choose_workspace_target(title)
        if target_workspace_id is None:
            return None
        return self._choose_dataset_in_workspace(target_workspace_id, title)

    def _clone_signal(self, sig):
        """Clone a signal object for copy operations."""
        try:
            if hasattr(sig, "deepcopy"):
                return sig.deepcopy()
            return copy.deepcopy(sig)
        except Exception:
            return None

    def _move_signals_via_dialog(self, signals, source_dataset_id):
        target_dataset_id = self._choose_destination_dataset("Move Signals")
        if target_dataset_id is None:
            return

        moved = 0
        for sig in signals:
            if self._move_signal_to_dataset(sig, source_dataset_id, target_dataset_id):
                moved += 1

        if moved:
            self.current_dataset_id = target_dataset_id
            self._sync_active_signals()

    def _copy_signals_via_dialog(self, signals, _source_dataset_id):
        target_dataset_id = self._choose_destination_dataset("Copy Signals")
        if target_dataset_id is None:
            return

        target = self.datasets.get(target_dataset_id)
        if target is None:
            return

        clones = []
        failed = 0
        for sig in signals:
            clone = self._clone_signal(sig)
            if clone is None:
                failed += 1
                continue
            target["signals"].append(clone)
            clones.append(clone)

        if target["grouped"]:
            target["grouped_signals"] = sort_and_group_signals(target["signals"])
        self._render_dataset(target)
        self._update_counts()

        if failed:
            QMessageBox.warning(self, "Copy Signals", f"Copied {len(clones)} signal(s), failed {failed}.")
        if clones:
            self.signals_copied.emit(clones, target_dataset_id)

    def _move_dataset_via_dialog(self, dataset_id):
        target_dataset_id = self._choose_destination_dataset("Move Dataset")
        if target_dataset_id is None:
            return
        target_ds = self.datasets.get(target_dataset_id)
        if target_ds is None:
            return
        self._move_dataset_to_workspace(dataset_id, target_ds["workspace_id"])

    def _copy_dataset_via_dialog(self, dataset_id):
        source = self.datasets.get(dataset_id)
        if source is None:
            return

        target_dataset_id = self._choose_destination_dataset("Copy Dataset")
        if target_dataset_id is None:
            return

        target = self.datasets.get(target_dataset_id)
        if target is None:
            return

        clones = []
        failed = 0
        for sig in source["signals"]:
            clone = self._clone_signal(sig)
            if clone is None:
                failed += 1
                continue
            target["signals"].append(clone)
            clones.append(clone)

        if target["grouped"]:
            target["grouped_signals"] = sort_and_group_signals(target["signals"])
        self._render_dataset(target)
        self._update_counts()

        if failed:
            QMessageBox.warning(self, "Copy Dataset", f"Copied {len(clones)} signal(s), failed {failed}.")
        if clones:
            self.signals_copied.emit(clones, target_dataset_id)

    # ── Move helpers ──────────────────────────────────────────────────────────
    def _move_signal_to_dataset(self, sig, source_dataset_id, target_dataset_id) -> bool:
        if sig is None:
            return False
        if source_dataset_id == target_dataset_id:
            return False
        source = self.datasets.get(source_dataset_id)
        target = self.datasets.get(target_dataset_id)
        if source is None or target is None:
            return False

        src_index = self._find_signal_index(source["signals"], sig)
        if src_index is None:
            return False

        source["signals"].pop(src_index)
        target["signals"].append(sig)

        if source["grouped"]:
            source["grouped_signals"] = sort_and_group_signals(source["signals"])
        if target["grouped"]:
            target["grouped_signals"] = sort_and_group_signals(target["signals"])

        self._render_dataset(source)
        self._render_dataset(target)
        self._prune_signal_store()
        self._update_counts()
        self.signal_moved.emit(sig, source_dataset_id, target_dataset_id)
        return True

    def _move_dataset_to_workspace(self, dataset_id, target_workspace_id) -> bool:
        dataset = self.datasets.get(dataset_id)
        if dataset is None:
            return False
        if dataset["workspace_id"] == target_workspace_id:
            return False

        source_ws = self._get_workspace(dataset["workspace_id"])
        target_ws = self._get_workspace(target_workspace_id)
        if source_ws is None or target_ws is None:
            return False

        old_ws_id = dataset["workspace_id"]

        # Remove from source
        source_ws["datasets"] = [d for d in source_ws["datasets"] if d["id"] != dataset_id]
        dataset_item = dataset["item"]
        if dataset_item is not None:
            source_ws["item"].removeChild(dataset_item)

        # Add to target
        dataset["workspace_id"] = target_workspace_id
        target_ws["datasets"].append(dataset)
        if dataset_item is not None:
            target_ws["item"].addChild(dataset_item)
            # Update role data on all items in this dataset
            self._update_item_workspace_role(dataset_item, target_workspace_id)

        self.tree_widget.expandItem(target_ws["item"])
        self._update_counts()
        self.dataset_moved.emit(dataset_id, old_ws_id, target_workspace_id)
        return True

    def _update_item_workspace_role(self, item: QTreeWidgetItem, workspace_id):
        """Recursively update ROLE_WORKSPACE_ID on an item and its children."""
        item.setData(0, self.ROLE_WORKSPACE_ID, workspace_id)
        for i in range(item.childCount()):
            self._update_item_workspace_role(item.child(i), workspace_id)

    # ── Close helpers ─────────────────────────────────────────────────────────
    def close_current_dataset(self):
        """Close currently selected dataset and release references from memory."""
        dataset = self._get_current_dataset()
        if dataset is None:
            return None, []

        dataset_name = dataset["name"]
        workspace    = self._get_workspace(dataset["workspace_id"])
        removed_signals = list(dataset["signals"])

        if workspace is not None:
            workspace["datasets"] = [d for d in workspace["datasets"] if d["id"] != dataset["id"]]

        item = dataset.get("item")
        if item is not None:
            parent = item.parent()
            if parent is not None:
                parent.removeChild(item)

        self.datasets.pop(dataset["id"], None)
        self._prune_signal_store()

        # Auto-select next dataset or workspace node
        self.current_dataset_id = None
        if workspace is not None and workspace["datasets"]:
            next_dataset = workspace["datasets"][0]
            self.current_dataset_id = next_dataset["id"]
            next_item = next_dataset.get("item")
            if next_item is not None:
                self.tree_widget.setCurrentItem(next_item)
                self.tree_widget.scrollToItem(next_item)
                self.tree_widget.expandItem(next_item)
        elif workspace is not None:
            ws_item = workspace.get("item")
            if ws_item is not None:
                self.tree_widget.setCurrentItem(ws_item)
                self.tree_widget.scrollToItem(ws_item)

        self._sync_active_signals()
        self._update_counts()
        gc.collect()
        return dataset_name, removed_signals

    def close_active_workspace(self):
        """Close active workspace and all datasets/signals it contains."""
        workspace = self._get_workspace(self.active_workspace_id)
        if workspace is None:
            return None, [], 0

        workspace_name  = workspace["name"]
        removed_signals = []
        dataset_count   = len(workspace["datasets"])

        for ds in workspace["datasets"]:
            removed_signals.extend(ds["signals"])
            self.datasets.pop(ds["id"], None)
        self._prune_signal_store()

        ws_item = workspace.get("item")
        if ws_item is not None:
            idx = self.tree_widget.indexOfTopLevelItem(ws_item)
            if idx >= 0:
                self.tree_widget.takeTopLevelItem(idx)

        self.workspaces = [ws for ws in self.workspaces if ws["id"] != workspace["id"]]

        if self.workspaces:
            next_ws = self.workspaces[0]
            self._set_active_workspace(next_ws["id"])
            self.current_dataset_id = None
            ws_item = next_ws.get("item")
            if ws_item is not None:
                self.tree_widget.setCurrentItem(ws_item)
                self.tree_widget.scrollToItem(ws_item)
            if next_ws["datasets"]:
                next_dataset = next_ws["datasets"][0]
                self.current_dataset_id = next_dataset["id"]
                ds_item = next_dataset.get("item")
                if ds_item is not None:
                    self.tree_widget.setCurrentItem(ds_item)
                    self.tree_widget.scrollToItem(ds_item)
                    self.tree_widget.expandItem(ds_item)
        else:
            self.add_workspace()
            self.current_dataset_id = None

        self._sync_active_signals()
        self._update_counts()
        gc.collect()
        return workspace_name, removed_signals, dataset_count

    # ── Remove ────────────────────────────────────────────────────────────────
    def remove_signals(self, signals_list: list):
        """Remove signals from datasets in memory and refresh tree nodes."""
        changed_dataset_ids = set()
        target_ids = {id(s) for s in signals_list}
        for dataset in self.datasets.values():
            before = len(dataset["signals"])
            dataset["signals"] = [s for s in dataset["signals"] if id(s) not in target_ids]
            if len(dataset["signals"]) != before:
                changed_dataset_ids.add(dataset["id"])
                if dataset["grouped"]:
                    dataset["grouped_signals"] = sort_and_group_signals(dataset["signals"])

        for dataset_id in changed_dataset_ids:
            dataset = self.datasets.get(dataset_id)
            if dataset is not None:
                self._render_dataset(dataset)

        self._prune_signal_store()
        self._sync_active_signals()
        self._update_counts()

    # ── Undo/Redo helpers (no dialogs, no undo signals emitted) ───────────────
    def remove_dataset_by_id(self, dataset_id):
        """Remove a dataset by id without confirmation (used by undo)."""
        dataset = self.datasets.get(dataset_id)
        if dataset is None:
            return
        workspace = self._get_workspace(dataset["workspace_id"])
        if workspace is not None:
            workspace["datasets"] = [d for d in workspace["datasets"] if d["id"] != dataset_id]
        item = dataset.get("item")
        if item is not None:
            parent = item.parent()
            if parent is not None:
                parent.removeChild(item)
        self.datasets.pop(dataset_id, None)
        self._prune_signal_store()
        if self.current_dataset_id == dataset_id:
            self.current_dataset_id = None
            if workspace is not None and workspace["datasets"]:
                self.current_dataset_id = workspace["datasets"][0]["id"]
        self._sync_active_signals()
        self._update_counts()

    def restore_signals_to_dataset(self, dataset_id, signals):
        """Re-append signals to a dataset without duplicating (used by undo of remove)."""
        dataset = self.datasets.get(dataset_id)
        if dataset is None:
            return
        existing_ids = {id(s) for s in dataset["signals"]}
        for s in signals:
            if id(s) not in existing_ids:
                dataset["signals"].append(s)
                existing_ids.add(id(s))
        if dataset.get("grouped"):
            dataset["grouped_signals"] = sort_and_group_signals(dataset["signals"])
        self._render_dataset(dataset)
        self._sync_active_signals()
        self._update_counts()

    def _rename_dataset_by_id(self, dataset_id, new_name):
        """Silently rename a dataset without dialog (used by undo/redo)."""
        dataset = self.datasets.get(dataset_id)
        if dataset is None:
            return
        dataset["name"] = new_name
        self._render_dataset(dataset)

    def _rename_workspace_by_id(self, workspace_id, new_name):
        """Silently rename a workspace without dialog (used by undo/redo)."""
        ws = self._get_workspace(workspace_id)
        if ws is None:
            return
        ws["name"] = new_name
        ws["item"].setText(0, new_name)
        if ws["id"] == self.active_workspace_id:
            self.workspace_hint.setText(f"Active: {new_name}")

    def close_workspace_by_id(self, workspace_id):
        """Close a workspace by id without confirmation (used by undo of add_workspace)."""
        prev_active = self.active_workspace_id
        self.active_workspace_id = workspace_id
        self.close_active_workspace()
        if prev_active != workspace_id and self._get_workspace(prev_active) is not None:
            self._set_active_workspace(prev_active)

    # ── Internal helpers ──────────────────────────────────────────────────────
    def _on_add_workspace_clicked(self):
        self.add_workspace()

    def _get_workspace(self, workspace_id):
        for ws in self.workspaces:
            if ws["id"] == workspace_id:
                return ws
        return None

    def _get_current_dataset(self):
        if self.current_dataset_id is None:
            return None
        return self.datasets.get(self.current_dataset_id)

    def _dataset_signals(self, dataset_id):
        ds = self.datasets.get(dataset_id)
        if ds is None:
            return []
        return list(ds["signals"])

    def _workspace_signals(self, workspace_id):
        ws = self._get_workspace(workspace_id)
        if ws is None:
            return []
        out = []
        for ds in ws["datasets"]:
            out.extend(ds["signals"])
        return out

    def _set_active_workspace(self, workspace_id):
        self.active_workspace_id = workspace_id
        for ws in self.workspaces:
            item = ws["item"]
            font = item.font(0)
            font.setBold(True)
            item.setFont(0, font)
            if ws["id"] == workspace_id:
                item.setBackground(0, QBrush(QColor("#d9ecff")))
                item.setForeground(0, QBrush(QColor("#003b66")))
            else:
                item.setBackground(0, QBrush())
                item.setForeground(0, QBrush(QColor("#000000")))

        ws = self._get_workspace(workspace_id)
        if ws is not None:
            self.workspace_hint.setText(f"Active: {ws['name']}")
        self._update_counts()

    def _dataset_sort_key(self, sig):
        type_priority = {"HAADF": 0, "DF": 1, "EELS CoreLoss": 2, "EELS LowLoss": 3}
        frame_num = extract_frame_number(get_signal_title(sig))
        if frame_num is None:
            frame_num = float("inf")
        priority = type_priority.get(classify_signal(sig), 99)
        return (frame_num, priority, get_signal_title(sig))

    def _render_dataset(self, dataset):
        item = dataset["item"]
        if item is None:
            return

        item.takeChildren()
        item.setText(0, f"{dataset['name']}  ({len(dataset['signals'])})")

        if dataset["grouped"]:
            grouped = dataset["grouped_signals"] or sort_and_group_signals(dataset["signals"])
            dataset["grouped_signals"] = grouped
            for frame_name, signals in grouped.items():
                frame_item = QTreeWidgetItem([str(frame_name)])
                frame_item.setData(0, self.ROLE_KIND, "frame")
                frame_item.setData(0, self.ROLE_WORKSPACE_ID, dataset["workspace_id"])
                frame_item.setData(0, self.ROLE_DATASET_ID, dataset["id"])

                frame_font = frame_item.font(0)
                frame_font.setBold(True)
                frame_item.setFont(0, frame_font)
                frame_item.setForeground(0, QBrush(QColor("#666666")))
                item.addChild(frame_item)

                for sig in signals:
                    frame_item.addChild(self._build_signal_item(sig, dataset))
        else:
            for sig in sorted(dataset["signals"], key=self._dataset_sort_key):
                item.addChild(self._build_signal_item(sig, dataset))

    def _build_signal_item(self, sig, dataset):
        cls   = type(sig).__name__
        label = classify_signal(sig)
        title = get_signal_title(sig)
        dims  = get_dimensions_str(sig)
        display = f"{title}\n{label}   {dims}"

        signal_item = QTreeWidgetItem([display])
        signal_item.setData(0, self.ROLE_KIND, "signal")
        signal_item.setData(0, self.ROLE_SIGNAL_TOKEN, self._signal_token(sig))
        signal_item.setData(0, self.ROLE_WORKSPACE_ID, dataset["workspace_id"])
        signal_item.setData(0, self.ROLE_DATASET_ID, dataset["id"])

        color = TYPE_COLORS.get(cls, "#607080")
        signal_item.setForeground(0, QBrush(QColor(color)))
        return signal_item

    def _sync_active_signals(self):
        dataset = self._get_current_dataset()
        self.signals = list(dataset["signals"]) if dataset else []

    def _find_signal_index(self, signals, target_sig):
        """Return index of target signal by identity, else None."""
        target_id = id(target_sig)
        for i, sig in enumerate(signals):
            if id(sig) == target_id:
                return i
        return None

    def _signal_token(self, sig):
        """Return stable lightweight token for a signal and register it."""
        token = id(sig)
        self._signal_store[token] = sig
        return token

    def _resolve_signal(self, token, dataset_id=None):
        """Resolve token back to signal; fallback scan protects against stale tokens."""
        if token is None:
            return None
        sig = self._signal_store.get(token)
        if sig is not None:
            return sig

        if dataset_id is not None:
            dataset = self.datasets.get(dataset_id)
            if dataset is not None:
                for cand in dataset["signals"]:
                    if id(cand) == token:
                        self._signal_store[token] = cand
                        return cand
            return None

        for dataset in self.datasets.values():
            for cand in dataset["signals"]:
                if id(cand) == token:
                    self._signal_store[token] = cand
                    return cand
        return None

    def _prune_signal_store(self):
        """Keep only signals still present in datasets to avoid stale references."""
        alive = set()
        for dataset in self.datasets.values():
            for sig in dataset["signals"]:
                alive.add(id(sig))
        self._signal_store = {k: v for k, v in self._signal_store.items() if k in alive}

    def _update_counts(self):
        dataset_count = sum(len(ws["datasets"]) for ws in self.workspaces)
        signal_count  = sum(len(ds["signals"]) for ds in self.datasets.values())
        self.count_label.setText(
            f"{len(self.workspaces)} workspace(s), {dataset_count} dataset(s), {signal_count} signal(s)"
        )
