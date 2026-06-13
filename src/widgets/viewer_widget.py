"""
viewer_widget.py
Phase 2 scaffold: MDI desktop-style viewer.

Signals are plotted in independent subwindows inside a desktop area.
"""
import numpy as np

import matplotlib
matplotlib.use("Qt5Agg")
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QPushButton, QSizePolicy,
    QPlainTextEdit, QLineEdit, QScrollArea, QGroupBox, QCheckBox, QMessageBox,
    QDialog, QMdiArea, QFrame, QApplication, QToolButton,
    QColorDialog, QInputDialog, QSpinBox, QDoubleSpinBox,
    QFormLayout, QStackedWidget,
)
from PyQt5.QtCore import Qt, QSize, pyqtSignal
from PyQt5.QtGui import QPalette, QColor


CMAPS = [
    "gray", "hot", "viridis", "plasma",
    "inferno", "magma", "cividis", "turbo", "RdBu_r",
]

INTERPOLATIONS = [
    "none", "nearest", "bilinear", "bicubic",
    "spline16", "spline36", "hanning", "hamming",
    "hermite", "kaiser", "quadric", "catrom",
    "gaussian", "bessel", "mitchell", "sinc", "lanczos",
]


class InfoPanel(QWidget):
    """A small closeable panel to display text (metadata / axes)."""

    def __init__(self, title: str, text: str, parent=None):
        super().__init__(parent)
        self.setObjectName("InfoPanel")
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        header = QHBoxLayout()
        lbl = QLabel(title)
        lbl.setStyleSheet("font-weight:600")
        header.addWidget(lbl)
        header.addStretch()
        btn_close = QPushButton("x")
        btn_close.setFixedSize(20, 20)
        btn_close.setFlat(True)
        header.addWidget(btn_close)
        layout.addLayout(header)

        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setPlainText(text)
        layout.addWidget(self.text)

        btn_close.clicked.connect(self.close)


class AxisEditorRow(QWidget):
    """A single editable row for an axis: units, scale, offset."""

    AXIS_LABEL_WIDTH = 180
    OFFSET_WIDTH = 170
    SCALE_WIDTH = 170
    UNITS_WIDTH = 110

    def __init__(self, axis, parent=None):
        super().__init__(parent)
        self.axis = axis
        hl = QHBoxLayout(self)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(6)

        name = getattr(axis, "name", getattr(axis, "title", str(axis)))
        size = getattr(axis, "size", None)
        if size is None:
            try:
                size = len(getattr(axis, "axis", []))
            except Exception:
                size = None

        lbl = QLabel(f"{name}  (size={size})")
        lbl.setFixedWidth(self.AXIS_LABEL_WIDTH)
        hl.addWidget(lbl)

        self.offset_edit = QLineEdit()
        self.offset_edit.setFixedWidth(self.OFFSET_WIDTH)
        offset_val = getattr(axis, "offset", None)
        if offset_val is None and hasattr(axis, "axis"):
            try:
                arr = getattr(axis, "axis")
                offset_val = float(arr[0])
            except Exception:
                offset_val = None
        self.offset_edit.setText("" if offset_val is None else str(offset_val))
        hl.addWidget(self.offset_edit)

        self.scale_edit = QLineEdit()
        self.scale_edit.setFixedWidth(self.SCALE_WIDTH)
        scale_val = getattr(axis, "scale", None)
        if scale_val is None and hasattr(axis, "axis"):
            try:
                arr = getattr(axis, "axis")
                if len(arr) > 1:
                    scale_val = float(arr[1] - arr[0])
            except Exception:
                scale_val = None
        self.scale_edit.setText("" if scale_val is None else str(scale_val))
        hl.addWidget(self.scale_edit)

        self.units_edit = QLineEdit()
        self.units_edit.setFixedWidth(self.UNITS_WIDTH)
        self.units_edit.setText(str(getattr(axis, "units", "") or ""))
        hl.addWidget(self.units_edit)

        hl.addStretch()

    def get_values(self):
        return {
            "units": self.units_edit.text().strip(),
            "scale": self.scale_edit.text().strip(),
            "offset": self.offset_edit.text().strip(),
        }


class AxisEditorPanel(QWidget):
    """Panel that exposes editable fields for all axes of a signal."""

    def __init__(self, title: str, signal, viewer=None, apply_to_signals=None, parent=None):
        super().__init__(parent)
        self.signal = signal
        self.viewer = viewer
        self.apply_to_signals = apply_to_signals or []
        self.setMinimumWidth(380)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        header = QHBoxLayout()
        lbl = QLabel(title)
        lbl.setStyleSheet("font-weight:600")
        header.addWidget(lbl)
        header.addStretch()

        self.batch_checkbox = None
        if self.apply_to_signals:
            self.batch_checkbox = QCheckBox(f"Apply to all {len(self.apply_to_signals)+1} signals")
            header.addWidget(self.batch_checkbox)

        btn_apply = QPushButton("Apply")
        btn_close = QPushButton("x")
        btn_close.setFixedSize(20, 20)
        btn_close.setFlat(True)
        header.addWidget(btn_apply)
        header.addWidget(btn_close)
        layout.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        scroll_layout = QVBoxLayout(container)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(8)

        am = getattr(signal, "axes_manager", None)
        self.rows = []

        if am is None:
            scroll_layout.addWidget(QLabel("No axes_manager available on this signal."))
        else:
            nav_axes = getattr(am, "navigation_axes", [])
            sig_axes = getattr(am, "signal_axes", [])

            if nav_axes:
                gb_nav = QGroupBox("Navigation axes")
                gb_nav_layout = QVBoxLayout(gb_nav)
                gb_nav_layout.addLayout(self._column_header_layout())
                for ax in nav_axes:
                    row = AxisEditorRow(ax, parent=gb_nav)
                    self.rows.append((ax, row))
                    gb_nav_layout.addWidget(row)
                scroll_layout.addWidget(gb_nav)

            if sig_axes:
                gb_sig = QGroupBox("Signal axes")
                gb_sig_layout = QVBoxLayout(gb_sig)
                gb_sig_layout.addLayout(self._column_header_layout())
                for ax in sig_axes:
                    row = AxisEditorRow(ax, parent=gb_sig)
                    self.rows.append((ax, row))
                    gb_sig_layout.addWidget(row)
                scroll_layout.addWidget(gb_sig)

        scroll_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll)

        btn_apply.clicked.connect(self._apply_changes)
        btn_close.clicked.connect(self.close)

    def _column_header_layout(self):
        """Header row for axis editor columns."""
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 2)
        layout.setSpacing(6)

        lbl_axis = QLabel("Axis")
        lbl_axis.setFixedWidth(AxisEditorRow.AXIS_LABEL_WIDTH)
        lbl_axis.setStyleSheet("font-weight:600;")
        layout.addWidget(lbl_axis)

        lbl_offsets = QLabel("Offsets")
        lbl_offsets.setFixedWidth(AxisEditorRow.OFFSET_WIDTH)
        lbl_offsets.setStyleSheet("font-weight:600;")
        layout.addWidget(lbl_offsets)

        lbl_scales = QLabel("Scales")
        lbl_scales.setFixedWidth(AxisEditorRow.SCALE_WIDTH)
        lbl_scales.setStyleSheet("font-weight:600;")
        layout.addWidget(lbl_scales)

        lbl_units = QLabel("Units")
        lbl_units.setFixedWidth(AxisEditorRow.UNITS_WIDTH)
        lbl_units.setStyleSheet("font-weight:600;")
        layout.addWidget(lbl_units)

        layout.addStretch()
        return layout

    def _apply_changes(self):
        target_signals = [self.signal]
        if self.batch_checkbox is not None and self.batch_checkbox.isChecked():
            target_signals.extend(self.apply_to_signals)

        axis_changes = {}
        for ax_obj, row in self.rows:
            am = getattr(self.signal, "axes_manager", None)
            if am is None:
                continue
            nav_axes = getattr(am, "navigation_axes", [])
            sig_axes = getattr(am, "signal_axes", [])

            try:
                if ax_obj in nav_axes:
                    axis_idx = nav_axes.index(ax_obj)
                    axis_changes[(axis_idx, "nav")] = row.get_values()
                elif ax_obj in sig_axes:
                    axis_idx = sig_axes.index(ax_obj)
                    axis_changes[(axis_idx, "sig")] = row.get_values()
            except Exception:
                pass

        failures = []
        for sig in target_signals:
            try:
                am = getattr(sig, "axes_manager", None)
                if am is None:
                    continue

                nav_axes = getattr(am, "navigation_axes", [])
                sig_axes = getattr(am, "signal_axes", [])

                for (axis_idx, axis_type), vals in axis_changes.items():
                    if axis_type == "nav" and axis_idx < len(nav_axes):
                        ax_obj = nav_axes[axis_idx]
                    elif axis_type == "sig" and axis_idx < len(sig_axes):
                        ax_obj = sig_axes[axis_idx]
                    else:
                        continue

                    try:
                        if vals["units"] != "" and getattr(ax_obj, "units", None) != vals["units"]:
                            setattr(ax_obj, "units", vals["units"])
                    except Exception as e:
                        failures.append(f"units: {e}")

                    if vals["scale"] != "":
                        try:
                            setattr(ax_obj, "scale", float(vals["scale"]))
                        except Exception as e:
                            failures.append(f"scale: {e}")

                    if vals["offset"] != "":
                        try:
                            setattr(ax_obj, "offset", float(vals["offset"]))
                        except Exception as e:
                            failures.append(f"offset: {e}")
            except Exception as e:
                failures.append(f"Signal error: {e}")

        if failures:
            QMessageBox.warning(self, "Apply Axes", "Some fields failed to apply:\n" + "\n".join(failures[:10]))
        else:
            if len(target_signals) > 1:
                QMessageBox.information(self, "Apply Axes", f"Axes updated for {len(target_signals)} signal(s).")
            else:
                QMessageBox.information(self, "Apply Axes", "Axes updated.")


def _plot_theme(facecolor: str) -> dict:
    """Return a consistent color dict for a plot background hex color."""
    try:
        r, g, b = int(facecolor[1:3], 16), int(facecolor[3:5], 16), int(facecolor[5:7], 16)
        lum = 0.299 * r + 0.587 * g + 0.114 * b
    except Exception:
        lum = 0
    if lum < 128:   # dark background
        return dict(ax_fc=facecolor, tick="#9090b0", title="#d0d8f0",
                    label="#9090b0", line="#4fc3f7", grid="#3a3a5c",
                    suptitle="#a0a8c8", cb_tick="#9090b0")
    else:           # light background
        return dict(ax_fc=facecolor, tick="#404060", title="#1a1a2e",
                    label="#404060", line="#0066cc", grid="#c0c8e0",
                    suptitle="#2a2a4e", cb_tick="#404060")


