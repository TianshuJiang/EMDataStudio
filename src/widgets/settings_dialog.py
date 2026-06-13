"""
settings_dialog.py
Settings dialog for EMDataStudio appearance preferences.
"""
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QSpinBox,
    QLineEdit, QPushButton, QColorDialog, QGroupBox, QGridLayout, QComboBox
)
from PyQt5.QtGui import QColor
from PyQt5.QtCore import Qt


INTERPOLATIONS = [
    "none", "nearest", "bilinear", "bicubic",
    "spline16", "spline36", "hanning", "hamming",
    "hermite", "kaiser", "quadric", "catrom",
    "gaussian", "bessel", "mitchell", "sinc", "lanczos",
]

CMAPS = [
    "gray", "hot", "viridis", "plasma",
    "inferno", "magma", "cividis", "turbo", "RdBu_r",
]


class SettingsDialog(QDialog):
    """Dialog for managing application settings."""

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("EMDataStudio Settings")
        self.setGeometry(100, 100, 400, 300)
        self._setup_ui()

    def _setup_ui(self):
        """Set up the UI for settings dialog."""
        layout = QVBoxLayout()

        # ── Global Font Size ─────────────────────────────────────────────────
        group_font = QGroupBox("Global Font Size")
        grid_font = QGridLayout()

        label_size = QLabel("Font Size:")
        self.spin_font_size = QSpinBox()
        self.spin_font_size.setMinimum(8)
        self.spin_font_size.setMaximum(24)
        self.spin_font_size.setValue(self.config.get("font_size", 11))

        grid_font.addWidget(label_size, 0, 0)
        grid_font.addWidget(self.spin_font_size, 0, 1)
        group_font.setLayout(grid_font)
        layout.addWidget(group_font)

        # ── Main Application ─────────────────────────────────────────────────
        group_main = QGroupBox("Main Application")
        grid_main = QGridLayout()

        # Background color
        label_bg = QLabel("Background Color:")
        self.line_bg_color = QLineEdit()
        self.line_bg_color.setText(self.config.get("background_color", "#e8e8e8"))
        self.line_bg_color.setReadOnly(True)
        btn_bg_color = QPushButton("Choose…")
        btn_bg_color.clicked.connect(self._choose_background_color)

        grid_main.addWidget(label_bg, 0, 0)
        grid_main.addWidget(self.line_bg_color, 0, 1)
        grid_main.addWidget(btn_bg_color, 0, 2)

        # Text color
        label_text = QLabel("Text Color:")
        self.line_text_color = QLineEdit()
        self.line_text_color.setText(self.config.get("text_color", "#000000"))
        self.line_text_color.setReadOnly(True)
        btn_text_color = QPushButton("Choose…")
        btn_text_color.clicked.connect(self._choose_text_color)

        grid_main.addWidget(label_text, 1, 0)
        grid_main.addWidget(self.line_text_color, 1, 1)
        grid_main.addWidget(btn_text_color, 1, 2)

        group_main.setLayout(grid_main)
        layout.addWidget(group_main)

        # ── Data List Area ───────────────────────────────────────────────────
        group_data = QGroupBox("Data List Area (Left Panel)")
        grid_data = QGridLayout()

        # Background color
        label_data_bg = QLabel("Background:")
        self.line_data_bg_color = QLineEdit()
        self.line_data_bg_color.setText(self.config.get("data_list_background", "#f8f8f8"))
        self.line_data_bg_color.setReadOnly(True)
        btn_data_bg_color = QPushButton("Choose…")
        btn_data_bg_color.clicked.connect(self._choose_data_background_color)

        grid_data.addWidget(label_data_bg, 0, 0)
        grid_data.addWidget(self.line_data_bg_color, 0, 1)
        grid_data.addWidget(btn_data_bg_color, 0, 2)

        # Text color
        label_data_text = QLabel("Text Color:")
        self.line_data_text_color = QLineEdit()
        self.line_data_text_color.setText(self.config.get("data_list_text", "#000000"))
        self.line_data_text_color.setReadOnly(True)
        btn_data_text_color = QPushButton("Choose…")
        btn_data_text_color.clicked.connect(self._choose_data_text_color)

        grid_data.addWidget(label_data_text, 1, 0)
        grid_data.addWidget(self.line_data_text_color, 1, 1)
        grid_data.addWidget(btn_data_text_color, 1, 2)

        # Font size
        label_data_font = QLabel("Font Size:")
        self.spin_data_font_size = QSpinBox()
        self.spin_data_font_size.setMinimum(8)
        self.spin_data_font_size.setMaximum(24)
        self.spin_data_font_size.setValue(self.config.get("data_list_font_size", 11))

        grid_data.addWidget(label_data_font, 2, 0)
        grid_data.addWidget(self.spin_data_font_size, 2, 1)

        group_data.setLayout(grid_data)
        layout.addWidget(group_data)

        # ── Viewing Area ─────────────────────────────────────────────────────
        group_viewer = QGroupBox("Viewing Area (Right Panel)")
        grid_viewer = QGridLayout()

        # Plot / figure background
        label_plot_fc = QLabel("Plot Background:")
        self.line_plot_facecolor = QLineEdit()
        self.line_plot_facecolor.setText(self.config.get("plot_facecolor", "#12121e"))
        self.line_plot_facecolor.setReadOnly(True)
        btn_plot_fc = QPushButton("Choose…")
        btn_plot_fc.setToolTip(
            "Matplotlib figure/axes background color.\n"
            "Applies to newly opened MDI plot windows and the PCA scree plot.\n"
            "Text and tick colors adapt automatically (dark vs light theme)."
        )
        btn_plot_fc.clicked.connect(self._choose_plot_facecolor)

        grid_viewer.addWidget(label_plot_fc, 1, 0)
        grid_viewer.addWidget(self.line_plot_facecolor, 1, 1)
        grid_viewer.addWidget(btn_plot_fc, 1, 2)

        # Text color
        label_viewer_text = QLabel("Toolbar Text Color:")
        self.line_viewer_text_color = QLineEdit()
        self.line_viewer_text_color.setText(self.config.get("viewer_text", "#000000"))
        self.line_viewer_text_color.setReadOnly(True)
        btn_viewer_text_color = QPushButton("Choose…")
        btn_viewer_text_color.clicked.connect(self._choose_viewer_text_color)

        grid_viewer.addWidget(label_viewer_text, 2, 0)
        grid_viewer.addWidget(self.line_viewer_text_color, 2, 1)
        grid_viewer.addWidget(btn_viewer_text_color, 2, 2)

        # Toolbar background
        label_toolbar_bg = QLabel("Toolbar BG:")
        self.line_toolbar_bg_color = QLineEdit()
        self.line_toolbar_bg_color.setText(self.config.get("viewer_toolbar_bg", "#f0f0f0"))
        self.line_toolbar_bg_color.setReadOnly(True)
        btn_toolbar_bg_color = QPushButton("Choose…")
        btn_toolbar_bg_color.clicked.connect(self._choose_toolbar_background_color)

        grid_viewer.addWidget(label_toolbar_bg, 3, 0)
        grid_viewer.addWidget(self.line_toolbar_bg_color, 3, 1)
        grid_viewer.addWidget(btn_toolbar_bg_color, 3, 2)

        # Font size
        label_viewer_font = QLabel("Toolbar Font Size:")
        self.spin_viewer_font_size = QSpinBox()
        self.spin_viewer_font_size.setMinimum(8)
        self.spin_viewer_font_size.setMaximum(24)
        self.spin_viewer_font_size.setValue(self.config.get("viewer_font_size", 11))

        grid_viewer.addWidget(label_viewer_font, 4, 0)
        grid_viewer.addWidget(self.spin_viewer_font_size, 4, 1)

        label_viewer_interp = QLabel("Interpolation:")
        self.combo_viewer_interpolation = QComboBox()
        self.combo_viewer_interpolation.addItems(INTERPOLATIONS)
        current_interp = self.config.get("viewer_interpolation", "none")
        if current_interp in INTERPOLATIONS:
            self.combo_viewer_interpolation.setCurrentText(current_interp)

        grid_viewer.addWidget(label_viewer_interp, 5, 0)
        grid_viewer.addWidget(self.combo_viewer_interpolation, 5, 1, 1, 2)

        label_viewer_cmap = QLabel("Colormap:")
        self.combo_viewer_cmap = QComboBox()
        self.combo_viewer_cmap.addItems(CMAPS)
        current_cmap = self.config.get("viewer_cmap", "gray")
        if current_cmap in CMAPS:
            self.combo_viewer_cmap.setCurrentText(current_cmap)

        grid_viewer.addWidget(label_viewer_cmap, 6, 0)
        grid_viewer.addWidget(self.combo_viewer_cmap, 6, 1, 1, 2)

        label_panel_font = QLabel("Analysis Panel Font Size:")
        self.spin_panel_font_size = QSpinBox()
        self.spin_panel_font_size.setMinimum(8)
        self.spin_panel_font_size.setMaximum(24)
        self.spin_panel_font_size.setValue(self.config.get("panel_font_size", 11))
        self.spin_panel_font_size.setToolTip(
            "Font size for controls inside PCA, Rebin and other analysis panels.\n"
            "Takes effect the next time you open a panel."
        )
        grid_viewer.addWidget(label_panel_font, 7, 0)
        grid_viewer.addWidget(self.spin_panel_font_size, 7, 1)

        label_panel_bg = QLabel("Analysis Panel BG:")
        self.line_panel_bg = QLineEdit()
        self.line_panel_bg.setText(self.config.get("panel_bg", "#1a1a2e"))
        self.line_panel_bg.setReadOnly(True)
        btn_panel_bg = QPushButton("Choose…")
        btn_panel_bg.setToolTip("Background color of the right-side control panel in PCA, Retract Background, and Crop panels.")
        btn_panel_bg.clicked.connect(self._choose_panel_bg_color)
        grid_viewer.addWidget(label_panel_bg, 8, 0)
        grid_viewer.addWidget(self.line_panel_bg, 8, 1)
        grid_viewer.addWidget(btn_panel_bg, 8, 2)

        label_panel_text = QLabel("Analysis Panel Text:")
        self.line_panel_text = QLineEdit()
        self.line_panel_text.setText(self.config.get("panel_text", "#d7def6"))
        self.line_panel_text.setReadOnly(True)
        btn_panel_text = QPushButton("Choose…")
        btn_panel_text.setToolTip("Font / text color inside the analysis panel control areas.")
        btn_panel_text.clicked.connect(self._choose_panel_text_color)
        grid_viewer.addWidget(label_panel_text, 9, 0)
        grid_viewer.addWidget(self.line_panel_text, 9, 1)
        grid_viewer.addWidget(btn_panel_text, 9, 2)

        group_viewer.setLayout(grid_viewer)
        layout.addWidget(group_viewer)

        # ── Behavior ─────────────────────────────────────────────────────────
        group_behavior = QGroupBox("Behavior")
        grid_behavior = QGridLayout()

        lbl_drop_prompt = QLabel("Workspace-drop prompt:")
        lbl_drop_status = QLabel(
            "Enabled" if self.config.get("drop_signal_workspace_ask", True) else "Suppressed (do-not-ask active)"
        )
        lbl_drop_status.setObjectName("drop_prompt_status")
        self._drop_status_label = lbl_drop_status
        btn_reset_prompt = QPushButton('Reset "Do not ask again"')
        btn_reset_prompt.setToolTip("Re-enable the confirmation dialog shown when dropping signals onto a workspace")
        btn_reset_prompt.clicked.connect(self._reset_drop_prompt)

        grid_behavior.addWidget(lbl_drop_prompt, 0, 0)
        grid_behavior.addWidget(lbl_drop_status, 0, 1)
        grid_behavior.addWidget(btn_reset_prompt, 0, 2)

        group_behavior.setLayout(grid_behavior)
        layout.addWidget(group_behavior)

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_layout = QHBoxLayout()

        btn_reset = QPushButton("Reset to Defaults")
        btn_reset.clicked.connect(self._reset_defaults)

        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)

        btn_ok = QPushButton("Apply & Save")
        btn_ok.clicked.connect(self.accept)

        btn_layout.addWidget(btn_reset)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_cancel)
        btn_layout.addWidget(btn_ok)

        layout.addStretch()
        layout.addLayout(btn_layout)

        self.setLayout(layout)

    def _choose_background_color(self):
        """Open color picker for main background color."""
        current_color = QColor(self.line_bg_color.text())
        color = QColorDialog.getColor(current_color, self, "Choose Main Background Color")
        if color.isValid():
            self.line_bg_color.setText(color.name())

    def _choose_text_color(self):
        """Open color picker for main text color."""
        current_color = QColor(self.line_text_color.text())
        color = QColorDialog.getColor(current_color, self, "Choose Main Text Color")
        if color.isValid():
            self.line_text_color.setText(color.name())

    def _choose_data_background_color(self):
        """Open color picker for data list background color."""
        current_color = QColor(self.line_data_bg_color.text())
        color = QColorDialog.getColor(current_color, self, "Choose Data List Background Color")
        if color.isValid():
            self.line_data_bg_color.setText(color.name())

    def _choose_data_text_color(self):
        """Open color picker for data list text color."""
        current_color = QColor(self.line_data_text_color.text())
        color = QColorDialog.getColor(current_color, self, "Choose Data List Text Color")
        if color.isValid():
            self.line_data_text_color.setText(color.name())

    def _choose_panel_bg_color(self):
        color = QColorDialog.getColor(QColor(self.line_panel_bg.text()), self, "Choose Analysis Panel Background")
        if color.isValid():
            self.line_panel_bg.setText(color.name())

    def _choose_panel_text_color(self):
        color = QColorDialog.getColor(QColor(self.line_panel_text.text()), self, "Choose Analysis Panel Text Color")
        if color.isValid():
            self.line_panel_text.setText(color.name())

    def _choose_plot_facecolor(self):
        current_color = QColor(self.line_plot_facecolor.text())
        color = QColorDialog.getColor(current_color, self, "Choose Plot Background Color")
        if color.isValid():
            self.line_plot_facecolor.setText(color.name())

    def _choose_viewer_text_color(self):
        """Open color picker for viewer text color."""
        current_color = QColor(self.line_viewer_text_color.text())
        color = QColorDialog.getColor(current_color, self, "Choose Viewer Text Color")
        if color.isValid():
            self.line_viewer_text_color.setText(color.name())

    def _choose_toolbar_background_color(self):
        """Open color picker for viewer toolbar background color."""
        current_color = QColor(self.line_toolbar_bg_color.text())
        color = QColorDialog.getColor(current_color, self, "Choose Viewer Toolbar Background Color")
        if color.isValid():
            self.line_toolbar_bg_color.setText(color.name())

    def _reset_drop_prompt(self):
        """Re-enable the workspace-drop confirmation dialog."""
        self.config.set("drop_signal_workspace_ask", True)
        self.config.save_settings()
        self._drop_status_label.setText("Enabled")

    def _reset_defaults(self):
        """Reset all settings to default values."""
        self.spin_font_size.setValue(11)
        self.line_bg_color.setText("#e8e8e8")
        self.line_text_color.setText("#000000")
        self.line_data_bg_color.setText("#f8f8f8")
        self.line_data_text_color.setText("#000000")
        self.spin_data_font_size.setValue(11)
        self.line_plot_facecolor.setText("#12121e")
        self.line_viewer_text_color.setText("#000000")
        self.line_toolbar_bg_color.setText("#f0f0f0")
        self.spin_viewer_font_size.setValue(11)
        self.spin_panel_font_size.setValue(11)
        self.line_panel_bg.setText("#1a1a2e")
        self.line_panel_text.setText("#d7def6")
        self.combo_viewer_interpolation.setCurrentText("none")
        self.combo_viewer_cmap.setCurrentText("gray")

    def get_settings(self) -> dict:
        """Return the updated settings."""
        return {
            "font_size": self.spin_font_size.value(),
            "background_color": self.line_bg_color.text(),
            "text_color": self.line_text_color.text(),
            "data_list_background": self.line_data_bg_color.text(),
            "data_list_text": self.line_data_text_color.text(),
            "data_list_font_size": self.spin_data_font_size.value(),
            "plot_facecolor": self.line_plot_facecolor.text(),
            "viewer_text": self.line_viewer_text_color.text(),
            "viewer_toolbar_bg": self.line_toolbar_bg_color.text(),
            "viewer_font_size": self.spin_viewer_font_size.value(),
            "panel_font_size": self.spin_panel_font_size.value(),
            "panel_bg": self.line_panel_bg.text(),
            "panel_text": self.line_panel_text.text(),
            "viewer_cmap": self.combo_viewer_cmap.currentText(),
            "viewer_interpolation": self.combo_viewer_interpolation.currentText(),
        }