class SignalPlotWidget(QWidget):
    """Single plot window content shown in the MDI desktop."""

    def __init__(self, signal, cmap="gray", interpolation="none",
                 facecolor="#12121e", parent=None):
        super().__init__(parent)
        self._facecolor = facecolor
        self.signal = signal
        self.cmap = cmap
        self.interpolation = interpolation
        self.annotation_tool = "none"
        self.annotation_color = "#ffb347"
        self._annotation_start = None
        self._annotation_preview = None
        self._annotation_axes = None
        self._annotations = []
        self._selected_annotation = None
        self._annotation_select_box = None
        self._annotation_resize_handle = None
        self._annotation_drag_mode = None
        self._annotation_drag_anchor = None
        self._annotation_drag_origin = None
        self._annotation_hit_tol_px = 8
        self._image_axes = None
        self._image_shape = None
        self._roi_patch = None   # matplotlib.patches.Rectangle overlay
        self._roi_handles = []   # marker artists for resize affordance
        self._roi_label = None   # text artist showing ROI size in px
        self._active_roi = None  # hs.roi.RectangularROI currently shown
        # Multi-ROI overlays: keyed by 1-based index
        self._multi_roi_artists = {}
        self._roi_drag_mode = None
        self._roi_drag_start = None
        self._roi_start_bounds = None
        self._roi_drag_target = None  # actual ROI object being dragged
        self._roi_edge_tol = 0.6

        self.figure = Figure(facecolor="#12121e", tight_layout={"rect": [0, 0, 1, 0.93]})
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setFocusPolicy(Qt.StrongFocus)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)

        self.canvas.mpl_connect("button_press_event", self._on_canvas_press)
        self.canvas.mpl_connect("motion_notify_event", self._on_canvas_motion)
        self.canvas.mpl_connect("button_release_event", self._on_canvas_release)
        self.canvas.mpl_connect("key_press_event", self._on_mpl_key_press)

        self.render()

    def set_annotation_tool(self, tool):
        self.annotation_tool = str(tool or "none")

    def set_annotation_color(self, color):
        if color:
            self.annotation_color = str(color)

    def _annotation_enabled(self):
        return self.annotation_tool in {"text", "line", "rect", "oval"}

    def _clear_annotation_preview(self):
        if self._annotation_preview is None:
            return
        try:
            self._annotation_preview.remove()
        except Exception:
            pass
        self._annotation_preview = None
        self._annotation_start = None
        self._annotation_axes = None

    def _register_annotation(self, artist, kind, axes):
        if artist is None or axes is None:
            return None
        for entry in self._annotations:
            if entry.get("artist") is artist:
                return entry
        entry = {"artist": artist, "kind": str(kind or ""), "axes": axes}
        self._annotations.append(entry)
        return entry

    def _clear_annotation_selection_artists(self):
        if self._annotation_select_box is not None:
            try:
                self._annotation_select_box.remove()
            except Exception:
                pass
            self._annotation_select_box = None
        if self._annotation_resize_handle is not None:
            try:
                self._annotation_resize_handle.remove()
            except Exception:
                pass
            self._annotation_resize_handle = None

    def _annotation_bbox_display(self, entry):
        if entry is None:
            return None
        artist = entry.get("artist")
        if artist is None:
            return None
        try:
            renderer = self.canvas.get_renderer()
            return artist.get_window_extent(renderer=renderer)
        except Exception:
            return None

    def _update_annotation_selection_visual(self):
        self._clear_annotation_selection_artists()
        entry = self._selected_annotation
        if entry is None:
            return
        bbox = self._annotation_bbox_display(entry)
        ax = entry.get("axes")
        if bbox is None or ax is None:
            return

        from matplotlib.patches import Rectangle
        inv = ax.transData.inverted()
        (x0, y0) = inv.transform((bbox.x0, bbox.y0))
        (x1, y1) = inv.transform((bbox.x1, bbox.y1))
        rx = min(x0, x1)
        ry = min(y0, y1)
        rw = abs(x1 - x0)
        rh = abs(y1 - y0)
        self._annotation_select_box = Rectangle(
            (rx, ry), rw, rh,
            fill=False,
            edgecolor="#ffd166",
            linewidth=1.0,
            linestyle=(0, (3, 2)),
            zorder=10,
        )
        ax.add_patch(self._annotation_select_box)

        if entry.get("kind") == "text":
            self._annotation_resize_handle = ax.plot(
                [x1], [y1],
                marker="s",
                markersize=5.5,
                markerfacecolor="#ffd166",
                markeredgecolor="#1a1a1a",
                markeredgewidth=0.8,
                linestyle="None",
                zorder=11,
            )[0]

    def _select_annotation(self, entry):
        self._selected_annotation = entry
        self._update_annotation_selection_visual()
        self.canvas.draw_idle()

    def _deselect_annotation(self):
        self._selected_annotation = None
        self._annotation_drag_mode = None
        self._annotation_drag_anchor = None
        self._annotation_drag_origin = None
        self._clear_annotation_selection_artists()
        self.canvas.draw_idle()

    def _pick_annotation(self, event):
        # Top-most first (newer annotations are appended later).
        for entry in reversed(self._annotations):
            artist = entry.get("artist")
            if artist is None:
                continue
            try:
                hit, _info = artist.contains(event)
            except Exception:
                hit = False
            if not hit:
                continue
            text_resize = self._text_resize_hit(entry, event)
            return entry, text_resize
        return None, False

    def _text_resize_hit(self, entry, event):
        if entry.get("kind") != "text":
            return False
        bbox = self._annotation_bbox_display(entry)
        if bbox is None:
            return False
        ex = float(getattr(event, "x", -1))
        ey = float(getattr(event, "y", -1))
        tol = float(self._annotation_hit_tol_px)
        near_right = abs(ex - bbox.x1) <= tol and (bbox.y0 - tol) <= ey <= (bbox.y1 + tol)
        near_top_right = abs(ex - bbox.x1) <= tol and abs(ey - bbox.y1) <= tol
        return near_right or near_top_right

    def _move_selected_annotation(self, x, y):
        entry = self._selected_annotation
        if entry is None or self._annotation_drag_anchor is None or self._annotation_drag_origin is None:
            return
        kind = entry.get("kind")
        artist = entry.get("artist")
        if artist is None:
            return
        sx, sy = self._annotation_drag_anchor
        dx = x - sx
        dy = y - sy

        try:
            if kind == "text":
                x0, y0 = self._annotation_drag_origin.get("pos", artist.get_position())
                artist.set_position((x0 + dx, y0 + dy))
            elif kind == "line":
                xs, ys = self._annotation_drag_origin.get("xydata", artist.get_data())
                artist.set_data([xs[0] + dx, xs[1] + dx], [ys[0] + dy, ys[1] + dy])
            elif kind == "rect":
                rx, ry = self._annotation_drag_origin.get("xy", artist.get_xy())
                artist.set_xy((rx + dx, ry + dy))
            elif kind == "oval":
                cx, cy = self._annotation_drag_origin.get("center", artist.center)
                artist.center = (cx + dx, cy + dy)
        except Exception:
            return

        self._update_annotation_selection_visual()
        self.canvas.draw_idle()

    def _resize_selected_text(self, event):
        entry = self._selected_annotation
        if entry is None or entry.get("kind") != "text" or self._annotation_drag_origin is None:
            return
        artist = entry.get("artist")
        if artist is None:
            return
        start_px = self._annotation_drag_origin.get("anchor_px")
        start_size = self._annotation_drag_origin.get("fontsize", float(artist.get_fontsize()))
        if start_px is None:
            return

        delta = max(float(event.x) - float(start_px[0]), float(event.y) - float(start_px[1]))
        new_size = max(6.0, min(96.0, float(start_size) + delta * 0.08))
        artist.set_fontsize(new_size)
        self._update_annotation_selection_visual()
        self.canvas.draw_idle()

    def _delete_selected_annotation(self):
        entry = self._selected_annotation
        if entry is None:
            return
        artist = entry.get("artist")
        if artist is not None:
            try:
                artist.remove()
            except Exception:
                pass
        self._annotations = [e for e in self._annotations if e.get("artist") is not artist]
        self._selected_annotation = None
        self._annotation_drag_mode = None
        self._annotation_drag_anchor = None
        self._annotation_drag_origin = None
        self._clear_annotation_selection_artists()
        self.canvas.draw_idle()

    def _on_mpl_key_press(self, event):
        key = str(getattr(event, "key", "") or "").lower()
        if key in {"delete", "backspace"}:
            self._delete_selected_annotation()

    def set_cmap(self, cmap):
        self.cmap = cmap
        self.render()

    def set_interpolation(self, interpolation):
        self.interpolation = interpolation
        self.render()

    def supports_2d_roi(self):
        am = getattr(self.signal, "axes_manager", None)
        if am is None:
            return False
        nav_axes = list(getattr(am, "navigation_axes", []) or [])
        sig_axes = list(getattr(am, "signal_axes", []) or [])
        if len(nav_axes) >= 2:
            return True
        if len(nav_axes) == 0 and len(sig_axes) >= 2:
            return True
        return False

    def get_roi_axes(self):
        """Return axes to be used with hs.roi.RectangularROI for this signal."""
        am = getattr(self.signal, "axes_manager", None)
        if am is None:
            return None
        nav_axes = list(getattr(am, "navigation_axes", []) or [])
        if len(nav_axes) >= 2:
            return nav_axes[-2:]
        # For pure Signal2D, let HyperSpy infer spatial axes by passing axes=None.
        if len(nav_axes) == 0:
            return None
        return None

    def ensure_hyperspy_plot(self):
        """Open HyperSpy's own interactive plot for RectangularROI widgets."""
        try:
            self.signal.plot()
            QApplication.processEvents()
            return True, None
        except Exception as e:
            return False, str(e)

    def get_image_display_axes(self):
        """Return (x_axis, y_axis) mapping ROI left/right→columns, top/bottom→rows."""
        am = getattr(self.signal, "axes_manager", None)
        if am is None:
            return None, None
        nav_axes = list(getattr(am, "navigation_axes", []) or [])
        sig_axes = list(getattr(am, "signal_axes", []) or [])
        if len(nav_axes) >= 2:
            # navigation_axes[0] = fastest (x / columns), [1] = slowest (y / rows)
            return nav_axes[0], nav_axes[1]
        elif len(nav_axes) == 0 and len(sig_axes) >= 2:
            # signal_axes[0] = fastest (x / columns), [1] = slowest (y / rows)
            return sig_axes[0], sig_axes[1]
        return None, None

    def draw_roi_overlay(self, roi):
        """Draw or update a dashed rectangle on the MDI canvas showing the ROI."""
        if self._image_axes is None:
            return
        x_axis, y_axis = self.get_image_display_axes()
        if x_axis is None or y_axis is None:
            return
        # roi.left/right are in x_axis units; roi.top/bottom in y_axis units
        x0 = (roi.left - x_axis.offset) / x_axis.scale
        x1 = (roi.right - x_axis.offset) / x_axis.scale
        y0 = (roi.top - y_axis.offset) / y_axis.scale
        y1 = (roi.bottom - y_axis.offset) / y_axis.scale
        self._active_roi = roi
        if self._roi_patch is None:
            from matplotlib.patches import Rectangle
            self._roi_patch = Rectangle(
                (x0 - 0.5, y0 - 0.5), x1 - x0, y1 - y0,
                linewidth=2.4, edgecolor="#ffb347", facecolor="#ffb347",
                alpha=0.12, linestyle="--", zorder=5,
            )
            self._image_axes.add_patch(self._roi_patch)
        else:
            self._roi_patch.set_xy((x0 - 0.5, y0 - 0.5))
            self._roi_patch.set_width(x1 - x0)
            self._roi_patch.set_height(y1 - y0)

        # Rebuild visible handles each time so resize points are obvious.
        for artist in self._roi_handles:
            try:
                artist.remove()
            except Exception:
                pass
        self._roi_handles = []
        if self._roi_label is not None:
            try:
                self._roi_label.remove()
            except Exception:
                pass
            self._roi_label = None

        left_edge = x0 - 0.5
        right_edge = x1 - 0.5
        top_edge = y0 - 0.5
        bottom_edge = y1 - 0.5
        mid_x = 0.5 * (left_edge + right_edge)
        mid_y = 0.5 * (top_edge + bottom_edge)
        handle_pts = [
            (left_edge, top_edge),
            (right_edge, top_edge),
            (left_edge, bottom_edge),
            (right_edge, bottom_edge),
            (mid_x, top_edge),
            (mid_x, bottom_edge),
            (left_edge, mid_y),
            (right_edge, mid_y),
        ]
        for hx, hy in handle_pts:
            h = self._image_axes.plot(
                hx, hy,
                marker="s",
                markersize=5.8,
                markerfacecolor="#ffd166",
                markeredgecolor="#1a1a1a",
                markeredgewidth=0.9,
                linestyle="None",
                zorder=6,
            )[0]
            self._roi_handles.append(h)

        # Center handle indicates move affordance.
        c = self._image_axes.plot(
            mid_x, mid_y,
            marker="+",
            markersize=8,
            color="#ffef99",
            markeredgewidth=1.2,
            linestyle="None",
            zorder=6,
        )[0]
        self._roi_handles.append(c)

        w_px = max(1, int(round(x1)) - int(round(x0)))
        h_px = max(1, int(round(y1)) - int(round(y0)))
        label_x = left_edge + 0.35
        label_y = top_edge - 0.35
        self._roi_label = self._image_axes.text(
            label_x,
            label_y,
            f"{w_px}x{h_px} px",
            color="#fff8dc",
            fontsize=9,
            fontweight="bold",
            ha="left",
            va="bottom",
            zorder=7,
            bbox={
                "boxstyle": "round,pad=0.22",
                "facecolor": "#101014",
                "edgecolor": "#ffb347",
                "linewidth": 0.8,
                "alpha": 0.88,
            },
        )
        self.canvas.draw_idle()

    def clear_roi_overlay(self):
        """Remove the ROI rectangle overlay from the MDI canvas."""
        self._active_roi = None
        self._roi_drag_target = None
        self._roi_drag_mode = None
        self._roi_drag_start = None
        self._roi_start_bounds = None
        self.canvas.unsetCursor()
        if self._roi_patch is not None:
            try:
                self._roi_patch.remove()
            except Exception:
                pass
            self._roi_patch = None
        for artist in self._roi_handles:
            try:
                artist.remove()
            except Exception:
                pass
        self._roi_handles = []
        if self._roi_label is not None:
            try:
                self._roi_label.remove()
            except Exception:
                pass
            self._roi_label = None
        if self._image_axes is not None:
            self.canvas.draw_idle()

    # ── Multi-ROI overlay helpers ──────────────────────────────────────────

    # Palette: visually distinct colors for up to 10 ROIs.
    _MULTI_ROI_COLORS = [
        "#ef476f", "#06d6a0", "#118ab2", "#ffd166", "#e040fb",
        "#ff9a3c", "#4fc3f7", "#a5d6a7", "#f48fb1", "#ce93d8",
    ]

    def draw_multi_roi_overlay(self, roi_index, roi):
        """Draw or update overlay for one multi-ROI entry (roi_index is 1-based)."""
        if self._image_axes is None:
            return
        x_axis, y_axis = self.get_image_display_axes()
        if x_axis is None or y_axis is None:
            return

        x0 = (roi.left - x_axis.offset) / x_axis.scale
        x1 = (roi.right - x_axis.offset) / x_axis.scale
        y0 = (roi.top - y_axis.offset) / y_axis.scale
        y1 = (roi.bottom - y_axis.offset) / y_axis.scale

        color = self._MULTI_ROI_COLORS[(roi_index - 1) % len(self._MULTI_ROI_COLORS)]
        existing = self._multi_roi_artists.get(roi_index)

        if existing is None:
            from matplotlib.patches import Rectangle
            patch = Rectangle(
                (x0 - 0.5, y0 - 0.5), x1 - x0, y1 - y0,
                linewidth=2.0, edgecolor=color, facecolor=color,
                alpha=0.14, linestyle="-", zorder=5,
            )
            self._image_axes.add_patch(patch)
            handles = self._build_multi_roi_handles(x0, y0, x1, y1, color)
            w_px = max(1, int(round(x1)) - int(round(x0)))
            h_px = max(1, int(round(y1)) - int(round(y0)))
            lbl = self._image_axes.text(
                x0 - 0.5 + 0.35, y0 - 0.5 - 0.35,
                f"#{roi_index}  {w_px}\u00d7{h_px} px",
                color=color, fontsize=8.5, fontweight="bold",
                ha="left", va="bottom", zorder=7,
                bbox={"boxstyle": "round,pad=0.22", "facecolor": "#101014",
                      "edgecolor": color, "linewidth": 0.8, "alpha": 0.90},
            )
            self._multi_roi_artists[roi_index] = {
                "roi": roi,
                "patch": patch,
                "handles": handles,
                "label": lbl,
            }
        else:
            existing["roi"] = roi
            existing["patch"].set_xy((x0 - 0.5, y0 - 0.5))
            existing["patch"].set_width(x1 - x0)
            existing["patch"].set_height(y1 - y0)
            for art in existing["handles"]:
                try:
                    art.remove()
                except Exception:
                    pass
            existing["handles"] = self._build_multi_roi_handles(x0, y0, x1, y1, color)
            w_px = max(1, int(round(x1)) - int(round(x0)))
            h_px = max(1, int(round(y1)) - int(round(y0)))
            existing["label"].set_position((x0 - 0.5 + 0.35, y0 - 0.5 - 0.35))
            existing["label"].set_text(f"#{roi_index}  {w_px}\u00d7{h_px} px")

        self.canvas.draw_idle()

    def _build_multi_roi_handles(self, x0, y0, x1, y1, color):
        le, re = x0 - 0.5, x1 - 0.5
        te, be = y0 - 0.5, y1 - 0.5
        mx, my = 0.5 * (le + re), 0.5 * (te + be)
        pts = [(le, te), (re, te), (le, be), (re, be),
               (mx, te), (mx, be), (le, my), (re, my)]
        handles = []
        for hx, hy in pts:
            h = self._image_axes.plot(
                hx, hy, marker="s", markersize=5.0,
                markerfacecolor=color, markeredgecolor="#1a1a1a",
                markeredgewidth=0.8, linestyle="None", zorder=6,
            )[0]
            handles.append(h)
        return handles

    def clear_multi_roi_overlay(self, roi_index):
        """Remove overlay artists for one multi-ROI entry."""
        entry = self._multi_roi_artists.pop(roi_index, None)
        if entry is None:
            return
        try:
            entry["patch"].remove()
        except Exception:
            pass
        for art in entry.get("handles", []):
            try:
                art.remove()
            except Exception:
                pass
        try:
            entry["label"].remove()
        except Exception:
            pass
        if self._image_axes is not None:
            self.canvas.draw_idle()

    def clear_all_multi_roi_overlays(self):
        """Remove all multi-ROI overlays from this canvas."""
        for idx in list(self._multi_roi_artists.keys()):
            self.clear_multi_roi_overlay(idx)

    def _is_roi_interaction_allowed(self):
        # Respect matplotlib toolbar pan/zoom mode.
        try:
            mode = getattr(self.toolbar, "mode", "")
            if mode:
                return False
        except Exception:
            pass
        return True

    def _current_roi_bounds_pixels(self, roi=None):
        roi_obj = roi if roi is not None else self._active_roi
        if roi_obj is None:
            return None
        x_axis, y_axis = self.get_image_display_axes()
        if x_axis is None or y_axis is None:
            return None
        x0 = (roi_obj.left - x_axis.offset) / x_axis.scale
        x1 = (roi_obj.right - x_axis.offset) / x_axis.scale
        y0 = (roi_obj.top - y_axis.offset) / y_axis.scale
        y1 = (roi_obj.bottom - y_axis.offset) / y_axis.scale
        return [x0, y0, x1, y1]

    def _iter_interactive_rois(self):
        """Yield ROI objects that can be manipulated on this thumbnail."""
        seen = set()
        # Prefer multi-ROIs first (reverse index => most recent on top)
        for idx in sorted(self._multi_roi_artists.keys(), reverse=True):
            entry = self._multi_roi_artists.get(idx) or {}
            roi_obj = entry.get("roi")
            if roi_obj is not None and id(roi_obj) not in seen:
                seen.add(id(roi_obj))
                yield roi_obj
        if self._active_roi is not None and id(self._active_roi) not in seen:
            yield self._active_roi

    def _pick_roi_under_cursor(self, x, y):
        """Return (roi_obj, bounds, mode) for the ROI under cursor, or (None, None, None)."""
        for roi_obj in self._iter_interactive_rois():
            bounds = self._current_roi_bounds_pixels(roi_obj)
            if bounds is None:
                continue
            mode = self._hit_test_roi_mode(x, y, bounds)
            if mode is not None:
                return roi_obj, bounds, mode
        return None, None, None

    def _hit_test_roi_mode(self, x, y, bounds):
        x0, y0, x1, y1 = bounds
        tol = self._roi_edge_tol

        left_edge = x0 - 0.5
        right_edge = x1 - 0.5
        top_edge = y0 - 0.5
        bottom_edge = y1 - 0.5

        near_left = abs(x - left_edge) <= tol
        near_right = abs(x - right_edge) <= tol
        near_top = abs(y - top_edge) <= tol
        near_bottom = abs(y - bottom_edge) <= tol
        inside = (left_edge <= x <= right_edge) and (top_edge <= y <= bottom_edge)

        if near_left and near_top:
            return "resize_tl"
        if near_right and near_top:
            return "resize_tr"
        if near_left and near_bottom:
            return "resize_bl"
        if near_right and near_bottom:
            return "resize_br"
        if near_left:
            return "resize_l"
        if near_right:
            return "resize_r"
        if near_top:
            return "resize_t"
        if near_bottom:
            return "resize_b"
        if inside:
            return "move"
        return None

    def _update_roi_cursor(self, mode):
        if not self._is_roi_interaction_allowed():
            self.canvas.unsetCursor()
            return
        if mode == "move":
            self.canvas.setCursor(Qt.SizeAllCursor)
            return
        if mode in ("resize_l", "resize_r"):
            self.canvas.setCursor(Qt.SizeHorCursor)
            return
        if mode in ("resize_t", "resize_b"):
            self.canvas.setCursor(Qt.SizeVerCursor)
            return
        if mode in ("resize_tl", "resize_br"):
            self.canvas.setCursor(Qt.SizeFDiagCursor)
            return
        if mode in ("resize_tr", "resize_bl"):
            self.canvas.setCursor(Qt.SizeBDiagCursor)
            return
        self.canvas.unsetCursor()

    def _apply_roi_bounds_pixels(self, x0, y0, x1, y1, roi=None):
        roi_obj = roi if roi is not None else self._active_roi
        if roi_obj is None:
            return
        x_axis, y_axis = self.get_image_display_axes()
        if x_axis is None or y_axis is None:
            return

        # Normalize and enforce at least one pixel width/height.
        if x1 < x0:
            x0, x1 = x1, x0
        if y1 < y0:
            y0, y1 = y1, y0

        x0 = int(round(x0))
        y0 = int(round(y0))
        x1 = int(round(x1))
        y1 = int(round(y1))

        if self._image_shape is not None and len(self._image_shape) >= 2:
            ny = int(self._image_shape[0])
            nx = int(self._image_shape[1])
            x0 = max(0, min(nx - 1, x0))
            y0 = max(0, min(ny - 1, y0))
            x1 = max(x0 + 1, min(nx, x1))
            y1 = max(y0 + 1, min(ny, y1))
        else:
            x1 = max(x0 + 1, x1)
            y1 = max(y0 + 1, y1)

        roi_obj.left = x_axis.offset + x0 * x_axis.scale
        roi_obj.top = y_axis.offset + y0 * y_axis.scale
        roi_obj.right = x_axis.offset + x1 * x_axis.scale
        roi_obj.bottom = y_axis.offset + y1 * y_axis.scale

    def _on_canvas_press(self, event):
        if event.button != 1:
            return
        if event.inaxes is None or event.xdata is None or event.ydata is None:
            return
        if not self._is_roi_interaction_allowed():
            return
        self.canvas.setFocus()

        if not self._annotation_enabled():
            picked, want_text_resize = self._pick_annotation(event)
            if picked is not None:
                self._select_annotation(picked)
                self._annotation_drag_mode = "resize_text" if want_text_resize else "move"
                self._annotation_drag_anchor = (float(event.xdata), float(event.ydata))
                artist = picked.get("artist")
                kind = picked.get("kind")
                origin = {}
                if kind == "text" and artist is not None:
                    origin["pos"] = tuple(artist.get_position())
                    origin["fontsize"] = float(artist.get_fontsize())
                    origin["anchor_px"] = (float(getattr(event, "x", 0.0)), float(getattr(event, "y", 0.0)))
                elif kind == "line" and artist is not None:
                    origin["xydata"] = artist.get_data()
                elif kind == "rect" and artist is not None:
                    origin["xy"] = tuple(artist.get_xy())
                elif kind == "oval" and artist is not None:
                    origin["center"] = tuple(artist.center)
                self._annotation_drag_origin = origin
                return

            # Click on empty area clears selected annotation.
            if self._selected_annotation is not None:
                self._deselect_annotation()

        if self._annotation_enabled():
            ax = event.inaxes
            x = float(event.xdata)
            y = float(event.ydata)
            tool = self.annotation_tool

            if tool == "text":
                text, ok = QInputDialog.getText(self, "Text Annotation", "Annotation text:", text="Text")
                if ok and text.strip():
                    txt = ax.text(
                        x, y, text.strip(),
                        color=self.annotation_color,
                        fontsize=10,
                        ha="left", va="bottom",
                        bbox={"boxstyle": "round,pad=0.2", "facecolor": "#101014", "alpha": 0.5,
                              "edgecolor": self.annotation_color, "linewidth": 0.8},
                        zorder=9,
                    )
                    entry = self._register_annotation(txt, "text", ax)
                    self._select_annotation(entry)
                    self.canvas.draw_idle()
                return

            from matplotlib.patches import Rectangle, Ellipse
            self._clear_annotation_preview()
            self._annotation_start = (x, y)
            self._annotation_axes = ax

            if tool == "line":
                self._annotation_preview = ax.plot(
                    [x, x], [y, y], color=self.annotation_color, linewidth=1.6, linestyle="-", zorder=9
                )[0]
            elif tool == "rect":
                self._annotation_preview = Rectangle(
                    (x, y), 0.0, 0.0,
                    fill=False, edgecolor=self.annotation_color,
                    linewidth=1.6, linestyle="-", zorder=9,
                )
                ax.add_patch(self._annotation_preview)
            elif tool == "oval":
                self._annotation_preview = Ellipse(
                    (x, y), 0.0, 0.0,
                    fill=False, edgecolor=self.annotation_color,
                    linewidth=1.6, linestyle="-", zorder=9,
                )
                ax.add_patch(self._annotation_preview)

            self.canvas.draw_idle()
            return

        if event.inaxes is not self._image_axes:
            return

        x = float(event.xdata)
        y = float(event.ydata)
        roi_obj, bounds, mode = self._pick_roi_under_cursor(x, y)

        if roi_obj is None or mode is None or bounds is None:
            return

        self._roi_drag_target = roi_obj
        self._roi_drag_mode = mode
        self._roi_drag_start = (x, y)
        self._roi_start_bounds = bounds
        self._update_roi_cursor(mode)

    def _on_canvas_motion(self, event):
        if self._annotation_drag_mode in {"move", "resize_text"}:
            if event.inaxes is None or event.xdata is None or event.ydata is None:
                return
            if self._annotation_drag_mode == "move":
                self._move_selected_annotation(float(event.xdata), float(event.ydata))
            else:
                self._resize_selected_text(event)
            return

        if self._annotation_enabled():
            if (
                self._annotation_preview is None
                or self._annotation_start is None
                or event.inaxes is not self._annotation_axes
                or event.xdata is None
                or event.ydata is None
            ):
                return

            x0, y0 = self._annotation_start
            x1 = float(event.xdata)
            y1 = float(event.ydata)
            tool = self.annotation_tool

            if tool == "line":
                self._annotation_preview.set_data([x0, x1], [y0, y1])
            elif tool == "rect":
                self._annotation_preview.set_xy((min(x0, x1), min(y0, y1)))
                self._annotation_preview.set_width(abs(x1 - x0))
                self._annotation_preview.set_height(abs(y1 - y0))
            elif tool == "oval":
                w = abs(x1 - x0)
                h = abs(y1 - y0)
                key = str(getattr(event, "key", "") or "").lower()
                if "control" in key or key == "ctrl":
                    side = max(w, h)
                    w = side
                    h = side
                    x1 = x0 + side if x1 >= x0 else x0 - side
                    y1 = y0 + side if y1 >= y0 else y0 - side
                self._annotation_preview.center = ((x0 + x1) * 0.5, (y0 + y1) * 0.5)
                self._annotation_preview.width = w
                self._annotation_preview.height = h

            self.canvas.draw_idle()
            return

        has_any_roi = any(True for _ in self._iter_interactive_rois())
        if not has_any_roi:
            self.canvas.unsetCursor()
            return
        if event.inaxes is not self._image_axes or event.xdata is None or event.ydata is None:
            if self._roi_drag_mode is None:
                self.canvas.unsetCursor()
            return

        if self._roi_drag_mode is None:
            _roi_obj, _bounds, mode = self._pick_roi_under_cursor(float(event.xdata), float(event.ydata))
            self._update_roi_cursor(mode)
            return

        if self._roi_drag_start is None or self._roi_start_bounds is None or self._roi_drag_target is None:
            return

        sx, sy = self._roi_drag_start
        dx = float(event.xdata) - sx
        dy = float(event.ydata) - sy

        x0, y0, x1, y1 = self._roi_start_bounds
        mode = self._roi_drag_mode

        if mode == "move":
            w = x1 - x0
            h = y1 - y0
            nx0 = x0 + dx
            ny0 = y0 + dy
            if self._image_shape is not None and len(self._image_shape) >= 2:
                ny = int(self._image_shape[0])
                nx = int(self._image_shape[1])
                nx0 = max(0, min(nx - w, nx0))
                ny0 = max(0, min(ny - h, ny0))
            nx1 = nx0 + w
            ny1 = ny0 + h
            self._apply_roi_bounds_pixels(nx0, ny0, nx1, ny1, roi=self._roi_drag_target)
            self._update_roi_cursor(mode)
            return

        nx0, ny0, nx1, ny1 = x0, y0, x1, y1
        if "l" in mode:
            nx0 = x0 + dx
        if "r" in mode:
            nx1 = x1 + dx
        if "t" in mode:
            ny0 = y0 + dy
        if "b" in mode:
            ny1 = y1 + dy
        self._apply_roi_bounds_pixels(nx0, ny0, nx1, ny1, roi=self._roi_drag_target)
        self._update_roi_cursor(mode)

    def _on_canvas_release(self, event):
        if self._annotation_drag_mode in {"move", "resize_text"}:
            self._annotation_drag_mode = None
            self._annotation_drag_anchor = None
            self._annotation_drag_origin = None
            return

        if self._annotation_enabled():
            if (
                self._annotation_preview is not None
                and self._annotation_start is not None
                and event is not None
                and event.inaxes is self._annotation_axes
                and event.xdata is not None
                and event.ydata is not None
            ):
                x0, y0 = self._annotation_start
                x1 = float(event.xdata)
                y1 = float(event.ydata)
                if abs(x1 - x0) < 1e-12 and abs(y1 - y0) < 1e-12:
                    try:
                        self._annotation_preview.remove()
                    except Exception:
                        pass
                else:
                    kind = self.annotation_tool
                    entry = self._register_annotation(self._annotation_preview, kind, self._annotation_axes)
                    self._select_annotation(entry)
                self.canvas.draw_idle()

            self._annotation_preview = None
            self._annotation_start = None
            self._annotation_axes = None
            return

        self._roi_drag_target = None
        self._roi_drag_mode = None
        self._roi_drag_start = None
        self._roi_start_bounds = None
        if event is None or event.inaxes is not self._image_axes or event.xdata is None or event.ydata is None:
            self.canvas.unsetCursor()
            return
        _roi_obj, _bounds, mode = self._pick_roi_under_cursor(float(event.xdata), float(event.ydata))
        self._update_roi_cursor(mode)

    def render(self):
        signal = self.signal
        self._clear_annotation_preview()
        self._annotations = []
        self._selected_annotation = None
        self._annotation_drag_mode = None
        self._annotation_drag_anchor = None
        self._annotation_drag_origin = None
        self._clear_annotation_selection_artists()
        self.figure.clear()
        self.figure.set_facecolor(self._facecolor)
        self._image_axes = None
        self._image_shape = None
        self._roi_patch = None  # patch was attached to old axes; cleared by figure.clear()
        self._roi_handles = []
        self._roi_label = None
        self._multi_roi_artists = {}

        cls = type(signal).__name__

        # Read metadata signal_type as a fallback so that signals whose Python
        # class may have been demoted (e.g. BaseSignal after sum()) are still
        # rendered correctly according to their original type.
        sig_type = ""
        try:
            sig_type = signal.metadata.Signal.signal_type or ""
        except Exception:
            pass

        am = getattr(signal, "axes_manager", None)
        nav_dim = len(list(getattr(am, "navigation_axes", []) or [])) if am else 0
        sig_dim = len(list(getattr(am, "signal_axes", []) or [])) if am else 0

        # Dispatch priority: class name → metadata signal_type → dimensions.
        _spectral_types = {"EELS", "EDX_SEM", "EDX_TEM", "CL", "EDS"}
        _spectral_classes = {"EELSSpectrum", "EDXSSpectrum", "Signal1D"}

        if cls == "Signal2D" or (nav_dim == 0 and sig_dim == 2):
            self._display_2d(signal)
        elif (cls in _spectral_classes or sig_type in _spectral_types) and nav_dim >= 1:
            # Spectrum with navigation (cube, line-scan, …): navigator + mean spectrum.
            self._display_eels(signal)
        elif cls in _spectral_classes or sig_type in _spectral_types or sig_dim == 1:
            # 0-D spectrum (summed over all nav axes, standalone Signal1D, …)
            self._display_signal1d(signal)
        else:
            self._display_generic(signal)

        self.canvas.draw()
        # Restore ROI overlay after axes are recreated
        if self._active_roi is not None:
            self.draw_roi_overlay(self._active_roi)

    def _display_2d(self, signal):
        t = _plot_theme(self._facecolor)
        ax = self.figure.add_subplot(111)
        ax.set_facecolor(t["ax_fc"])

        data = signal.data.astype(float)
        self._image_axes = ax
        self._image_shape = data.shape
        im = ax.imshow(
            data,
            cmap=self.cmap,
            interpolation=self.interpolation,
            origin="upper",
            aspect="equal",
        )
        cb = self.figure.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        cb.ax.tick_params(colors=t["cb_tick"])

        ax.set_title(self._safe_title(signal), color=t["title"], pad=8)
        ax.set_xlabel("x (px)", color=t["label"])
        ax.set_ylabel("y (px)", color=t["label"])
        ax.tick_params(colors=t["tick"])

    def _display_signal1d(self, signal):
        """Render any 1-D spectrum signal (Signal1D, EELS after full sum, EDX, …)."""
        t = _plot_theme(self._facecolor)
        ax = self.figure.add_subplot(111)
        ax.set_facecolor(t["ax_fc"])
        ax.tick_params(colors=t["tick"])

        data = signal.data.astype(float).ravel()
        try:
            eax = signal.axes_manager.signal_axes[0]
            x = eax.axis
            x_label = f"{eax.name} ({eax.units})" if eax.units else (eax.name or "Channel")
        except Exception:
            x = np.arange(data.size)
            x_label = "Channel"

        ax.plot(x, data, color=t["line"], linewidth=1.2)
        ax.fill_between(x, data, alpha=0.15, color=t["line"])
        ax.set_title(self._safe_title(signal), color=t["title"], pad=6)
        ax.set_xlabel(x_label, color=t["label"])
        ax.set_ylabel("Intensity", color=t["label"])
        ax.grid(True, alpha=0.15, color=t["grid"])

    def _display_eels(self, signal):
        """
        Render a spectrum with navigation: navigator panel + mean spectrum.

        nav_dim == 1  → spectrum image (waterfall): rows=positions, cols=energy
        nav_dim >= 2  → integrated-intensity image + mean spectrum
        """
        t = _plot_theme(self._facecolor)
        data = signal.data.astype(float)
        am = getattr(signal, "axes_manager", None)
        nav_axes = list(getattr(am, "navigation_axes", []) or []) if am else []
        nav_dim = len(nav_axes)

        ax_img = self.figure.add_subplot(1, 2, 1)
        ax_sp = self.figure.add_subplot(1, 2, 2)
        for ax in (ax_img, ax_sp):
            ax.set_facecolor(t["ax_fc"])
            ax.tick_params(colors=t["tick"])

        self._image_axes = ax_img
        if nav_dim == 1:
            nav_ax = nav_axes[0]
            nav_label = f"{nav_ax.name} ({nav_ax.units})" if getattr(nav_ax, 'units', '') else (getattr(nav_ax, 'name', '') or "Position")
            im = ax_img.imshow(
                data,
                cmap=self.cmap,
                interpolation=self.interpolation,
                origin="upper",
                aspect="auto",
            )
            self.figure.colorbar(im, ax=ax_img, fraction=0.046, pad=0.04).ax.tick_params(colors=t["cb_tick"])
            ax_img.set_title("Spectrum Image", color=t["title"], pad=6)
            ax_img.set_ylabel(nav_label, color=t["label"])
            self._image_shape = data.shape
        else:
            integrated = np.sum(data, axis=-1)
            self._image_shape = integrated.shape
            im = ax_img.imshow(
                integrated,
                cmap=self.cmap,
                interpolation=self.interpolation,
                origin="upper",
                aspect="equal",
            )
            self.figure.colorbar(im, ax=ax_img, fraction=0.046, pad=0.04).ax.tick_params(colors=t["cb_tick"])
            ax_img.set_title("Integrated Intensity", color=t["title"], pad=6)

        mean_spectrum = np.mean(data, axis=tuple(range(nav_dim)))
        try:
            eax = signal.axes_manager.signal_axes[0]
            energy = eax.axis
            xlabel = f"{eax.name} ({eax.units})" if eax.units else (eax.name or "Energy")
        except Exception:
            energy = np.arange(data.shape[-1])
            xlabel = "Channel"

        ax_sp.plot(energy, mean_spectrum, color=t["line"], linewidth=1.2)
        ax_sp.fill_between(energy, mean_spectrum, alpha=0.15, color=t["line"])
        ax_sp.set_title("Mean Spectrum", color=t["title"], pad=6)
        ax_sp.set_xlabel(xlabel, color=t["label"])
        ax_sp.set_ylabel("Intensity", color=t["label"])
        ax_sp.grid(True, alpha=0.15, color=t["grid"])

        self.figure.suptitle(self._safe_title(signal), color=t["suptitle"], fontsize=10, y=0.98)

    def _display_generic(self, signal):
        t = _plot_theme(self._facecolor)
        ax = self.figure.add_subplot(111)
        ax.set_facecolor(t["ax_fc"])
        ax.axis("off")
        info = (
            f"Type: {type(signal).__name__}\n"
            f"Shape: {getattr(signal.data, 'shape', '?')}\n"
            f"dtype: {getattr(signal.data, 'dtype', '?')}\n\n"
            f"Axes:\n{getattr(signal, 'axes_manager', '<none>')}"
        )
        ax.text(
            0.05, 0.95, info,
            transform=ax.transAxes,
            va="top", ha="left",
            color=t["title"],
            fontfamily="monospace",
            fontsize=10,
        )

    @staticmethod
    def _safe_title(signal):
        try:
            t = signal.metadata.General.title
            return t if t else type(signal).__name__
        except Exception:
            return type(signal).__name__


class ElementalMapWidget(QWidget):
    """Interactive elemental mapping panel for any Signal1D with navigation.

    Layout
    ------
    * **nav_dim == 1** (line-scan): spectrum top, integrated line profile bottom.
    * **nav_dim >= 2** (2-D scan): mean spectrum left, integrated map right.

    The user drags or resizes the orange SpanSelector on the mean-spectrum panel
    to choose the integration energy window.  The map/profile updates on release.
    """

    map_export_requested = pyqtSignal(object, str)

    def __init__(self, signal, title: str = "", config=None, parent=None):
        super().__init__(parent)
        self.signal = signal
        self._title = title
        self._config = config

        am = signal.axes_manager
        self._sig_axis   = am.signal_axes[0]            # energy axis
        self._nav_ndim   = am.navigation_dimension
        self._nav_shape  = am.navigation_shape          # HyperSpy order

        # Mean spectrum (average over all nav dims — last ndim axes in data)
        nav_axes_in_array = tuple(range(self._nav_ndim))
        self._mean_spectrum = np.mean(signal.data, axis=nav_axes_in_array).astype(float)

        # Energy axis vector
        off  = float(getattr(self._sig_axis, "offset", 0.0) or 0.0)
        sc   = float(getattr(self._sig_axis, "scale",  1.0) or 1.0)
        n_ch = int(self._sig_axis.size)
        self._energy = off + sc * np.arange(n_ch)
        self._units  = str(getattr(self._sig_axis, "units", "eV") or "eV")
        self._off    = off
        self._sc     = sc

        # Default span: centre quarter of the energy axis
        e_min = float(self._energy[0])
        e_max = float(self._energy[-1])
        e_range = e_max - e_min
        self._span_left  = e_min + e_range * 0.375
        self._span_right = e_min + e_range * 0.625

        self._cbar = None
        self._im   = None   # persistent imshow artist (2-D nav only)
        self._line = None   # persistent line artist (1-D nav only)
        self._last_map_data = None
        self._last_range_str = ""
        self._setup_ui()
        self._update_map()

    # ── UI ───────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        from matplotlib.widgets import SpanSelector

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        _pfc = self._config.get("plot_facecolor", "#12121e") if self._config else "#12121e"
        _t = _plot_theme(_pfc)
        self._t = _t

        self.figure = Figure(facecolor=_pfc)
        self.canvas = FigureCanvasQTAgg(self.figure)
        toolbar = NavigationToolbar2QT(self.canvas, self)

        bar_row = QHBoxLayout()
        bar_row.setContentsMargins(0, 0, 0, 0)
        bar_row.setSpacing(6)
        bar_row.addWidget(toolbar, 1)
        self.btn_export_map = QPushButton("Export map")
        self.btn_export_map.setFixedHeight(26)
        self.btn_export_map.setMinimumWidth(96)
        self.btn_export_map.setStyleSheet(
            "QPushButton {"
            "  background: #1e3a5f;"
            "  color: #f4a261;"
            "  border: 2px solid #f4a261;"
            "  border-radius: 3px;"
            "  padding: 2px 10px;"
            "  font-weight: bold;"
            "}"
            "QPushButton:hover { background: #2a5080; }"
            "QPushButton:disabled { color: #555; border-color: #444; background: #1a1a1a; }"
        )
        self.btn_export_map.clicked.connect(self._export_current_map)
        if self._nav_ndim < 2:
            self.btn_export_map.setEnabled(False)
            self.btn_export_map.setToolTip(
                "Export to Signal2D is available for 2-D navigation maps only."
            )
        else:
            self.btn_export_map.setToolTip(
                "Create a Signal2D from the current integration window and add it to the data list."
            )
        bar_row.addWidget(self.btn_export_map)

        if self._nav_ndim >= 2:
            # 3-column layout: spectrum | map | narrow colorbar
            # Using a dedicated colorbar axes prevents colorbar from
            # stealing space from ax_map on every update.
            gs = self.figure.add_gridspec(
                1, 3,
                width_ratios=[1.0, 1.1, 0.06],
                wspace=0.10,
                left=0.07, right=0.97, top=0.90, bottom=0.13,
            )
            self._ax_spec = self.figure.add_subplot(gs[0])
            self._ax_map  = self.figure.add_subplot(gs[1])
            self._ax_cbar = self.figure.add_subplot(gs[2])
        else:
            gs = self.figure.add_gridspec(
                2, 1, hspace=0.50,
                left=0.10, right=0.95, top=0.92, bottom=0.09,
            )
            self._ax_spec = self.figure.add_subplot(gs[0])
            self._ax_map  = self.figure.add_subplot(gs[1])
            self._ax_cbar = None

        for ax in (self._ax_spec, self._ax_map):
            ax.set_facecolor(_t["ax_fc"])
            ax.tick_params(colors=_t["tick"], labelsize=8)
            for sp in ax.spines.values():
                sp.set_edgecolor(_t["grid"])

        if self._ax_cbar is not None:
            self._ax_cbar.set_facecolor(_pfc)

        # Mean spectrum
        self._ax_spec.plot(
            self._energy, self._mean_spectrum,
            color=_t["line"], linewidth=0.9, alpha=0.92,
        )
        self._ax_spec.set_xlabel(f"Energy ({self._units})", color=_t["label"], fontsize=8)
        self._ax_spec.set_ylabel("Counts (mean)", color=_t["label"], fontsize=8)
        self._ax_spec.set_title(
            "Mean spectrum  —  drag / resize span to set integration window",
            color=_t["title"], fontsize=8,
        )
        # Zoom x-axis to the actual signal energy range (2 % padding each side)
        _e_pad = (self._energy[-1] - self._energy[0]) * 0.02
        self._ax_spec.set_xlim(self._energy[0] - _e_pad, self._energy[-1] + _e_pad)

        # Pre-create the map artist so updates never recreate axes geometry
        if self._nav_ndim >= 2:
            nav_shape = self.signal.axes_manager.navigation_shape
            # navigation_shape is in HyperSpy (fast, slow) order;
            # data array has shape (..., n_channels), so nav dims are leading.
            blank = np.zeros(nav_shape[::-1])  # flip to (rows, cols)
            self._im = self._ax_map.imshow(
                blank, cmap="hot", aspect="equal",
                origin="upper", interpolation="nearest",
            )
            self._cbar = self.figure.colorbar(self._im, cax=self._ax_cbar)
            self._cbar.ax.tick_params(colors=_t["cb_tick"], labelsize=7)
            self._ax_map.set_facecolor(_t["ax_fc"])
            self._ax_map.tick_params(colors=_t["tick"], labelsize=8)
            for sp in self._ax_map.spines.values():
                sp.set_edgecolor(_t["grid"])
        else:
            nav_ax  = self.signal.axes_manager.navigation_axes[0]
            nav_off = float(getattr(nav_ax, "offset", 0.0) or 0.0)
            nav_sc  = float(getattr(nav_ax, "scale",  1.0) or 1.0)
            nav_u   = str(getattr(nav_ax, "units", "") or "")
            nav_n   = int(nav_ax.size)
            nav_x   = nav_off + nav_sc * np.arange(nav_n)
            (self._line,) = self._ax_map.plot(
                nav_x, np.zeros(nav_n), color=_t["line"], linewidth=1.0
            )
            self._ax_map.set_xlabel(
                f"Position ({nav_u})" if nav_u else "Position",
                color=_t["label"], fontsize=8,
            )
            self._ax_map.set_ylabel("Intensity", color=_t["label"], fontsize=8)

        # Interactive SpanSelector
        self._span_selector = SpanSelector(
            self._ax_spec,
            self._on_span_select,
            direction="horizontal",
            useblit=True,
            props=dict(alpha=0.25, facecolor="#f4a261", edgecolor="#f4a261", linewidth=1.0),
            interactive=True,
            drag_from_anywhere=True,
        )
        self._span_selector.extents = (self._span_left, self._span_right)

        root.addLayout(bar_row)
        root.addWidget(self.canvas)

    # ── Span callback ────────────────────────────────────────────────────────

    def _on_span_select(self, left: float, right: float):
        if right - left < abs(self._sc) * 0.5:
            return
        self._span_left  = float(left)
        self._span_right = float(right)
        self._update_map()

    # ── Map computation & rendering ──────────────────────────────────────────

    def _e_to_idx(self, e_val: float) -> int:
        """Convert energy value to nearest integer index (clamped)."""
        if abs(self._sc) < 1e-15:
            return 0
        return int(round((e_val - self._off) / self._sc))

    def _current_map_payload(self):
        """Return (map_data, range_str) for the currently selected span."""
        n = int(self._sig_axis.size)
        i_l = max(0, min(n - 1, self._e_to_idx(self._span_left)))
        i_r = max(i_l + 1, min(n,     self._e_to_idx(self._span_right) + 1))

        map_data = self.signal.data[..., i_l:i_r].sum(axis=-1).astype(float)
        while map_data.ndim > 2:
            map_data = map_data.sum(axis=0)

        e_l = self._energy[i_l]
        e_r = self._energy[min(i_r - 1, len(self._energy) - 1)]
        range_str = f"{e_l:.2f} – {e_r:.2f} {self._units}"
        return map_data, range_str

    def _export_current_map(self):
        if self._nav_ndim < 2:
            QMessageBox.information(
                self,
                "Export Map",
                "Current signal has 1-D navigation (line profile).\n"
                "Export to Signal2D requires a 2-D navigation map.",
            )
            return
        if self._last_map_data is None:
            QMessageBox.warning(self, "Export Map", "No map data available to export.")
            return

        try:
            import hyperspy.api as hs
            map_sig = hs.signals.Signal2D(np.array(self._last_map_data, copy=True))
        except Exception as e:
            QMessageBox.warning(self, "Export Map", f"Could not create Signal2D.\n\n{e}")
            return

        try:
            src_title = SignalPlotWidget._safe_title(self.signal)
        except Exception:
            src_title = "Elemental map"
        export_title = f"ROI map — {src_title} [{self._last_range_str}]"

        # Populate title for downstream display; keep a non-persistent app label too.
        try:
            map_sig.metadata.General.title = export_title
        except Exception:
            pass
        try:
            map_sig._ev_display_name = export_title
        except Exception:
            pass

        self.map_export_requested.emit(map_sig, export_title)

    def _update_map(self):
        map_data, range_str = self._current_map_payload()
        self._last_map_data = np.array(map_data, copy=True)
        self._last_range_str = range_str

        if self._nav_ndim >= 2:
            # Update image data and colorbar in-place — no axes geometry changes
            self._im.set_data(map_data)
            self._im.set_clim(vmin=map_data.min(), vmax=map_data.max())
            self._ax_map.set_title(
                f"Integrated map  [{range_str}]", color=self._t["title"], fontsize=8
            )
        else:
            # Update line y-data in-place
            self._line.set_ydata(map_data)
            self._ax_map.relim()
            self._ax_map.autoscale_view(scalex=False, scaley=True)
            self._ax_map.set_title(
                f"Integrated profile  [{range_str}]", color=self._t["title"], fontsize=8
            )

        self.canvas.draw_idle()


class CropSignalsWidget(QWidget):
    """Interactive crop panel for Signal1D/Signal2D using signal-axis ROI(s)."""

    crop_export_requested = pyqtSignal(object, str)  # (list_of_crops, dataset_name)

    _ROI_COLORS = [
        "#ef476f", "#06d6a0", "#118ab2", "#ffd166", "#e040fb",
        "#ff9a3c", "#4fc3f7", "#a5d6a7", "#f48fb1", "#ce93d8",
    ]

    def __init__(self, signal, crop_count: int = 1, title: str = "", config=None, parent=None):
        super().__init__(parent)
        self.signal = signal
        self._title = title
        self._config = config
        self._crop_count = max(1, int(crop_count))

        am = signal.axes_manager
        self._sig_dim = int(getattr(am, "signal_dimension", 0) or 0)
        self._nav_dim = int(getattr(am, "navigation_dimension", 0) or 0)

        self._selectors = []
        self._patches = []
        self._labels = []
        self._roi_ranges = []
        self._setting_active_extents = False

        self._setup_data()
        self._setup_ui()
        self._refresh_roi_artists()

    def _setup_data(self):
        am = self.signal.axes_manager
        nav_axes_in_array = tuple(range(self._nav_dim))

        if self._sig_dim == 1:
            sig_axis = am.signal_axes[0]
            self._x_off = float(getattr(sig_axis, "offset", 0.0) or 0.0)
            self._x_sc = float(getattr(sig_axis, "scale", 1.0) or 1.0)
            self._x_size = int(sig_axis.size)
            self._x_units = str(getattr(sig_axis, "units", "") or "")
            self._x_vals = self._x_off + self._x_sc * np.arange(self._x_size)
            if self._nav_dim > 0:
                self._preview_1d = np.mean(self.signal.data, axis=nav_axes_in_array).astype(float)
            else:
                self._preview_1d = np.asarray(self.signal.data, dtype=float).ravel()

            x0 = float(self._x_vals[0])
            x1 = float(self._x_vals[-1])
            span = max(abs(x1 - x0), abs(self._x_sc), 1.0)
            width = max(span * 0.10, abs(self._x_sc) * 2.0)
            for i in range(self._crop_count):
                left = x0 + span * (0.05 + 0.03 * i)
                right = left + width
                if right > x1:
                    right = x1
                    left = max(x0, right - width)
                self._roi_ranges.append([float(left), float(right)])

        elif self._sig_dim == 2:
            ax_x = am.signal_axes[0]
            ax_y = am.signal_axes[1]
            self._x_off = float(getattr(ax_x, "offset", 0.0) or 0.0)
            self._x_sc = float(getattr(ax_x, "scale", 1.0) or 1.0)
            self._x_size = int(ax_x.size)
            self._x_units = str(getattr(ax_x, "units", "") or "")
            self._y_off = float(getattr(ax_y, "offset", 0.0) or 0.0)
            self._y_sc = float(getattr(ax_y, "scale", 1.0) or 1.0)
            self._y_size = int(ax_y.size)
            self._y_units = str(getattr(ax_y, "units", "") or "")

            if self._nav_dim > 0:
                self._preview_2d = np.mean(self.signal.data, axis=nav_axes_in_array).astype(float)
            else:
                self._preview_2d = np.asarray(self.signal.data, dtype=float)

            x0 = float(self._x_off)
            x1 = float(self._x_off + self._x_sc * (self._x_size - 1))
            y0 = float(self._y_off)
            y1 = float(self._y_off + self._y_sc * (self._y_size - 1))
            x_min, x_max = min(x0, x1), max(x0, x1)
            y_min, y_max = min(y0, y1), max(y0, y1)
            w = max((x_max - x_min) * 0.10, abs(self._x_sc) * 2.0)
            h = max((y_max - y_min) * 0.10, abs(self._y_sc) * 2.0)
            dx = max((x_max - x_min) * 0.03, abs(self._x_sc))
            dy = max((y_max - y_min) * 0.03, abs(self._y_sc))

            for i in range(self._crop_count):
                left = x_min + (x_max - x_min) * 0.05 + i * dx
                top = y_min + (y_max - y_min) * 0.05 + i * dy
                right = left + w
                bottom = top + h
                if right > x_max:
                    right = x_max
                    left = max(x_min, right - w)
                if bottom > y_max:
                    bottom = y_max
                    top = max(y_min, bottom - h)
                self._roi_ranges.append([float(left), float(top), float(right), float(bottom)])

    def _setup_ui(self):
        from matplotlib.widgets import SpanSelector, RectangleSelector

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        left = QWidget()
        left_col = QVBoxLayout(left)
        left_col.setContentsMargins(0, 0, 0, 0)
        left_col.setSpacing(0)

        self.figure = Figure(facecolor="#12121e")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        left_col.addWidget(self.toolbar)
        left_col.addWidget(self.canvas)
        root.addWidget(left, 1)

        _pbg  = self._config.get("panel_bg",   "#1a1a2e") if self._config else "#1a1a2e"
        _ptxt = self._config.get("panel_text", "#d7def6") if self._config else "#d7def6"

        right = QWidget()
        right.setFixedWidth(300)
        right.setStyleSheet(
            f"QWidget {{ background:{_pbg}; color:{_ptxt}; }}"
            f"QLabel {{ color:{_ptxt}; }}"
            "QSpinBox, QLineEdit {"
            "  background:#0f1326;"
            "  color:#f5f7ff;"
            "  border:1px solid #5a658f;"
            "  border-radius:3px;"
            "  padding:3px 6px;"
            "  selection-background-color:#4a6ea8;"
            "}"
            "QSpinBox::up-button, QSpinBox::down-button { width:22px; height:16px; }"
            "QSpinBox::up-arrow, QSpinBox::down-arrow { width:10px; height:10px; }"
            "QDoubleSpinBox, QDoubleSpinBox:enabled {"
            "  background:#0f1326;"
            "  color:#f5f7ff;"
            "  border:1px solid #5a658f;"
            "  border-radius:3px;"
            "  padding:3px 6px;"
            "  selection-background-color:#4a6ea8;"
            "}"
            "QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width:22px; height:16px; }"
            "QDoubleSpinBox::up-arrow, QDoubleSpinBox::down-arrow { width:10px; height:10px; }"
        )
        right_col = QVBoxLayout(right)
        right_col.setContentsMargins(10, 14, 10, 10)
        right_col.setSpacing(6)

        self._lbl_mode = QLabel(
            "Mode: Signal1D (energy axis)" if self._sig_dim == 1 else "Mode: Signal2D (x/y signal axes)"
        )
        self._lbl_mode.setStyleSheet("font-weight:bold; color:#e9edff;")
        right_col.addWidget(self._lbl_mode)

        idx_row = QHBoxLayout()
        lbl_active = QLabel("Active crop #")
        lbl_active.setStyleSheet("color:#e2e8ff;")
        idx_row.addWidget(lbl_active)
        self._crop_index_spin = QSpinBox()
        self._crop_index_spin.setRange(1, self._crop_count)
        self._crop_index_spin.setValue(1)
        self._crop_index_spin.setFixedWidth(70)
        self._crop_index_spin.setMinimumHeight(30)
        self._crop_index_spin.setStyleSheet(
            "QSpinBox { padding-right:22px; min-height:30px; font-weight:bold; }"
            "QSpinBox::up-button, QSpinBox::down-button { width:20px; height:14px; }"
            "QSpinBox::up-arrow, QSpinBox::down-arrow { width:11px; height:11px; }"
        )
        self._crop_index_spin.valueChanged.connect(self._on_active_crop_changed)
        idx_row.addWidget(self._crop_index_spin)
        idx_row.addStretch()
        right_col.addLayout(idx_row)

        self._manual_guard = False
        bounds_form = QVBoxLayout()
        bounds_form.setSpacing(4)

        def _make_double_spin():
            spin = QDoubleSpinBox()
            spin.setDecimals(6)
            spin.setRange(-1e12, 1e12)
            spin.setSingleStep(self._auto_step())
            spin.setMinimumHeight(30)
            return spin

        self._left_spin = _make_double_spin()
        self._right_spin = _make_double_spin()
        self._top_spin = _make_double_spin()
        self._bottom_spin = _make_double_spin()

        self._left_spin.valueChanged.connect(self._on_manual_bounds_changed)
        self._right_spin.valueChanged.connect(self._on_manual_bounds_changed)
        self._top_spin.valueChanged.connect(self._on_manual_bounds_changed)
        self._bottom_spin.valueChanged.connect(self._on_manual_bounds_changed)

        self._bounds_widget = QWidget()
        bounds_layout = QVBoxLayout(self._bounds_widget)
        bounds_layout.setContentsMargins(0, 0, 0, 0)
        bounds_layout.setSpacing(4)

        self._left_row = self._make_bound_row("Left", self._left_spin)
        self._right_row = self._make_bound_row("Right", self._right_spin)
        self._top_row = self._make_bound_row("Top", self._top_spin)
        self._bottom_row = self._make_bound_row("Bottom", self._bottom_spin)
        bounds_layout.addWidget(self._left_row)
        bounds_layout.addWidget(self._right_row)
        bounds_layout.addWidget(self._top_row)
        bounds_layout.addWidget(self._bottom_row)
        right_col.addWidget(self._bounds_widget)

        self._lbl_bounds = QLabel("")
        self._lbl_bounds.setWordWrap(True)
        self._lbl_bounds.setStyleSheet("color:#cfd8f6;")
        right_col.addWidget(self._lbl_bounds)

        lbl_output = QLabel("Output dataset name")
        lbl_output.setStyleSheet("color:#e2e8ff;")
        right_col.addWidget(lbl_output)
        self._name_edit = QLineEdit()
        base_title = SignalPlotWidget._safe_title(self.signal)
        self._name_edit.setPlaceholderText(f"{base_title} (crops N={self._crop_count})")
        right_col.addWidget(self._name_edit)

        note = QLabel(
            "ROI applies on signal axes only.\n"
            "If navigation axes exist, all navigator pixels are cropped with the same ROI."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#c6d1f4;")
        right_col.addWidget(note)
        right_col.addStretch(1)

        self._btn_export = QPushButton(f"Export {self._crop_count} crop(s)")
        self._btn_export.setFixedHeight(32)
        self._btn_export.setStyleSheet(
            "QPushButton {"
            "  background: #1e3a5f;"
            "  color: #f4a261;"
            "  border: 2px solid #f4a261;"
            "  border-radius: 3px;"
            "  font-weight: bold;"
            "}"
            "QPushButton:hover { background: #2a5080; }"
        )
        self._btn_export.clicked.connect(self._on_export)
        right_col.addWidget(self._btn_export)
        root.addWidget(right)

        gs = self.figure.add_gridspec(1, 1, left=0.08, right=0.97, top=0.92, bottom=0.10)
        self._ax = self.figure.add_subplot(gs[0])
        self._ax.set_facecolor("#1a1a2e")
        self._ax.tick_params(colors="#a0a8c0", labelsize=8)
        for sp in self._ax.spines.values():
            sp.set_edgecolor("#444466")

        if self._sig_dim == 1:
            self._ax.plot(self._x_vals, self._preview_1d, color="#7ec8e3", linewidth=0.9)
            x_unit = f" ({self._x_units})" if self._x_units else ""
            self._ax.set_xlabel(f"Energy{x_unit}", color="#a0a8c0", fontsize=8)
            self._ax.set_ylabel("Counts (mean)", color="#a0a8c0", fontsize=8)
            self._ax.set_title("Drag active span to define crop on signal axis", color="#c0c8e0", fontsize=8)
            x_pad = (self._x_vals[-1] - self._x_vals[0]) * 0.02
            self._ax.set_xlim(self._x_vals[0] - x_pad, self._x_vals[-1] + x_pad)

            for i in range(self._crop_count):
                sel = SpanSelector(
                    self._ax,
                    lambda l, r, idx=i: self._on_span_changed(idx, l, r),
                    direction="horizontal",
                    useblit=True,
                    props=dict(
                        alpha=0.18,
                        facecolor=self._ROI_COLORS[i % len(self._ROI_COLORS)],
                        edgecolor=self._ROI_COLORS[i % len(self._ROI_COLORS)],
                        linewidth=1.0,
                    ),
                    interactive=True,
                    drag_from_anywhere=True,
                )
                lr = self._roi_ranges[i]
                sel.extents = (lr[0], lr[1])
                self._selectors.append(sel)

        else:
            x_min = min(self._x_off, self._x_off + self._x_sc * (self._x_size - 1))
            x_max = max(self._x_off, self._x_off + self._x_sc * (self._x_size - 1))
            y_min = min(self._y_off, self._y_off + self._y_sc * (self._y_size - 1))
            y_max = max(self._y_off, self._y_off + self._y_sc * (self._y_size - 1))

            self._ax.imshow(
                self._preview_2d,
                cmap="gray",
                origin="upper",
                interpolation="nearest",
                extent=[x_min, x_max, y_max, y_min],
                aspect="auto",
            )
            x_unit = f" ({self._x_units})" if self._x_units else ""
            y_unit = f" ({self._y_units})" if self._y_units else ""
            self._ax.set_xlabel(f"X{x_unit}", color="#a0a8c0", fontsize=8)
            self._ax.set_ylabel(f"Y{y_unit}", color="#a0a8c0", fontsize=8)
            self._ax.set_title("Drag active rectangle to define crop on signal axes", color="#c0c8e0", fontsize=8)

            self._rect_selector = RectangleSelector(
                self._ax,
                self._on_rect_changed,
                useblit=True,
                button=[1],
                minspanx=max(abs(self._x_sc), 1e-9),
                minspany=max(abs(self._y_sc), 1e-9),
                interactive=True,
                drag_from_anywhere=True,
                props=dict(alpha=0.15, facecolor="#ffd166", edgecolor="#ffd166", linewidth=1.3),
            )

        self._on_active_crop_changed(self._crop_index_spin.value())

    def _auto_step(self) -> float:
        if getattr(self, "_sig_dim", 0) == 1:
            return max(abs(self._x_sc) / 10.0, 1e-6)
        return max(min(abs(self._x_sc), abs(self._y_sc)) / 10.0, 1e-6)

    def _make_bound_row(self, label_text: str, spin: QDoubleSpinBox) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        label = QLabel(label_text)
        label.setFixedWidth(50)
        label.setStyleSheet("color:#e2e8ff;")
        layout.addWidget(label)
        layout.addWidget(spin, 1)
        return row

    def _active_index(self) -> int:
        return int(self._crop_index_spin.value()) - 1

    def _on_active_crop_changed(self, _value):
        idx = self._active_index()
        self._update_bounds_label(idx)
        self._sync_manual_inputs(idx)
        if self._sig_dim == 1:
            self._setting_active_extents = True
            try:
                for i, sel in enumerate(self._selectors):
                    sel.set_active(i == idx)
                left, right = self._roi_ranges[idx]
                self._selectors[idx].extents = (left, right)
            finally:
                self._setting_active_extents = False
        else:
            self._setting_active_extents = True
            try:
                l, t, r, b = self._roi_ranges[idx]
                self._rect_selector.extents = (l, r, t, b)
            finally:
                self._setting_active_extents = False
        self._refresh_roi_artists()

    def _sync_manual_inputs(self, idx: int):
        self._manual_guard = True
        try:
            if self._sig_dim == 1:
                left, right = self._roi_ranges[idx]
                self._left_spin.setValue(float(left))
                self._right_spin.setValue(float(right))
                self._top_row.setVisible(False)
                self._bottom_row.setVisible(False)
            else:
                left, top, right, bottom = self._roi_ranges[idx]
                self._left_spin.setValue(float(left))
                self._right_spin.setValue(float(right))
                self._top_spin.setValue(float(top))
                self._bottom_spin.setValue(float(bottom))
                self._top_row.setVisible(True)
                self._bottom_row.setVisible(True)
        finally:
            self._manual_guard = False

    def _on_manual_bounds_changed(self, _value):
        if self._manual_guard:
            return
        idx = self._active_index()
        if self._sig_dim == 1:
            left = float(self._left_spin.value())
            right = float(self._right_spin.value())
            if abs(right - left) < abs(self._x_sc) * 0.5:
                return
            self._roi_ranges[idx] = [left, right]
        else:
            left = float(self._left_spin.value())
            top = float(self._top_spin.value())
            right = float(self._right_spin.value())
            bottom = float(self._bottom_spin.value())
            if abs(right - left) < abs(self._x_sc) * 0.5 or abs(bottom - top) < abs(self._y_sc) * 0.5:
                return
            self._roi_ranges[idx] = [left, top, right, bottom]

        self._update_bounds_label(idx)
        self._refresh_roi_artists()

    def _on_span_changed(self, idx: int, left: float, right: float):
        if self._setting_active_extents:
            return
        if idx != self._active_index():
            return
        lo, hi = sorted((float(left), float(right)))
        if hi - lo < abs(self._x_sc) * 0.5:
            return
        self._roi_ranges[idx] = [lo, hi]
        self._update_bounds_label(idx)
        self._refresh_roi_artists()

    def _on_rect_changed(self, eclick, erelease):
        if self._setting_active_extents:
            return
        if eclick is None or erelease is None:
            return
        idx = self._active_index()
        x0 = float(eclick.xdata) if eclick.xdata is not None else None
        y0 = float(eclick.ydata) if eclick.ydata is not None else None
        x1 = float(erelease.xdata) if erelease.xdata is not None else None
        y1 = float(erelease.ydata) if erelease.ydata is not None else None
        if None in (x0, y0, x1, y1):
            return
        l, r = sorted((x0, x1))
        t, b = sorted((y0, y1))
        if abs(r - l) < abs(self._x_sc) * 0.5 or abs(b - t) < abs(self._y_sc) * 0.5:
            return
        self._roi_ranges[idx] = [l, t, r, b]
        self._update_bounds_label(idx)
        self._refresh_roi_artists()

    def _update_bounds_label(self, idx: int):
        if self._sig_dim == 1:
            l, r = self._roi_ranges[idx]
            unit = self._x_units or "axis units"
            self._lbl_bounds.setText(f"Crop #{idx+1}: left={l:.4g}, right={r:.4g} ({unit})")
        else:
            l, t, r, b = self._roi_ranges[idx]
            unit_x = self._x_units or "x"
            unit_y = self._y_units or "y"
            self._lbl_bounds.setText(
                f"Crop #{idx+1}: left={l:.4g}, top={t:.4g}, right={r:.4g}, bottom={b:.4g}\n"
                f"Units: {unit_x}, {unit_y}"
            )

    def _refresh_roi_artists(self):
        from matplotlib.patches import Rectangle

        for p in self._patches:
            try:
                p.remove()
            except Exception:
                pass
        self._patches = []

        for t in self._labels:
            try:
                t.remove()
            except Exception:
                pass
        self._labels = []

        if self._sig_dim == 1:
            y_min, y_max = self._ax.get_ylim()
            y_span = max(y_max - y_min, 1e-12)
            y_pos = y_max - y_span * 0.06
            for i, (l, r) in enumerate(self._roi_ranges):
                color = self._ROI_COLORS[i % len(self._ROI_COLORS)]
                alpha = 0.26 if i == self._active_index() else 0.14
                patch = self._ax.axvspan(l, r, color=color, alpha=alpha, zorder=2)
                self._patches.append(patch)
                txt = self._ax.text(
                    l, y_pos, f"#{i+1}", color=color, fontsize=8, fontweight="bold",
                    ha="left", va="top", zorder=3,
                    bbox={"boxstyle": "round,pad=0.2", "facecolor": "#101014", "edgecolor": color, "alpha": 0.85},
                )
                self._labels.append(txt)
        else:
            for i, (l, t, r, b) in enumerate(self._roi_ranges):
                color = self._ROI_COLORS[i % len(self._ROI_COLORS)]
                alpha = 0.24 if i == self._active_index() else 0.12
                rect = Rectangle(
                    (l, t),
                    r - l,
                    b - t,
                    linewidth=2.0,
                    edgecolor=color,
                    facecolor=color,
                    alpha=alpha,
                    zorder=3,
                )
                self._ax.add_patch(rect)
                self._patches.append(rect)
                txt = self._ax.text(
                    l, t, f"#{i+1}", color=color, fontsize=8, fontweight="bold",
                    ha="left", va="bottom", zorder=4,
                    bbox={"boxstyle": "round,pad=0.2", "facecolor": "#101014", "edgecolor": color, "alpha": 0.85},
                )
                self._labels.append(txt)

        self.canvas.draw_idle()

    def _output_dataset_name(self) -> str:
        txt = self._name_edit.text().strip()
        if txt:
            return txt
        return self._name_edit.placeholderText() or f"Crops (N={self._crop_count})"

    def _on_export(self):
        crops = []
        failed = 0

        for i, roi in enumerate(self._roi_ranges):
            try:
                if self._sig_dim == 1:
                    l, r = sorted((float(roi[0]), float(roi[1])))
                    if abs(r - l) < abs(self._x_sc) * 0.5:
                        failed += 1
                        continue
                    c = self.signal.isig[l:r].copy()
                else:
                    l, t, r, b = roi
                    x0, x1 = sorted((float(l), float(r)))
                    y0, y1 = sorted((float(t), float(b)))
                    if abs(x1 - x0) < abs(self._x_sc) * 0.5 or abs(y1 - y0) < abs(self._y_sc) * 0.5:
                        failed += 1
                        continue
                    c = self.signal.isig[x0:x1, y0:y1].copy()

                title_base = SignalPlotWidget._safe_title(self.signal)
                try:
                    c.metadata.General.title = f"{title_base} crop #{i+1}"
                except Exception:
                    pass
                try:
                    sig_type = self.signal.metadata.Signal.signal_type
                    if sig_type:
                        c.set_signal_type(sig_type)
                except Exception:
                    pass

                crops.append(c)
            except Exception:
                failed += 1

        if not crops:
            QMessageBox.warning(
                self,
                "Crop signals",
                "No valid crops were produced.\nAdjust ROI ranges and try again.",
            )
            return

        dataset_name = self._output_dataset_name()
        self.crop_export_requested.emit(crops, dataset_name)
        if failed:
            QMessageBox.information(
                self,
                "Crop signals",
                f"Exported {len(crops)} crop(s). Skipped {failed} invalid crop(s).",
            )


class _MatplotlibPanel(QWidget):
    """Minimal MDI panel that embeds an existing matplotlib Figure."""

    def __init__(self, fig, title="", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        canvas = FigureCanvasQTAgg(fig)
        toolbar = NavigationToolbar2QT(canvas, self)
        layout.addWidget(toolbar)
        layout.addWidget(canvas)
        canvas.draw()


class PcaWidget(QWidget):
    """Interactive PCA / decomposition panel.

    Workflow
    --------
    1. Choose algorithm and optional n_components, click Run Decomposition.
    2. Scree plot appears (log-scale dot plot of individual variance ratio).
    3. Pick signal components to keep; optionally plot factors / loadings.
    4. Export denoised signal and/or noise residual to data list.
    """

    pca_export_requested = pyqtSignal(object, str)  # (list_of_signals, dataset_name)
    figure_ready = pyqtSignal(object, str)           # (matplotlib Figure, title)

    _ALGORITHMS = [
        "SVD", "MLPCA", "sklearn_pca", "nmf",
        "sparse_pca", "mini_batch_sparse_pca",
        "RPCA", "ORPCA", "ORNMF",
    ]

    def __init__(self, signal, title="", config=None, parent=None):
        super().__init__(parent)
        self._signal = signal
        self._pca_signal = None
        self._config = config
        self._title = title or "PCA / Decomposition"
        self._decomposed = False
        self._n_components_computed = 0
        self._setup_ui()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        self.setWindowTitle(self._title)
        root = QHBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(6)

        # Left: scree canvas
        _pfc = self._config.get("plot_facecolor", "#12121e") if self._config else "#12121e"
        _pt = _plot_theme(_pfc)
        left = QWidget()
        left_vbox = QVBoxLayout(left)
        left_vbox.setContentsMargins(0, 0, 0, 0)
        self._fig = Figure(figsize=(5, 4), facecolor=_pfc, tight_layout=True)
        self._ax_scree = self._fig.add_subplot(111)
        self._ax_scree.set_facecolor(_pfc)
        self._ax_scree.set_title("Scree plot (run decomposition first)",
                                  color=_pt["title"])
        self._ax_scree.set_xlabel("Component index")
        self._ax_scree.set_ylabel("Explained variance (%)")
        self._canvas = FigureCanvasQTAgg(self._fig)
        toolbar = NavigationToolbar2QT(self._canvas, left)
        left_vbox.addWidget(toolbar)
        left_vbox.addWidget(self._canvas)
        root.addWidget(left, stretch=3)

        # Right: controls — wrapped in a scroll area so small windows can still reach all controls
        right_inner = QWidget()
        right_vbox = QVBoxLayout(right_inner)
        right_vbox.setContentsMargins(8, 8, 8, 8)
        right_vbox.setSpacing(10)
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QScrollArea.NoFrame)
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        right_scroll.setWidget(right_inner)
        right_scroll.setMinimumWidth(300)

        _fs = 11  # default panel font size
        if self._config:
            try:
                _fs = int(self._config.get("panel_font_size", 11))
            except Exception:
                pass

        _pbg  = self._config.get("panel_bg",   "#1a1a2e") if self._config else "#1a1a2e"
        _ptxt = self._config.get("panel_text", "#d7def6") if self._config else "#d7def6"

        _ctrl_style = f"""
            QWidget {{ background-color:{_pbg}; color:{_ptxt}; font-size:{_fs}px; }}
            QLabel  {{ color:{_ptxt}; }}
            QGroupBox {{
                color:{_ptxt};
                border:1px solid #3a4060;
                border-radius:4px;
                margin-top:20px;
                padding-top:6px;
                font-size:{_fs}px;
            }}
            QGroupBox::title {{
                subcontrol-origin:margin;
                subcontrol-position:top left;
                left:8px;
                top:4px;
                color:{_ptxt};
                padding:0 4px;
            }}
            QComboBox, QSpinBox, QLineEdit {{
                background:#0f1326; color:#f5f7ff; border:1px solid #5a658f;
                border-radius:3px; padding:2px 6px; font-size:{_fs}px;
            }}
            QPushButton {{
                background:#2d3a6e; color:#d7def6; border:1px solid #5a658f;
                border-radius:4px; padding:5px 10px; font-size:{_fs}px;
            }}
            QPushButton:hover   {{ background:#3a4a8e; }}
            QPushButton:disabled {{ background:#1a1e2e; color:#555; border-color:#333; }}
        """
        right_inner.setStyleSheet(_ctrl_style)
        right_scroll.setStyleSheet(f"background:{_pbg}; border:none;")

        # Signal title
        sig_lbl = QLabel(f"Signal: {self._signal_title()}")
        sig_lbl.setWordWrap(True)
        sig_lbl.setStyleSheet(f"font-size:{max(_fs-1,9)}px; color:{_ptxt};")
        right_vbox.addWidget(sig_lbl)

        # Decomposition settings
        set_grp = QGroupBox("Decomposition settings")
        set_form = QFormLayout(set_grp)
        set_form.setHorizontalSpacing(8)
        set_form.setVerticalSpacing(6)

        self._algo_combo = QComboBox()
        self._algo_combo.addItems(self._ALGORITHMS)
        set_form.addRow("Algorithm:", self._algo_combo)

        self._ncomp_spin = QSpinBox()
        self._ncomp_spin.setRange(0, 4096)
        self._ncomp_spin.setValue(0)
        self._ncomp_spin.setSpecialValueText("Auto")
        self._ncomp_spin.setToolTip("0 = compute all components")
        set_form.addRow("n_components:", self._ncomp_spin)

        self._float32_copy_cb = QCheckBox("Use float32 working copy")
        self._float32_copy_cb.setChecked(False)
        self._float32_copy_cb.setToolTip(
            "Create a copied signal converted to float32 for decomposition. "
            "Useful when input data is integer type."
        )
        set_form.addRow("", self._float32_copy_cb)

        right_vbox.addWidget(set_grp)

        self._run_btn = QPushButton("▶  Run Decomposition")
        self._run_btn.setStyleSheet(
            "background:#1f7a3f; font-weight:bold; padding:6px; color:#e0ffe0;"
        )
        self._run_btn.clicked.connect(self._on_run)
        right_vbox.addWidget(self._run_btn)

        self._status_lbl = QLabel("")
        self._status_lbl.setWordWrap(True)
        self._status_lbl.setStyleSheet("color:#90c090; font-size:10px;")
        right_vbox.addWidget(self._status_lbl)

        # Component selection
        self._comp_grp = QGroupBox("Component selection")
        self._comp_grp.setEnabled(False)
        comp_form = QFormLayout(self._comp_grp)
        comp_form.setHorizontalSpacing(8)
        comp_form.setVerticalSpacing(6)

        self._nsig_spin = QSpinBox()
        self._nsig_spin.setRange(1, 4096)
        self._nsig_spin.setValue(3)
        self._nsig_spin.setToolTip("Components 0 … n−1 = signal; rest = noise")
        comp_form.addRow("Signal components:", self._nsig_spin)

        right_vbox.addWidget(self._comp_grp)

        # Visualise
        self._viz_grp = QGroupBox("Visualise")
        self._viz_grp.setEnabled(False)
        viz_vbox = QVBoxLayout(self._viz_grp)
        viz_vbox.setSpacing(5)

        viz_n_row = QHBoxLayout()
        viz_n_row.addWidget(QLabel("# components:"))
        self._viz_ncomp_spin = QSpinBox()
        self._viz_ncomp_spin.setRange(1, 100)
        self._viz_ncomp_spin.setValue(10)
        viz_n_row.addWidget(self._viz_ncomp_spin)
        viz_vbox.addLayout(viz_n_row)

        self._btn_plot_factors = QPushButton("Plot factors (spectra)")
        self._btn_plot_factors.clicked.connect(self._on_plot_factors)
        viz_vbox.addWidget(self._btn_plot_factors)

        self._btn_plot_loadings = QPushButton("Plot loadings (maps)")
        self._btn_plot_loadings.clicked.connect(self._on_plot_loadings)
        viz_vbox.addWidget(self._btn_plot_loadings)

        right_vbox.addWidget(self._viz_grp)

        # Export
        self._export_grp = QGroupBox("Export")
        self._export_grp.setEnabled(False)
        exp_vbox = QVBoxLayout(self._export_grp)
        exp_vbox.setSpacing(5)

        exp_vbox.addWidget(QLabel("Dataset name prefix:"))
        self._out_name_edit = QLineEdit(f"{self._signal_title()} PCA")
        exp_vbox.addWidget(self._out_name_edit)

        self._btn_export_denoised = QPushButton("Export denoised signal")
        self._btn_export_denoised.setStyleSheet(
            "background:#1a5a8f; color:#d7def6;"
        )
        self._btn_export_denoised.clicked.connect(self._on_export_denoised)
        exp_vbox.addWidget(self._btn_export_denoised)

        self._btn_export_noise = QPushButton("Export noise residual")
        self._btn_export_noise.clicked.connect(self._on_export_noise)
        exp_vbox.addWidget(self._btn_export_noise)

        right_vbox.addWidget(self._export_grp)
        right_vbox.addStretch()
        root.addWidget(right_scroll, stretch=1)

    def _signal_title(self):
        try:
            return str(self._signal.metadata.General.title or "Signal")
        except Exception:
            return "Signal"

    def _analysis_signal(self):
        return self._pca_signal if self._pca_signal is not None else self._signal

    def _make_float32_working_copy(self):
        base = self._signal
        try:
            work = base.deepcopy()
        except Exception:
            work = base.copy()
        work.change_dtype("float32")
        try:
            work.metadata.General.title = f"{self._signal_title()} (float32 copy)"
        except Exception:
            pass
        return work

    # ── Run decomposition ─────────────────────────────────────────────────────

    def _on_run(self):
        try:
            algo = self._algo_combo.currentText()
            n = self._ncomp_spin.value()
            kw = {"algorithm": algo}
            if n > 0:
                kw["output_dimension"] = n

            target_sig = self._signal
            used_float32_copy = False
            if self._float32_copy_cb.isChecked():
                target_sig = self._make_float32_working_copy()
                used_float32_copy = True

            self._run_btn.setEnabled(False)
            self._status_lbl.setText("Running decomposition…")
            QApplication.processEvents()

            target_sig.decomposition(**kw)
            self._pca_signal = target_sig
            self._decomposed = True

            try:
                var = np.array(self._analysis_signal().learning_results.explained_variance_ratio)
                self._n_components_computed = len(var)
            except Exception:
                self._n_components_computed = 0

            msg = f"Done. {self._n_components_computed} component(s) computed."
            if used_float32_copy:
                msg += " (float32 working copy)"
            self._status_lbl.setText(msg)

            cap = max(1, self._n_components_computed)
            self._nsig_spin.setMaximum(cap)
            self._viz_ncomp_spin.setMaximum(cap)
            self._viz_ncomp_spin.setValue(min(10, cap))

            self._comp_grp.setEnabled(True)
            self._viz_grp.setEnabled(True)
            self._export_grp.setEnabled(True)

            self._draw_scree()

        except Exception as e:
            self._status_lbl.setText(f"Error: {e}")
            msg = f"Decomposition failed:\n{e}"
            err_txt = str(e).lower()
            if (
                ("float or complex" in err_txt or "change_dtype" in err_txt)
                and not self._float32_copy_cb.isChecked()
            ):
                msg += (
                    "\n\nTip: tick 'Use float32 working copy' and run again."
                )
            QMessageBox.critical(self, "PCA / Decomposition",
                                 msg)
        finally:
            self._run_btn.setEnabled(True)

    # ── Scree plot ────────────────────────────────────────────────────────────

    def _draw_scree(self):
        try:
            _pfc = self._config.get("plot_facecolor", "#12121e") if self._config else "#12121e"
            _pt = _plot_theme(_pfc)
            var = np.array(self._analysis_signal().learning_results.explained_variance_ratio)
            self._ax_scree.clear()
            self._ax_scree.set_facecolor(_pfc)
            self._fig.set_facecolor(_pfc)
            x = np.arange(len(var))
            self._ax_scree.plot(x, var, "o", color=_pt["line"],
                                markersize=5, markeredgewidth=0)
            self._ax_scree.set_title("Scree plot — explained variance ratio",
                                     color=_pt["title"])
            self._ax_scree.set_xlabel("Component index", color=_pt["label"])
            self._ax_scree.set_ylabel("Variance ratio", color=_pt["label"])
            self._ax_scree.tick_params(colors=_pt["tick"])
            self._ax_scree.set_xlim(-0.5, len(var) - 0.5)
            self._ax_scree.set_yscale("log")
            self._ax_scree.grid(True, which="both", linestyle="--",
                                color=_pt["grid"], alpha=0.5, linewidth=0.6)
            self._fig.tight_layout()
            self._canvas.draw()
        except Exception as e:
            self._status_lbl.setText(f"Scree plot error: {e}")

    # ── Visualise ─────────────────────────────────────────────────────────────

    def _on_plot_factors(self):
        if not self._decomposed:
            return
        n = self._viz_ncomp_spin.value()
        try:
            import matplotlib.pyplot as plt
            analysis_signal = self._analysis_signal()
            factors = analysis_signal.get_decomposition_factors()
            try:
                sig_ax = analysis_signal.axes_manager.signal_axes[-1]
                e_axis = sig_ax.axis
                ax_name = str(getattr(sig_ax, "name", "") or "index")
                ax_units = str(getattr(sig_ax, "units", "") or "")
                xlabel = f"{ax_name} ({ax_units})" if ax_units else ax_name
            except Exception:
                e_axis = None
                xlabel = "index"

            try:
                variance = np.array(
                    analysis_signal.learning_results.explained_variance_ratio
                )
            except Exception:
                variance = None

            fdata = factors.data if hasattr(factors, "data") else np.array(factors)
            actual_n = min(n, len(fdata))

            fig, axes = plt.subplots(actual_n, 1,
                                     figsize=(8, actual_n * 2), sharex=True)
            if actual_n == 1:
                axes = [axes]
            for i, ax in enumerate(axes):
                y = fdata[i]
                x = e_axis if e_axis is not None else np.arange(len(y))
                ax.plot(x, y, color="tab:blue", lw=1.2)
                ax.axhline(0, color="gray", lw=0.8, linestyle="--")
                ax.set_ylabel(f"PC{i}", fontsize=9)
                var_txt = (f"  var={variance[i]*100:.2f}%"
                           if variance is not None and i < len(variance) else "")
                ax.set_title(f"Factor {i}{var_txt}", fontsize=9)
                ax.tick_params(labelsize=8)
            axes[-1].set_xlabel(xlabel, fontsize=11)
            fig.suptitle(f"PCA Factors — {self._signal_title()}", fontsize=12, y=0.98)
            fig.tight_layout(rect=[0, 0, 1, 0.93])
            self.figure_ready.emit(fig, f"PCA Factors — {self._signal_title()}")
        except Exception as e:
            QMessageBox.warning(self, "PCA", f"Plot factors failed:\n{e}")

    def _on_plot_loadings(self):
        if not self._decomposed:
            return
        n = self._viz_ncomp_spin.value()
        try:
            import matplotlib.pyplot as plt
            analysis_signal = self._analysis_signal()
            loadings = analysis_signal.get_decomposition_loadings()
            try:
                variance = np.array(
                    analysis_signal.learning_results.explained_variance_ratio
                )
            except Exception:
                variance = None

            ldata = loadings.data if hasattr(loadings, "data") else np.array(loadings)
            actual_n = min(n, len(ldata))

            ncols = min(5, actual_n)
            nrows = int(np.ceil(actual_n / ncols))
            fig, axes = plt.subplots(nrows, ncols,
                                     figsize=(ncols * 3, nrows * 3))
            axes_flat = np.array(axes).flatten() if actual_n > 1 else [axes]
            for i in range(actual_n):
                ax = axes_flat[i]
                im = ax.imshow(ldata[i], cmap="RdBu_r", aspect="auto")
                var_txt = (f"  var={variance[i]*100:.2f}%"
                           if variance is not None and i < len(variance) else "")
                ax.set_title(f"Loading {i}{var_txt}", fontsize=9)
                ax.axis("off")
                plt.colorbar(im, ax=ax, shrink=0.8)
            for j in range(actual_n, len(axes_flat)):
                axes_flat[j].set_visible(False)
            fig.suptitle(f"PCA Loadings — {self._signal_title()}", fontsize=12, y=0.98)
            fig.tight_layout(rect=[0, 0, 1, 0.93])
            self.figure_ready.emit(fig, f"PCA Loadings — {self._signal_title()}")
        except Exception as e:
            QMessageBox.warning(self, "PCA", f"Plot loadings failed:\n{e}")

    # ── Export ────────────────────────────────────────────────────────────────

    def _build_denoised_noise(self):
        analysis_signal = self._analysis_signal()
        n_sig = self._nsig_spin.value()
        denoised = analysis_signal.get_decomposition_model(components=n_sig)
        try:
            denoised.metadata.General.title = (
                f"{self._signal_title()} denoised ({n_sig} comp)"
            )
        except Exception:
            pass

        noise = analysis_signal - denoised
        try:
            noise.metadata.General.title = (
                f"{self._signal_title()} noise (>{n_sig} comp)"
            )
        except Exception:
            pass

        try:
            sig_type = self._signal.metadata.Signal.signal_type
            if sig_type:
                denoised.set_signal_type(sig_type)
                noise.set_signal_type(sig_type)
        except Exception:
            pass

        return denoised, noise

    def _on_export_denoised(self):
        if not self._decomposed:
            return
        try:
            denoised, _ = self._build_denoised_noise()
            base = self._out_name_edit.text().strip() or self._signal_title()
            self.pca_export_requested.emit([denoised], f"{base} — denoised")
        except Exception as e:
            QMessageBox.critical(self, "PCA Export",
                                 f"Export denoised failed:\n{e}")

    def _on_export_noise(self):
        if not self._decomposed:
            return
        try:
            _, noise = self._build_denoised_noise()
            base = self._out_name_edit.text().strip() or self._signal_title()
            self.pca_export_requested.emit([noise], f"{base} — noise")
        except Exception as e:
            QMessageBox.critical(self, "PCA Export",
                                 f"Export noise failed:\n{e}")


class RetractBackgroundWidget(QWidget):
    """Interactive background-retraction panel for any Signal1D.

    Layout
    ------
    * **Left**  – Matplotlib canvas: mean spectrum (red), fitted background
                  (blue dashed), and background-subtracted preview (green).
                  An orange SpanSelector lets the user choose the pre-edge
                  fitting range.
    * **Right** – Options panel: background model, polynomial order,
                  fast / zero_fill checkboxes, output name, and Extract button.
    """

    extract_requested = pyqtSignal(object, str)   # (result_signal, output_name)

    BG_TYPES = [
        ("Power Law",   "PowerLaw"),
        ("Polynomial",  "Polynomial"),
        ("Exponential", "Exponential"),
        ("Gaussian",    "Gaussian"),
        ("Offset",      "Offset"),
    ]

    def __init__(self, signal, title: str = "", config=None, parent=None):
        super().__init__(parent)
        self.signal  = signal
        self._title  = title
        self._config = config

        am = signal.axes_manager
        self._sig_axis = am.signal_axes[0]
        self._nav_ndim = am.navigation_dimension

        off = float(getattr(self._sig_axis, "offset", 0.0) or 0.0)
        sc  = float(getattr(self._sig_axis, "scale",  1.0) or 1.0)
        n   = int(self._sig_axis.size)
        self._energy = off + sc * np.arange(n)
        self._units  = str(getattr(self._sig_axis, "units", "eV") or "eV")
        self._off    = off
        self._sc     = sc

        if self._nav_ndim > 0:
            nav_axes_in_array = tuple(range(self._nav_ndim))
            self._mean_spec = np.mean(signal.data, axis=nav_axes_in_array).astype(float)
        else:
            self._mean_spec = np.asarray(signal.data, dtype=float).ravel()

        e_min   = float(self._energy[0])
        e_max   = float(self._energy[-1])
        e_range = max(e_max - e_min, 1.0)
        self._span_left  = e_min + e_range * 0.05
        self._span_right = e_min + e_range * 0.40

        self._line_orig   = None
        self._line_bg     = None
        self._line_result = None

        self._setup_ui()
        self._update_preview()

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _section_label(text: str, color: str = "#c0c8e0") -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"font-weight:bold; color:{color}; margin-top:4px;")
        return lbl

    @staticmethod
    def _hsep(color: str = "#444466") -> QLabel:
        sep = QLabel()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background:{color}; margin:2px 0;")
        return sep

    # ── UI ────────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        from matplotlib.widgets import SpanSelector

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Left: canvas ──────────────────────────────────────────────────────
        _pfc = self._config.get("plot_facecolor", "#12121e") if self._config else "#12121e"
        _t = _plot_theme(_pfc)
        _fs = int(self._config.get("panel_font_size", 11)) if self._config else 11

        _pbg  = self._config.get("panel_bg",   "#1a1a2e") if self._config else "#1a1a2e"
        _ptxt = self._config.get("panel_text", "#d7def6") if self._config else "#d7def6"

        canvas_col = QVBoxLayout()
        canvas_col.setContentsMargins(0, 0, 0, 0)
        canvas_col.setSpacing(0)

        self.figure = Figure(facecolor=_pfc)
        self.canvas = FigureCanvasQTAgg(self.figure)
        toolbar     = NavigationToolbar2QT(self.canvas, self)
        canvas_col.addWidget(toolbar)
        canvas_col.addWidget(self.canvas)

        canvas_wrap = QWidget()
        canvas_wrap.setLayout(canvas_col)
        root.addWidget(canvas_wrap, 1)

        # ── Right: control panel ───────────────────────────────────────────────
        ctrl = QWidget()
        ctrl.setFixedWidth(290)
        ctrl.setStyleSheet(
            f"background:{_pbg}; color:{_ptxt}; font-size:{_fs}px;"
        )
        ctrl_col = QVBoxLayout(ctrl)
        ctrl_col.setContentsMargins(10, 14, 10, 10)
        ctrl_col.setSpacing(6)

        # background model
        ctrl_col.addWidget(self._section_label("Background Model", _ptxt))
        self._bg_combo = QComboBox()
        for label, key in self.BG_TYPES:
            self._bg_combo.addItem(label, userData=key)
        ctrl_col.addWidget(self._bg_combo)

        # polynomial order
        poly_row = QHBoxLayout()
        poly_row.setSpacing(6)
        poly_row.addWidget(QLabel("Polynomial order:"))
        self._poly_spin = QSpinBox()
        self._poly_spin.setRange(1, 10)
        self._poly_spin.setValue(2)
        self._poly_spin.setFixedWidth(60)
        self._poly_spin.setEnabled(False)
        poly_row.addWidget(self._poly_spin)
        poly_row.addStretch()
        ctrl_col.addLayout(poly_row)

        ctrl_col.addWidget(self._hsep(_t["grid"]))
        ctrl_col.addWidget(self._section_label("Options", _ptxt))

        self._fast_cb = QCheckBox("fast  (analytical approximation)")
        self._fast_cb.setChecked(True)
        ctrl_col.addWidget(self._fast_cb)

        self._zero_fill_cb = QCheckBox("zero_fill  (set pre-edge to 0)")
        self._zero_fill_cb.setChecked(False)
        ctrl_col.addWidget(self._zero_fill_cb)

        ctrl_col.addWidget(self._hsep(_t["grid"]))
        ctrl_col.addWidget(self._section_label("Output dataset name", _ptxt))
        self._name_edit = QLineEdit()
        try:
            _default = f"{SignalPlotWidget._safe_title(self.signal)} (bg removed)"
        except Exception:
            _default = "signal (bg removed)"
        self._name_edit.setPlaceholderText(_default)
        ctrl_col.addWidget(self._name_edit)

        ctrl_col.addStretch(1)

        self._btn_extract = QPushButton("Extract")
        self._btn_extract.setFixedHeight(32)
        self._btn_extract.setStyleSheet(
            "QPushButton {"
            "  background: #1e3a5f;"
            "  color: #f4a261;"
            "  border: 2px solid #f4a261;"
            "  border-radius: 3px;"
            "  font-weight: bold;"
            "  font-size: 13px;"
            "}"
            "QPushButton:hover { background: #2a5080; }"
            "QPushButton:pressed { background: #0e2040; }"
        )
        self._btn_extract.clicked.connect(self._on_extract)
        ctrl_col.addWidget(self._btn_extract)

        root.addWidget(ctrl)

        # ── Matplotlib single axes ─────────────────────────────────────────────
        gs = self.figure.add_gridspec(
            1, 1,
            left=0.09, right=0.97, top=0.90, bottom=0.12,
        )
        self._ax = self.figure.add_subplot(gs[0])
        self._ax.set_facecolor(_t["ax_fc"])
        self._ax.tick_params(colors=_t["tick"], labelsize=8)
        for sp in self._ax.spines.values():
            sp.set_edgecolor(_t["grid"])

        e_pad = (self._energy[-1] - self._energy[0]) * 0.02
        self._ax.set_xlim(self._energy[0] - e_pad, self._energy[-1] + e_pad)

        (self._line_orig,) = self._ax.plot(
            self._energy, self._mean_spec,
            color="#ef476f", linewidth=0.9, alpha=0.92, label="Original (mean)",
        )
        (self._line_bg,) = self._ax.plot(
            self._energy, np.zeros_like(self._mean_spec),
            color="#7ec8e3", linewidth=1.2, linestyle="--",
            label="BG fit", visible=False,
        )
        (self._line_result,) = self._ax.plot(
            self._energy, np.zeros_like(self._mean_spec),
            color="#a0e88f", linewidth=0.9,
            label="BG subtracted", visible=False,
        )
        self._ax.set_xlabel(f"Energy ({self._units})", color=_t["label"], fontsize=8)
        self._ax.set_ylabel("Counts", color=_t["label"], fontsize=8)
        self._ax.set_title(
            "Drag span to set pre-edge fitting range  "
            "(red = original  |  blue dashed = BG fit  |  green = subtracted)",
            color=_t["title"], fontsize=8,
        )
        self._ax.legend(
            fontsize=7, facecolor=_pfc,
            edgecolor=_t["grid"], labelcolor=_t["label"],
        )

        self._span_selector = SpanSelector(
            self._ax,
            self._on_span_select,
            direction="horizontal",
            useblit=True,
            props=dict(
                alpha=0.25, facecolor="#f4a261",
                edgecolor="#f4a261", linewidth=1.0,
            ),
            interactive=True,
            drag_from_anywhere=True,
        )
        self._span_selector.extents = (self._span_left, self._span_right)

        # Connect live-preview triggers
        self._bg_combo.currentIndexChanged.connect(self._on_bg_type_changed)
        self._bg_combo.currentIndexChanged.connect(self._on_option_changed)
        self._poly_spin.valueChanged.connect(self._on_option_changed)
        self._fast_cb.stateChanged.connect(self._on_option_changed)
        self._zero_fill_cb.stateChanged.connect(self._on_option_changed)

    # ── callbacks ─────────────────────────────────────────────────────────────

    def _on_bg_type_changed(self, _=None):
        is_poly = self._bg_combo.currentData() == "Polynomial"
        self._poly_spin.setEnabled(is_poly)

    def _on_span_select(self, left: float, right: float):
        if abs(right - left) < abs(self._sc) * 0.5:
            return
        self._span_left  = float(left)
        self._span_right = float(right)
        self._update_preview()

    def _on_option_changed(self, _=None):
        self._update_preview()

    # ── preview ───────────────────────────────────────────────────────────────

    def _build_remove_kwargs(self, fast_override=None) -> dict:
        bg_type = self._bg_combo.currentData()
        kw = dict(
            signal_range=(float(self._span_left), float(self._span_right)),
            background_type=bg_type,
            fast=self._fast_cb.isChecked() if fast_override is None else fast_override,
            zero_fill=self._zero_fill_cb.isChecked(),
            show_progressbar=False,
        )
        if bg_type == "Polynomial":
            kw["polynomial_order"] = self._poly_spin.value()
        return kw

    def _update_preview(self):
        """Run remove_background on a temporary 1-D mean spectrum and refresh plot."""
        try:
            import hyperspy.api as hs
            kw = self._build_remove_kwargs(fast_override=True)  # always fast for preview
            tmp = hs.signals.Signal1D(self._mean_spec.copy())
            tmp.axes_manager.signal_axes[0].offset = float(self._off)
            tmp.axes_manager.signal_axes[0].scale  = float(self._sc)
            tmp.axes_manager.signal_axes[0].units  = self._units
            result = tmp.remove_background(**kw)
            if result is not None:
                res_data = np.asarray(result.data, dtype=float).ravel()
                bg_data  = self._mean_spec - res_data
                self._line_bg.set_ydata(bg_data)
                self._line_bg.set_visible(True)
                self._line_result.set_ydata(res_data)
                self._line_result.set_visible(True)
                all_y = np.concatenate([self._mean_spec, bg_data, res_data])
                mn, mx = float(np.nanmin(all_y)), float(np.nanmax(all_y))
                pad = (mx - mn) * 0.05 or 1.0
                self._ax.set_ylim(mn - pad, mx + pad)
            else:
                self._line_bg.set_visible(False)
                self._line_result.set_visible(False)
        except Exception:
            self._line_bg.set_visible(False)
            self._line_result.set_visible(False)
        finally:
            self.canvas.draw_idle()

    # ── extract ───────────────────────────────────────────────────────────────

    def _output_name(self) -> str:
        txt = self._name_edit.text().strip()
        return txt if txt else (self._name_edit.placeholderText() or "signal (bg removed)")

    def _on_extract(self):
        """Run remove_background on the full signal and emit the result."""
        kw = self._build_remove_kwargs()
        try:
            result = self.signal.remove_background(**kw)
        except Exception as e:
            err_msg = str(e)
            low = err_msg.lower()
            if any(k in low for k in ("unset", "nan", "singular", "not converge")):
                detail = (
                    "The background fit failed — likely because some pixels in the "
                    "fitting range contain zero or negative counts (common in vacuum "
                    "regions of a 2-D map), or the data is too noisy to converge.\n\n"
                    "Suggestions:\n"
                    "  \u2022 Move the fitting span to a cleaner pre-edge region.\n"
                    "  \u2022 Try a different background model (e.g. Polynomial).\n"
                    "  \u2022 Uncheck \u2018fast\u2019 for a full NLLS fit.\n\n"
                    f"Original error:\n{err_msg}"
                )
            elif any(k in low for k in ("negative", "log", "positive")):
                detail = (
                    "Background fit failed: non-positive (zero or negative) counts "
                    "were found inside the fitting range.\n\n"
                    "Power Law fitting works in log-log space and requires strictly "
                    "positive values.  Try:\n"
                    "  \u2022 Choosing a fitting span that avoids zero/negative channels.\n"
                    "  \u2022 Switching to Polynomial background type.\n\n"
                    f"Original error:\n{err_msg}"
                )
            else:
                detail = f"Background removal failed:\n\n{err_msg}"
            QMessageBox.critical(self, "Retract Background \u2014 Extraction Failed", detail)
            return

        if result is None:
            QMessageBox.warning(
                self,
                "Retract Background",
                "remove_background returned no signal.\n"
                "Check that the fitting span lies within the signal energy axis.",
            )
            return

        out_name = self._output_name()
        try:
            result.metadata.General.title = out_name
        except Exception:
            pass
        try:
            orig_type = self.signal.metadata.Signal.signal_type
            if orig_type:
                result.set_signal_type(orig_type)
        except Exception:
            pass

        self.extract_requested.emit(result, out_name)


# ─────────────────────────────────────────────────────────────────────────────
class DeconvolutionWidget(QWidget):
    """Interactive EELS deconvolution panel.

    Layout
    ------
    * **Left**  – Matplotlib canvas: mean original spectrum (red) and, after
                  running deconvolution, the result overlay (green).
    * **Right** – Options panel: algorithm selector, reference signal picker,
                  algorithm-specific parameters, output name, and Run button.
    """

    deconvolution_done = pyqtSignal(object, str)   # (result_signal, output_name)

    METHODS = [
        ("Fourier-Log",     "fourier_log"),
        ("Fourier-Ratio",   "fourier_ratio"),
        ("Richardson-Lucy", "richardson_lucy"),
    ]

    def __init__(self, signal, available_signals, title: str = "",
                 config=None, parent=None):
        super().__init__(parent)
        self.signal          = signal
        self._avail          = available_signals   # list of (label, sig)
        self._title          = title
        self._config         = config
        self._result_signal  = None

        am               = signal.axes_manager
        self._sig_axis   = am.signal_axes[0]
        nav_ndim         = am.navigation_dimension

        off = float(getattr(self._sig_axis, "offset", 0.0) or 0.0)
        sc  = float(getattr(self._sig_axis, "scale",  1.0) or 1.0)
        n   = int(self._sig_axis.size)
        self._energy = off + sc * np.arange(n)
        self._units  = str(getattr(self._sig_axis, "units", "eV") or "eV")

        if nav_ndim > 0:
            nav_axes = tuple(range(nav_ndim))
            self._mean_spec = np.mean(signal.data, axis=nav_axes).astype(float)
        else:
            self._mean_spec = np.asarray(signal.data, dtype=float).ravel()

        self._setup_ui()

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _section_label(text: str, color: str = "#c0c8e0") -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"font-weight:bold; color:{color}; margin-top:4px;")
        return lbl

    @staticmethod
    def _hsep(color: str = "#444466") -> QLabel:
        sep = QLabel()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background:{color}; margin:2px 0;")
        return sep

    # ── UI ────────────────────────────────────────────────────────────────────

    def _setup_ui(self):
        _pfc  = self._config.get("plot_facecolor", "#12121e") if self._config else "#12121e"
        _t    = _plot_theme(_pfc)
        _fs   = int(self._config.get("panel_font_size", 11)) if self._config else 11
        _pbg  = self._config.get("panel_bg",   "#1a1a2e") if self._config else "#1a1a2e"
        _ptxt = self._config.get("panel_text", "#d7def6") if self._config else "#d7def6"

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Left: canvas ──────────────────────────────────────────────────────
        canvas_col = QVBoxLayout()
        canvas_col.setContentsMargins(0, 0, 0, 0)
        canvas_col.setSpacing(0)

        self.figure = Figure(facecolor=_pfc)
        self.canvas = FigureCanvasQTAgg(self.figure)
        toolbar     = NavigationToolbar2QT(self.canvas, self)
        canvas_col.addWidget(toolbar)
        canvas_col.addWidget(self.canvas)

        canvas_wrap = QWidget()
        canvas_wrap.setLayout(canvas_col)
        root.addWidget(canvas_wrap, 1)

        # ── Right: control panel ───────────────────────────────────────────────
        ctrl = QWidget()
        ctrl.setFixedWidth(310)
        ctrl.setStyleSheet(
            f"background:{_pbg}; color:{_ptxt}; font-size:{_fs}px;"
        )
        ctrl_col = QVBoxLayout(ctrl)
        ctrl_col.setContentsMargins(10, 14, 10, 10)
        ctrl_col.setSpacing(6)

        # Method selection
        ctrl_col.addWidget(self._section_label("Deconvolution Method", _ptxt))
        self._method_combo = QComboBox()
        for label, key in self.METHODS:
            self._method_combo.addItem(label, userData=key)
        ctrl_col.addWidget(self._method_combo)

        ctrl_col.addWidget(self._hsep(_t["grid"]))

        # Reference signal
        self._ref_label = QLabel("ZLP signal:")
        ctrl_col.addWidget(self._ref_label)
        self._ref_combo = QComboBox()
        self._ref_combo.addItem("— none —", userData=None)
        for label, sig in self._avail:
            self._ref_combo.addItem(label, userData=sig)
        ctrl_col.addWidget(self._ref_combo)

        ctrl_col.addWidget(self._hsep(_t["grid"]))

        # ── Algorithm-specific parameters (stacked) ───────────────────────────
        self._params_stack = QStackedWidget()
        self._params_stack.setStyleSheet(
            f"background:{_pbg}; color:{_ptxt};"
        )

        # Page 0 — Fourier-Log
        p0        = QWidget()
        p0_layout = QVBoxLayout(p0)
        p0_layout.setContentsMargins(0, 0, 0, 0)
        p0_layout.setSpacing(4)
        self._fl_add_zlp = QCheckBox("add_zlp  (include ZLP in output)")
        self._fl_add_zlp.setChecked(False)
        p0_layout.addWidget(self._fl_add_zlp)
        self._fl_crop = QCheckBox("crop  (trim modified edge channels)")
        self._fl_crop.setChecked(False)
        p0_layout.addWidget(self._fl_crop)
        p0_layout.addStretch()
        self._params_stack.addWidget(p0)

        # Page 1 — Fourier-Ratio
        p1        = QWidget()
        p1_layout = QFormLayout(p1)
        p1_layout.setContentsMargins(0, 0, 0, 0)
        p1_layout.setSpacing(4)
        self._fr_fwhm = QDoubleSpinBox()
        self._fr_fwhm.setRange(0.0, 9999.0)
        self._fr_fwhm.setValue(0.0)
        self._fr_fwhm.setSpecialValueText("auto (None)")
        self._fr_fwhm.setDecimals(3)
        self._fr_fwhm.setToolTip(
            "FWHM of Gaussian smoothing applied to the deconvolution result (eV).\n"
            "0 = auto-estimate from ZLP."
        )
        p1_layout.addRow("fwhm (eV):", self._fr_fwhm)
        self._fr_threshold = QDoubleSpinBox()
        self._fr_threshold.setRange(0.0, 9999.0)
        self._fr_threshold.setValue(0.0)
        self._fr_threshold.setSpecialValueText("auto (None)")
        self._fr_threshold.setDecimals(3)
        self._fr_threshold.setToolTip(
            "Truncation energy to estimate elastic-scattering intensity (eV).\n"
            "0 = auto (first minimum after ZLP centre)."
        )
        p1_layout.addRow("threshold (eV):", self._fr_threshold)
        self._fr_extrap_ll = QCheckBox("extrapolate_lowloss")
        self._fr_extrap_ll.setChecked(True)
        p1_layout.addRow(self._fr_extrap_ll)
        self._fr_extrap_cl = QCheckBox("extrapolate_coreloss")
        self._fr_extrap_cl.setChecked(True)
        p1_layout.addRow(self._fr_extrap_cl)
        self._params_stack.addWidget(p1)

        # Page 2 — Richardson-Lucy
        p2        = QWidget()
        p2_layout = QFormLayout(p2)
        p2_layout.setContentsMargins(0, 0, 0, 0)
        p2_layout.setSpacing(4)
        self._rl_iterations = QSpinBox()
        self._rl_iterations.setRange(1, 1000)
        self._rl_iterations.setValue(15)
        self._rl_iterations.setToolTip(
            "Number of Richardson-Lucy iterations.\n"
            "Higher values increase noise amplification."
        )
        p2_layout.addRow("iterations:", self._rl_iterations)
        self._params_stack.addWidget(p2)

        ctrl_col.addWidget(self._params_stack)
        ctrl_col.addWidget(self._hsep(_t["grid"]))

        # Output name
        ctrl_col.addWidget(self._section_label("Output dataset name", _ptxt))
        self._name_edit = QLineEdit()
        try:
            _default = f"{SignalPlotWidget._safe_title(self.signal)} (deconvolved)"
        except Exception:
            _default = "signal (deconvolved)"
        self._name_edit.setPlaceholderText(_default)
        ctrl_col.addWidget(self._name_edit)

        ctrl_col.addStretch(1)

        self._btn_run = QPushButton("Run Deconvolution")
        self._btn_run.setFixedHeight(32)
        self._btn_run.setStyleSheet(
            "QPushButton {"
            "  background: #1e3a5f;"
            "  color: #f4a261;"
            "  border: 2px solid #f4a261;"
            "  border-radius: 3px;"
            "  font-weight: bold;"
            "  font-size: 13px;"
            "}"
            "QPushButton:hover { background: #2a5080; }"
            "QPushButton:pressed { background: #0e2040; }"
        )
        self._btn_run.clicked.connect(self._on_run)
        ctrl_col.addWidget(self._btn_run)

        root.addWidget(ctrl)

        # ── Matplotlib axes ────────────────────────────────────────────────────
        gs = self.figure.add_gridspec(
            1, 1,
            left=0.09, right=0.97, top=0.90, bottom=0.12,
        )
        self._ax = self.figure.add_subplot(gs[0])
        self._ax.set_facecolor(_t["ax_fc"])
        self._ax.tick_params(colors=_t["tick"], labelsize=8)
        for sp in self._ax.spines.values():
            sp.set_edgecolor(_t["grid"])

        e_pad = (self._energy[-1] - self._energy[0]) * 0.02
        self._ax.set_xlim(self._energy[0] - e_pad, self._energy[-1] + e_pad)

        (self._line_orig,) = self._ax.plot(
            self._energy, self._mean_spec,
            color="#ef476f", linewidth=0.9, alpha=0.92, label="Original (mean)",
        )
        (self._line_result,) = self._ax.plot(
            self._energy, np.zeros_like(self._mean_spec),
            color="#a0e88f", linewidth=0.9,
            label="Deconvolved", visible=False,
        )
        self._ax.set_xlabel(f"Energy ({self._units})", color=_t["label"], fontsize=8)
        self._ax.set_ylabel("Counts",                   color=_t["label"], fontsize=8)
        self._ax.set_title(
            f"EELS Deconvolution — {self._title}" if self._title else "EELS Deconvolution",
            color=_t["title"], fontsize=8,
        )
        # Store theme colors so _on_run can refresh the legend after result appears
        self._legend_kw = dict(
            fontsize=7, facecolor=_pfc,
            edgecolor=_t["grid"], labelcolor=_t["label"],
        )
        # Pass explicit handles so both entries show even before deconvolution runs
        self._ax.legend(
            handles=[self._line_orig, self._line_result],
            **self._legend_kw,
        )

        # Connect
        self._method_combo.currentIndexChanged.connect(self._on_method_changed)
        self._on_method_changed(0)
        self.canvas.draw()

    # ── slots ─────────────────────────────────────────────────────────────────

    def _on_method_changed(self, index: int):
        self._params_stack.setCurrentIndex(index)
        method_key = self._method_combo.currentData()
        labels = {
            "fourier_log":     "ZLP signal:",
            "fourier_ratio":   "Low-loss signal:",
            "richardson_lucy": "PSF signal:",
        }
        self._ref_label.setText(labels.get(method_key, "Reference signal:"))

    def _on_run(self):
        method_key = self._method_combo.currentData()
        ref_sig    = self._ref_combo.currentData()

        if ref_sig is None:
            QMessageBox.warning(
                self, "Deconvolution",
                "Please select a reference signal from the dropdown."
            )
            return

        try:
            import exspy.signals as _exspy
        except ImportError:
            QMessageBox.critical(
                self, "Deconvolution",
                "exspy is not installed. Install it with:\n  pip install exspy"
            )
            return

        # Check if either signal has integer dtype and ask the user before converting
        def _needs_float_cast(s):
            return np.issubdtype(np.asarray(s.data).dtype, np.integer)

        if _needs_float_cast(self.signal) or _needs_float_cast(ref_sig):
            sig_dtype  = np.asarray(self.signal.data).dtype
            ref_dtype  = np.asarray(ref_sig.data).dtype
            detail     = []
            if _needs_float_cast(self.signal):
                detail.append(f"• Main signal: {sig_dtype}")
            if _needs_float_cast(ref_sig):
                detail.append(f"• Reference signal: {ref_dtype}")
            detail_str = "\n".join(detail)

            msg = QMessageBox(self)
            msg.setWindowTitle("Deconvolution — Integer Data Detected")
            msg.setIcon(QMessageBox.Warning)
            msg.setText(
                "Deconvolution requires floating-point data, but the following "
                "signal(s) have integer dtype:\n\n"
                f"{detail_str}\n\n"
                "Convert to floating-point to continue?"
            )
            btn_f64    = msg.addButton("Convert to float64", QMessageBox.AcceptRole)
            btn_f32    = msg.addButton("Convert to float32", QMessageBox.AcceptRole)
            btn_cancel = msg.addButton("Cancel",             QMessageBox.RejectRole)
            msg.setDefaultButton(btn_f64)
            msg.exec_()

            clicked = msg.clickedButton()
            if clicked is btn_cancel:
                return
            float_dtype = np.float64 if clicked is btn_f64 else np.float32
        else:
            float_dtype = None   # no conversion needed; keep original dtype

        def _as_eels(s):
            """Return an EELSSpectrum with guaranteed float data."""
            # Use astype(copy=True) so the new array is always independent of the
            # original signal's buffer – HyperSpy cannot write back into integer data.
            if float_dtype is not None:
                data = s.data.astype(float_dtype, copy=True)
            else:
                data = np.array(s.data)   # plain copy, preserves float dtype

            axes_dicts = [ax.get_axis_dictionary()
                          for ax in s.axes_manager._axes]

            # First try: build a fresh EELSSpectrum from scratch
            try:
                return _exspy.EELSSpectrum(data, axes=axes_dicts)
            except Exception:
                pass

            # Second try: Signal1D path – avoids axes metadata quirks
            try:
                import hyperspy.api as _hs
                sig2 = _hs.signals.Signal1D(data, axes=axes_dicts)
                sig2.set_signal_type("EELS")
                return sig2
            except Exception as _e:
                raise RuntimeError(
                    f"Could not prepare signal for deconvolution.\n"
                    f"dtype requested: {float_dtype} — error: {_e}"
                )

        sig = _as_eels(self.signal)
        ref = _as_eels(ref_sig)

        self._btn_run.setEnabled(False)
        self._btn_run.setText("Running…")
        QApplication.processEvents()
        try:
            if method_key == "fourier_log":
                add_zlp = self._fl_add_zlp.isChecked()
                crop    = self._fl_crop.isChecked()
                result  = sig.fourier_log_deconvolution(ref, add_zlp=add_zlp, crop=crop)

            elif method_key == "fourier_ratio":
                fwhm      = self._fr_fwhm.value()      or None
                threshold = self._fr_threshold.value() or None
                result = sig.fourier_ratio_deconvolution(
                    ref,
                    fwhm=fwhm,
                    threshold=threshold,
                    extrapolate_lowloss=self._fr_extrap_ll.isChecked(),
                    extrapolate_coreloss=self._fr_extrap_cl.isChecked(),
                )

            elif method_key == "richardson_lucy":
                result = sig.richardson_lucy_deconvolution(
                    ref, iterations=self._rl_iterations.value()
                )
            else:
                return
        except Exception as exc:
            QMessageBox.critical(
                self, "Deconvolution",
                f"Deconvolution failed:\n{exc}"
            )
            return
        finally:
            self._btn_run.setEnabled(True)
            self._btn_run.setText("Run Deconvolution")

        self._result_signal = result

        # Update canvas
        nav_ndim = result.axes_manager.navigation_dimension
        if nav_ndim > 0:
            r_mean = np.mean(result.data, axis=tuple(range(nav_ndim))).astype(float)
        else:
            r_mean = np.asarray(result.data, dtype=float).ravel()

        n = min(len(self._energy), len(r_mean))
        self._line_result.set_xdata(self._energy[:n])
        self._line_result.set_ydata(r_mean[:n])
        self._line_result.set_visible(True)
        self._ax.relim()
        self._ax.autoscale_view()
        # Refresh legend so the Deconvolved entry renders with the correct color
        self._ax.legend(
            handles=[self._line_orig, self._line_result],
            **self._legend_kw,
        )
        self.canvas.draw()

        # Emit to data list
        out_name = self._name_edit.text().strip() or self._name_edit.placeholderText()
        try:
            result.metadata.General.title = out_name
        except Exception:
            pass
        try:
            orig_type = self.signal.metadata.Signal.signal_type
            if orig_type:
                result.set_signal_type(orig_type)
        except Exception:
            pass
        self.deconvolution_done.emit(result, out_name)


class PlotManagerPanel(QWidget):
    """Floating panel listing all open MDI subwindows with focus/close controls."""

    def __init__(self, desktop: QMdiArea, parent=None):
        super().__init__(parent)
        self.desktop = desktop
        self.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setWindowTitle("Plot Manager")
        self.setMinimumWidth(340)
        self.resize(360, 400)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # Header row
        hdr = QHBoxLayout()
        self._count_label = QLabel("0 windows")
        self._count_label.setStyleSheet("font-weight:600;")
        hdr.addWidget(self._count_label, 1)
        btn_close_all = QPushButton("Close All")
        btn_close_all.setFixedHeight(24)
        btn_close_all.clicked.connect(self._close_all)
        hdr.addWidget(btn_close_all)
        root.addLayout(hdr)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        root.addWidget(sep)

        # Scrollable list
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._container = QWidget()
        self._list_layout = QVBoxLayout(self._container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(3)
        self._scroll.setWidget(self._container)
        root.addWidget(self._scroll)

        self.refresh()

    # ── public API ─────────────────────────────────────────────────────────

    def refresh(self):
        """Rebuild the window list from the current MDI subwindow state."""
        # Remove old rows
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        windows = self.desktop.subWindowList()
        n = len(windows)
        self._count_label.setText(f"{n} window{'s' if n != 1 else ''} open")

        if n == 0:
            lbl = QLabel("No plots open.")
            lbl.setStyleSheet("color:#888; padding:6px 2px;")
            self._list_layout.addWidget(lbl)
        else:
            for idx, sub in enumerate(windows, start=1):
                self._list_layout.addWidget(self._make_row(idx, sub))

        self._list_layout.addStretch()
        self.setWindowTitle(f"Plot Manager  ({n})")

    # ── private helpers ────────────────────────────────────────────────────

    def _make_row(self, idx: int, sub) -> QWidget:
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(4, 2, 4, 2)
        hl.setSpacing(6)

        num_lbl = QLabel(str(idx))
        num_lbl.setFixedWidth(20)
        num_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        num_lbl.setStyleSheet("color:#888; font-size:10px;")
        hl.addWidget(num_lbl)

        title = sub.windowTitle() or "(untitled)"
        lbl = QLabel(title)
        lbl.setMinimumWidth(150)
        lbl.setToolTip(title)
        hl.addWidget(lbl, 1)

        btn_focus = QPushButton("Focus")
        btn_focus.setFixedSize(50, 22)
        btn_focus.clicked.connect(lambda _checked, s=sub: self._focus(s))
        hl.addWidget(btn_focus)

        btn_close = QPushButton("✕")
        btn_close.setFixedSize(24, 22)
        btn_close.setToolTip("Close this window")
        btn_close.clicked.connect(lambda _checked, s=sub: self._close_one(s))
        hl.addWidget(btn_close)

        return row

    def _focus(self, sub):
        if sub in self.desktop.subWindowList():
            self.desktop.setActiveSubWindow(sub)
            sub.showNormal()
            sub.raise_()

    def _close_one(self, sub):
        if sub in self.desktop.subWindowList():
            sub.close()
        # refresh is triggered by ViewerWidget via subWindowActivated

    def _close_all(self):
        self.desktop.closeAllSubWindows()


class ViewerWidget(QWidget):
    """MDI desktop-style viewer for HyperSpy signals."""

    roi_state_changed = pyqtSignal(bool)
    elemental_map_exported = pyqtSignal(object, str)
    background_removed_exported = pyqtSignal(object, str)
    cropped_signals_exported = pyqtSignal(object, str)
    pca_exported = pyqtSignal(object, str)
    deconvolution_exported = pyqtSignal(object, str)

    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self.config = config
        self.current_signal = None
        self._annotation_tool = "none"
        self._annotation_color = "#ffb347"
        self._annotation_buttons = {}
        self._floating_panels = []
        self._plot_manager = None
        self._hs_roi = None
        self._hs_roi_targets = []
        # Multi-ROI: list of {"index": int, "roi": RectangularROI, "targets": [...] }
        self._multi_rois = []
        self._setup_ui()

    def update_styling(self, config):
        self.config = config
        if hasattr(self, "cmap_combo"):
            cmap = self.config.get("viewer_cmap", "gray")
            if cmap in CMAPS and self.cmap_combo.currentText() != cmap:
                self.cmap_combo.setCurrentText(cmap)
        if hasattr(self, "interpolation_combo"):
            interpolation = self.config.get("viewer_interpolation", "none")
            if interpolation in INTERPOLATIONS and self.interpolation_combo.currentText() != interpolation:
                self.interpolation_combo.setCurrentText(interpolation)
        self._apply_styling()

    def _apply_styling(self):
        if not self.config:
            return

        font_size = self.config.get("viewer_font_size", 11)
        text_color = self.config.get("viewer_text", "#000000")
        toolbar_bg = self.config.get("viewer_toolbar_bg", "#f0f0f0")

        toolbar_style = f"""
            QWidget {{ background: {toolbar_bg}; }}
            QLabel  {{ color: {text_color}; font-size: {font_size}px; padding: 2px 4px; }}
            QComboBox {{
                background: white;
                color: {text_color};
                border: 1px solid #ccc;
                border-radius: 3px;
                padding: 2px 6px; min-width: 90px; font-size: {font_size}px;
            }}
            QPushButton {{
                background: #007acc;
                color: white;
                border: 1px solid #007acc;
                border-radius: 3px;
                padding: 3px 10px; font-size: {font_size}px;
            }}
            QPushButton:hover {{ background: #005a9e; }}
            QToolButton {{
                background: white;
                color: {text_color};
                border: 1px solid #ccc;
                border-radius: 3px;
                padding: 2px;
                min-width: 22px;
                min-height: 22px;
                max-width: 22px;
                max-height: 22px;
                font-size: {font_size - 1}px;
            }}
            QToolButton:checked {{
                background: #007acc;
                color: white;
                border: 1px solid #007acc;
            }}
            QToolButton:hover {{ border-color: #007acc; }}
        """
        self.toolbar_row.setStyleSheet(toolbar_style)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.toolbar_row = QWidget()
        tr_layout = QHBoxLayout(self.toolbar_row)
        tr_layout.setContentsMargins(8, 4, 8, 4)
        tr_layout.setSpacing(10)

        self.title_label = QLabel("Viewer Desktop")
        self.title_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tr_layout.addWidget(self.title_label)

        tr_layout.addWidget(QLabel("Annotate:"))

        def _mk_anno_btn(text, tool_name, tooltip):
            btn = QToolButton(self.toolbar_row)
            btn.setText(text)
            btn.setCheckable(True)
            btn.setToolTip(tooltip)
            btn.setAutoRaise(False)
            btn.clicked.connect(lambda checked=False, t=tool_name: self._toggle_annotation_tool(t))
            self._annotation_buttons[tool_name] = btn
            tr_layout.addWidget(btn)

        _mk_anno_btn("T", "text", "Text annotation")
        _mk_anno_btn("/", "line", "Line annotation")
        _mk_anno_btn("[]", "rect", "Rectangle annotation")
        _mk_anno_btn("O", "oval", "Oval annotation")

        self.anno_color_btn = QToolButton(self.toolbar_row)
        self.anno_color_btn.setText("C")
        self.anno_color_btn.setToolTip("Annotation color")
        self.anno_color_btn.setStyleSheet(f"background:{self._annotation_color}; border:1px solid #555;")
        self.anno_color_btn.clicked.connect(self._choose_annotation_color)
        tr_layout.addWidget(self.anno_color_btn)

        tr_layout.addWidget(QLabel("Interpolation:"))
        self.interpolation_combo = QComboBox()
        self.interpolation_combo.addItems(INTERPOLATIONS)
        initial_interpolation = "none"
        if self.config:
            initial_interpolation = self.config.get("viewer_interpolation", "none")
        if initial_interpolation not in INTERPOLATIONS:
            initial_interpolation = "none"
        self.interpolation_combo.setCurrentText(initial_interpolation)
        self.interpolation_combo.currentTextChanged.connect(self._on_interpolation_changed)
        tr_layout.addWidget(self.interpolation_combo)

        tr_layout.addWidget(QLabel("Colormap:"))
        self.cmap_combo = QComboBox()
        self.cmap_combo.addItems(CMAPS)
        initial_cmap = "gray"
        if self.config:
            initial_cmap = self.config.get("viewer_cmap", "gray")
        if initial_cmap not in CMAPS:
            initial_cmap = "gray"
        self.cmap_combo.setCurrentText(initial_cmap)
        self.cmap_combo.currentTextChanged.connect(self._on_cmap_changed)
        tr_layout.addWidget(self.cmap_combo)

        btn_tile = QPushButton("Tile")
        btn_tile.clicked.connect(self._tile)
        tr_layout.addWidget(btn_tile)

        btn_cascade = QPushButton("Cascade")
        btn_cascade.clicked.connect(self._cascade)
        tr_layout.addWidget(btn_cascade)

        btn_clear = QPushButton("Clear All")
        btn_clear.clicked.connect(self.clear_display)
        tr_layout.addWidget(btn_clear)

        layout.addWidget(self.toolbar_row)

        self.desktop = QMdiArea()
        self.desktop.setViewMode(QMdiArea.SubWindowView)
        self.desktop.setTabsClosable(True)
        self.desktop.setTabsMovable(True)
        self.desktop.subWindowActivated.connect(self._on_desktop_changed)
        layout.addWidget(self.desktop)

        self._apply_styling()

    # Compatibility: old callers still work.
    def display_signal(self, signal):
        self.plot_signal(signal)

    def plot_signal(self, signal):
        fc = self.config.get("plot_facecolor", "#12121e") if self.config else "#12121e"
        plot = SignalPlotWidget(
            signal,
            cmap=self.cmap_combo.currentText(),
            interpolation=self.interpolation_combo.currentText(),
            facecolor=fc,
            parent=self.desktop,
        )
        plot.set_annotation_tool(self._annotation_tool)
        plot.set_annotation_color(self._annotation_color)
        sub = self.desktop.addSubWindow(plot)
        sub.setAttribute(Qt.WA_DeleteOnClose, True)
        sub.setWindowTitle(SignalPlotWidget._safe_title(signal))
        sub.resize(640, 420)
        plot.show()
        sub.show()
        self.desktop.setActiveSubWindow(sub)
        self.current_signal = signal
        if self._hs_roi is not None:
            self._attach_hs_roi_to_widget(plot)
        self._update_title_count()
        if self._plot_manager and self._plot_manager.isVisible():
            self._plot_manager.refresh()

    def plot_signals(self, signals):
        for sig in signals:
            self.plot_signal(sig)

    def clear_display(self):
        self.desktop.closeAllSubWindows()
        self.current_signal = None
        if self._hs_roi is not None:
            self.clear_shared_2d_roi()
        self.title_label.setText("Viewer Desktop")
        if self._plot_manager and self._plot_manager.isVisible():
            self._plot_manager.refresh()

    def _on_desktop_changed(self, _sub=None):
        """Called when any subwindow is activated, closed, or created."""
        self._update_title_count()
        if self._plot_manager and self._plot_manager.isVisible():
            self._plot_manager.refresh()

    def _update_title_count(self):
        n = len(self.desktop.subWindowList())
        if n == 0:
            self.title_label.setText("Viewer Desktop")
        else:
            self.title_label.setText(f"Viewer Desktop — {n} window{'s' if n != 1 else ''}")

    def _toggle_annotation_tool(self, tool_name):
        if self._annotation_tool == tool_name:
            self._annotation_tool = "none"
        else:
            self._annotation_tool = tool_name

        for name, btn in self._annotation_buttons.items():
            btn.blockSignals(True)
            btn.setChecked(name == self._annotation_tool)
            btn.blockSignals(False)

        for sub in self.desktop.subWindowList():
            widget = sub.widget()
            if hasattr(widget, "set_annotation_tool"):
                widget.set_annotation_tool(self._annotation_tool)

    def _choose_annotation_color(self):
        color = QColorDialog.getColor(parent=self, title="Choose Annotation Color")
        if not color.isValid():
            return
        self._annotation_color = color.name()
        self.anno_color_btn.setStyleSheet(f"background:{self._annotation_color}; border:1px solid #555;")
        for sub in self.desktop.subWindowList():
            widget = sub.widget()
            if hasattr(widget, "set_annotation_color"):
                widget.set_annotation_color(self._annotation_color)

    def toggle_plot_manager(self):
        """Show or hide the Plot Manager floating panel."""
        if self._plot_manager is None:
            self._plot_manager = PlotManagerPanel(self.desktop)
        if self._plot_manager.isVisible():
            self._plot_manager.hide()
        else:
            self._plot_manager.refresh()
            self._plot_manager.show()
            self._plot_manager.raise_()

    def _on_cmap_changed(self, cmap):
        if self.config:
            self.config.set("viewer_cmap", cmap)
            self.config.save_settings()
        for sub in self.desktop.subWindowList():
            widget = sub.widget()
            if hasattr(widget, "set_cmap"):
                widget.set_cmap(cmap)

    def _on_interpolation_changed(self, interpolation):
        if self.config:
            self.config.set("viewer_interpolation", interpolation)
            self.config.save_settings()
        for sub in self.desktop.subWindowList():
            widget = sub.widget()
            if hasattr(widget, "set_interpolation"):
                widget.set_interpolation(interpolation)

    def _tile(self):
        self.desktop.tileSubWindows()

    def _cascade(self):
        self.desktop.cascadeSubWindows()

    def has_shared_2d_roi(self):
        return self._hs_roi is not None

    def get_shared_2d_roi_bounds(self):
        if self._hs_roi is None:
            return None
        return {
            "left": self._hs_roi.left,
            "top": self._hs_roi.top,
            "right": self._hs_roi.right,
            "bottom": self._hs_roi.bottom,
        }

    def get_shared_2d_roi_signals(self):
        return [t["signal"] for t in self._hs_roi_targets]

    def get_shared_2d_roi_payload(self):
        if self._hs_roi is None:
            return None
        return {
            "roi": self._hs_roi,
            "targets": list(self._hs_roi_targets),
        }

    def toggle_shared_2d_roi(self, initial_size_px=3):
        """Create or clear a synchronized 2D ROI using HyperSpy RectangularROI widgets."""
        if self._hs_roi is not None:
            self.clear_shared_2d_roi()
            return False, "Cleared synchronized 2D ROI."

        widgets = self._roi_capable_widgets()
        if not widgets:
            return False, "No open 2D image panels are available for ROI creation."

        targets = []
        for widget in widgets:
            sig = getattr(widget, "signal", None)
            axes = widget.get_roi_axes() if hasattr(widget, "get_roi_axes") else None
            if sig is None:  # axes=None is valid for pure Signal2D
                continue
            targets.append({"signal": sig, "axes": axes})

        if not targets:
            return False, "No compatible HyperSpy signal axes found for ROI widgets."

        try:
            import hyperspy.api as hs
        except Exception as e:
            return False, f"HyperSpy is required for ROI interaction: {e}"

        # Open HyperSpy plots first so ROI widgets can be attached reliably.
        plot_errors = []
        for widget in widgets:
            if not hasattr(widget, "ensure_hyperspy_plot"):
                continue
            ok, err = widget.ensure_hyperspy_plot()
            if not ok:
                title = "<unknown>"
                try:
                    title = SignalPlotWidget._safe_title(widget.signal)
                except Exception:
                    pass
                plot_errors.append(f"{title}: {err}")

        if plot_errors:
            return False, "Failed to open HyperSpy ROI plot(s): " + "; ".join(plot_errors[:3])

        # Use the first widget's display axes for initial ROI bounds
        x_axis, y_axis = widgets[0].get_image_display_axes()
        if x_axis is None or y_axis is None:
            return False, "Reference signal does not provide ROI coordinate axes."

        try:
            roi_size_pixels = int(initial_size_px)
        except Exception:
            roi_size_pixels = 3
        roi_size_pixels = max(1, roi_size_pixels)

        left = x_axis.offset
        top = y_axis.offset
        right = left + roi_size_pixels * x_axis.scale
        bottom = top + roi_size_pixels * y_axis.scale

        roi = hs.roi.RectangularROI(
            left=left,
            top=top,
            right=right,
            bottom=bottom,
        )

        try:
            for target in targets:
                if target["axes"] is None:
                    roi.add_widget(target["signal"])
                else:
                    roi.add_widget(target["signal"], axes=target["axes"])
        except Exception as e:
            return False, f"Failed to attach ROI widgets: {e}"

        self._hs_roi = roi
        self._hs_roi_targets = targets

        # Draw rectangle overlays directly on all MDI thumbnail canvases
        for widget in widgets:
            if hasattr(widget, "draw_roi_overlay"):
                widget.draw_roi_overlay(roi)

        # Keep overlays in sync when the ROI is dragged/resized in HyperSpy windows
        try:
            roi.events.changed.connect(self._on_roi_changed)
        except Exception:
            pass

        self.roi_state_changed.emit(True)
        return True, f"Created synchronized 2D ROI on {len(targets)} signal panel(s)."

    def clear_shared_2d_roi(self):
        # Remove rectangle overlays from all MDI canvases
        for widget in self._roi_capable_widgets():
            if hasattr(widget, "clear_roi_overlay"):
                widget.clear_roi_overlay()
        if self._hs_roi is not None:
            # Disconnect change callback
            try:
                self._hs_roi.events.changed.disconnect(self._on_roi_changed)
            except Exception:
                pass
            for target in self._hs_roi_targets:
                sig = target.get("signal")
                axes = target.get("axes")
                try:
                    self._hs_roi.remove_widget(sig, axes=axes)
                except Exception:
                    try:
                        self._hs_roi.remove_widget(sig)
                    except Exception:
                        pass
        self._hs_roi = None
        self._hs_roi_targets = []
        self.roi_state_changed.emit(False)

    def _on_roi_changed(self, *args, **kwargs):
        """Update MDI thumbnail overlays when the ROI is moved/resized in HyperSpy."""
        if self._hs_roi is None:
            return
        for widget in self._roi_capable_widgets():
            if hasattr(widget, "draw_roi_overlay"):
                widget.draw_roi_overlay(self._hs_roi)

    def _roi_capable_widgets(self):
        widgets = []
        for sub in self.desktop.subWindowList():
            widget = sub.widget()
            if hasattr(widget, "supports_2d_roi") and widget.supports_2d_roi():
                widgets.append(widget)
        return widgets

    def _attach_hs_roi_to_widget(self, widget):
        if self._hs_roi is None:
            return
        sig = getattr(widget, "signal", None)
        axes = widget.get_roi_axes() if hasattr(widget, "get_roi_axes") else None
        if sig is None:
            return
        try:
            ok, _err = widget.ensure_hyperspy_plot()
            if not ok:
                return
            if axes is None:
                self._hs_roi.add_widget(sig)
            else:
                self._hs_roi.add_widget(sig, axes=axes)
            self._hs_roi_targets.append({"signal": sig, "axes": axes})
            # Draw overlay on this newly-added widget
            if hasattr(widget, "draw_roi_overlay"):
                widget.draw_roi_overlay(self._hs_roi)
        except Exception:
            pass

    # ── Multi-ROI API ─────────────────────────────────────────────────────────────

    def has_multi_rois(self):
        return len(self._multi_rois) > 0

    def get_multi_roi_count(self):
        return len(self._multi_rois)

    def add_multi_roi(self, initial_size_px=3):
        """Create one new ROI and attach it to all ROI-capable widgets.
        Returns (True, index) on success or (False, error_msg) on failure.
        """
        widgets = self._roi_capable_widgets()
        if not widgets:
            return False, "No open 2D image panels available for ROI creation."

        try:
            import hyperspy.api as hs
        except Exception as e:
            return False, f"HyperSpy is required for ROI interaction: {e}"

        # Open HyperSpy plots
        for widget in widgets:
            if hasattr(widget, "ensure_hyperspy_plot"):
                widget.ensure_hyperspy_plot()

        x_axis, y_axis = widgets[0].get_image_display_axes()
        if x_axis is None or y_axis is None:
            return False, "Reference signal does not provide ROI coordinate axes."

        size = max(1, int(initial_size_px))

        # Offset each new ROI by a few pixels so they don't stack on top of each other.
        offset_px = len(self._multi_rois) * (size + 2)
        left = x_axis.offset + offset_px * x_axis.scale
        top = y_axis.offset + offset_px * y_axis.scale
        right = left + size * x_axis.scale
        bottom = top + size * y_axis.scale

        roi = hs.roi.RectangularROI(left=left, top=top, right=right, bottom=bottom)

        targets = []
        for widget in widgets:
            sig = getattr(widget, "signal", None)
            if sig is None:
                continue
            axes = widget.get_roi_axes() if hasattr(widget, "get_roi_axes") else None
            try:
                if axes is None:
                    roi.add_widget(sig)
                else:
                    roi.add_widget(sig, axes=axes)
                targets.append({"signal": sig, "axes": axes})
            except Exception:
                pass

        roi_index = len(self._multi_rois) + 1
        entry = {"index": roi_index, "roi": roi, "targets": targets}
        self._multi_rois.append(entry)

        # Draw overlay on all thumbnail canvases.
        for widget in widgets:
            if hasattr(widget, "draw_multi_roi_overlay"):
                widget.draw_multi_roi_overlay(roi_index, roi)

        # Keep overlays in sync when dragged in HyperSpy windows.
        try:
            roi.events.changed.connect(
                lambda *a, **kw: self._on_multi_roi_changed(roi_index)
            )
        except Exception:
            pass

        return True, roi_index

    def remove_multi_roi(self, roi_index):
        """Remove one ROI by its 1-based index."""
        entry = next((e for e in self._multi_rois if e["index"] == roi_index), None)
        if entry is None:
            return
        try:
            entry["roi"].events.changed.disconnect()
        except Exception:
            pass
        for target in entry["targets"]:
            sig = target.get("signal")
            axes = target.get("axes")
            try:
                entry["roi"].remove_widget(sig, axes=axes)
            except Exception:
                try:
                    entry["roi"].remove_widget(sig)
                except Exception:
                    pass
        self._multi_rois = [e for e in self._multi_rois if e["index"] != roi_index]
        for widget in self._roi_capable_widgets():
            if hasattr(widget, "clear_multi_roi_overlay"):
                widget.clear_multi_roi_overlay(roi_index)

    def clear_multi_rois(self):
        """Remove all multi-ROIs."""
        for entry in list(self._multi_rois):
            self.remove_multi_roi(entry["index"])
        self._multi_rois = []
        for widget in self._roi_capable_widgets():
            if hasattr(widget, "clear_all_multi_roi_overlays"):
                widget.clear_all_multi_roi_overlays()

    def get_multi_roi_payload(self):
        """Return list of {index, roi, targets} for all current multi-ROIs."""
        return list(self._multi_rois)

    def _on_multi_roi_changed(self, roi_index):
        entry = next((e for e in self._multi_rois if e["index"] == roi_index), None)
        if entry is None:
            return
        for widget in self._roi_capable_widgets():
            if hasattr(widget, "draw_multi_roi_overlay"):
                widget.draw_multi_roi_overlay(roi_index, entry["roi"])

    def add_info_panel(self, title: str, text: str):
        """Show metadata/info as an MDI subwindow in the viewer desktop."""
        panel = InfoPanel(title, text, parent=self.desktop)
        sub = self.desktop.addSubWindow(panel)
        sub.setAttribute(Qt.WA_DeleteOnClose, True)
        sub.setWindowTitle(title)
        sub.resize(520, 420)
        panel.show()
        sub.show()
        self.desktop.setActiveSubWindow(sub)
        self._update_title_count()
        if self._plot_manager and self._plot_manager.isVisible():
            self._plot_manager.refresh()
        return panel

    def add_axes_editor(self, title: str, signal, apply_to_signals=None):
        """Show axes editor as an MDI subwindow in the viewer desktop."""
        panel = AxisEditorPanel(title, signal, viewer=self, apply_to_signals=apply_to_signals, parent=self.desktop)
        sub = self.desktop.addSubWindow(panel)
        sub.setAttribute(Qt.WA_DeleteOnClose, True)
        sub.setWindowTitle(title)
        sub.resize(560, 520)
        panel.show()
        sub.show()
        self.desktop.setActiveSubWindow(sub)
        self._update_title_count()
        if self._plot_manager and self._plot_manager.isVisible():
            self._plot_manager.refresh()
        return panel

    def add_elemental_map(self, signal, title: str = "") -> "ElementalMapWidget":
        """Open an interactive elemental mapping panel as an MDI subwindow."""
        panel = ElementalMapWidget(signal, title=title, config=self.config, parent=self.desktop)
        panel.map_export_requested.connect(self.elemental_map_exported.emit)
        sub = self.desktop.addSubWindow(panel)
        sub.setAttribute(Qt.WA_DeleteOnClose, True)
        sub.setWindowTitle(title or "Elemental Map")
        sub.resize(980, 500)
        panel.show()
        sub.show()
        self.desktop.setActiveSubWindow(sub)
        self._update_title_count()
        if self._plot_manager and self._plot_manager.isVisible():
            self._plot_manager.refresh()
        return panel

    def add_retract_background(self, signal, title: str = "") -> "RetractBackgroundWidget":
        """Open an interactive background-retraction panel as an MDI subwindow."""
        panel = RetractBackgroundWidget(signal, title=title, config=self.config, parent=self.desktop)
        panel.extract_requested.connect(self.background_removed_exported.emit)
        sub = self.desktop.addSubWindow(panel)
        sub.setAttribute(Qt.WA_DeleteOnClose, True)
        sub.setWindowTitle(title or "Retract Background")
        sub.resize(1020, 520)
        panel.show()
        sub.show()
        self.desktop.setActiveSubWindow(sub)
        self._update_title_count()
        if self._plot_manager and self._plot_manager.isVisible():
            self._plot_manager.refresh()
        return panel

    def add_deconvolution_panel(self, signal, available_signals,
                                title: str = "") -> "DeconvolutionWidget":
        """Open an interactive EELS deconvolution panel as an MDI subwindow."""
        panel = DeconvolutionWidget(
            signal, available_signals,
            title=title, config=self.config, parent=self.desktop,
        )
        panel.deconvolution_done.connect(self.deconvolution_exported.emit)
        sub = self.desktop.addSubWindow(panel)
        sub.setAttribute(Qt.WA_DeleteOnClose, True)
        sub.setWindowTitle(title or "Deconvolution")
        sub.resize(1060, 520)
        panel.show()
        sub.show()
        self.desktop.setActiveSubWindow(sub)
        self._update_title_count()
        if self._plot_manager and self._plot_manager.isVisible():
            self._plot_manager.refresh()
        return panel

    def add_crop_signals_panel(self, signal, crop_count: int, title: str = "") -> "CropSignalsWidget":
        """Open an interactive crop panel as an MDI subwindow."""
        panel = CropSignalsWidget(signal, crop_count=crop_count, title=title, config=self.config, parent=self.desktop)
        panel.crop_export_requested.connect(self.cropped_signals_exported.emit)
        sub = self.desktop.addSubWindow(panel)
        sub.setAttribute(Qt.WA_DeleteOnClose, True)
        sub.setWindowTitle(title or "Crop signals")
        sub.resize(1040, 560)
        panel.show()
        sub.show()
        self.desktop.setActiveSubWindow(sub)
        self._update_title_count()
        if self._plot_manager and self._plot_manager.isVisible():
            self._plot_manager.refresh()
        return panel

    def add_figure_panel(self, fig, title: str = ""):
        """Embed an existing matplotlib Figure as an MDI subwindow."""
        panel = _MatplotlibPanel(fig, title=title, parent=self.desktop)
        sub = self.desktop.addSubWindow(panel)
        sub.setAttribute(Qt.WA_DeleteOnClose, True)
        sub.setWindowTitle(title or "Figure")
        w = int(fig.get_figwidth() * fig.dpi + 40)
        h = int(fig.get_figheight() * fig.dpi + 80)
        sub.resize(max(400, min(w, 1400)), max(300, min(h, 900)))
        panel.show()
        sub.show()
        self.desktop.setActiveSubWindow(sub)
        self._update_title_count()
        if self._plot_manager and self._plot_manager.isVisible():
            self._plot_manager.refresh()

    def add_pca_panel(self, signal, title: str = "") -> "PcaWidget":
        """Open an interactive PCA/decomposition panel as an MDI subwindow."""
        panel = PcaWidget(signal, title=title, config=self.config, parent=self.desktop)
        panel.pca_export_requested.connect(self.pca_exported.emit)
        panel.figure_ready.connect(self.add_figure_panel)
        sub = self.desktop.addSubWindow(panel)
        sub.setAttribute(Qt.WA_DeleteOnClose, True)
        sub.setWindowTitle(title or "PCA / Decomposition")
        sub.resize(1060, 580)
        panel.show()
        sub.show()
        self.desktop.setActiveSubWindow(sub)
        self._update_title_count()
        if self._plot_manager and self._plot_manager.isVisible():
            self._plot_manager.refresh()
        return panel
