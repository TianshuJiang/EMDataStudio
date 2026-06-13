"""
config.py
Configuration management for EMDataStudio.
Handles saving and loading user preferences like font size, colors, etc.
"""
import json
import os
from pathlib import Path


class AppConfig:
    """Manage application settings and preferences."""

    # Default configuration
    DEFAULTS = {
        "font_size": 16,  # Default font size in points
        "background_color": "#e8e8e8",  # Light gray background
        "text_color": "#000000",  # Black text
        "menu_background": "#1c1c2e",  # Keep dark menu for contrast
        "menu_text": "#e0e0e0",
        
        # Data list area (left panel)
        "data_list_background": "#f8f8f8",  # Slightly lighter than main background
        "data_list_text": "#000000",  # Black text
        "data_list_font_size": 16,  # Font size for data list
        
        # Viewing area (right panel)
        "viewer_text": "#000000",  # Black text for viewing area
        "viewer_toolbar_bg": "#f0f0f0",  # Light gray for viewer toolbar
        "viewer_toolbar_text": "#000000",  # Black text for toolbar
        "viewer_font_size": 16,  # Font size for viewing area
        "viewer_cmap": "gray",
        "viewer_interpolation": "none",
        "plot_facecolor": "#12121e",  # Matplotlib figure/axes background

        # Analysis panel (PCA, Retract Background, Crop) right-side controls
        "panel_font_size": 11,
        "panel_bg": "#1a1a2e",   # Right-side control panel background
        "panel_text": "#d7def6",  # Right-side control panel text / font color

        # Drag/drop behavior for signal -> workspace
        "drop_signal_workspace_ask": True,
        "drop_signal_workspace_mode": "existing",  # 'new' | 'existing'
    }

    def __init__(self):
        """Initialize configuration with defaults."""
        self.config_dir = Path.home() / ".emdatastudio"
        self.config_file = self.config_dir / "settings.json"
        
        # Create config directory if it doesn't exist
        self.config_dir.mkdir(exist_ok=True)
        
        # Load existing config or use defaults
        self.settings = self._load_settings()

    def _load_settings(self) -> dict:
        """Load settings from file or return defaults."""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    settings = json.load(f)
                # Merge with defaults to ensure all keys exist
                return {**self.DEFAULTS, **settings}
            except Exception as e:
                print(f"Warning: Could not load settings: {e}")
                return self.DEFAULTS.copy()
        return self.DEFAULTS.copy()

    def save_settings(self) -> bool:
        """Save current settings to file."""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.settings, f, indent=2)
            return True
        except Exception as e:
            print(f"Error saving settings: {e}")
            return False

    def get(self, key: str, default=None):
        """Get a setting value."""
        return self.settings.get(key, default)

    def set(self, key: str, value):
        """Set a setting value."""
        self.settings[key] = value

    def reset_to_defaults(self):
        """Reset all settings to defaults."""
        self.settings = self.DEFAULTS.copy()
        self.save_settings()

    def get_stylesheet(self) -> str:
        """Generate stylesheet based on current settings."""
        font_size = self.get("font_size", 11)
        bg_color = self.get("background_color", "#e8e8e8")
        text_color = self.get("text_color", "#000000")
        menu_bg = self.get("menu_background", "#1c1c2e")
        menu_text = self.get("menu_text", "#e0e0e0")
        stylesheet = f"""
            QMainWindow {{ background: {bg_color}; color: {text_color}; }}
            QLabel {{ color: {text_color}; }}
            QListWidget {{ background: {bg_color}; color: {text_color}; }}
            QListWidgetItem {{ color: {text_color}; }}
            
            QMenuBar {{
                background: {menu_bg};
                color: {menu_text};
                padding: 2px;
                font-size: {font_size}px;
            }}
            QMenuBar::item:selected {{ background: #2e2e4a; border-radius: 3px; }}
            
            QMenu {{
                background: {menu_bg};
                color: {menu_text};
                border: 1px solid #3a3a5c;
                font-size: {font_size}px;
            }}
            QMenu::item:selected {{ background: #3a3a6c; }}
            
            QStatusBar {{
                background: {menu_bg};
                color: {menu_text};
                font-size: {font_size - 1}px;
            }}
            
            QSplitter::handle {{ background: #d0d0d8; width: 3px; }}
            
            QDialog {{
                background: {bg_color};
                color: {text_color};
            }}
            
            QSpinBox, QLineEdit {{
                background: white;
                color: {text_color};
                border: 1px solid #ccc;
                padding: 4px;
            }}
            
            QPushButton {{
                background: #007acc;
                color: white;
                border: none;
                padding: 6px 16px;
                border-radius: 3px;
                font-size: {font_size}px;
            }}
            QPushButton:hover {{ background: #005a9e; }}
            
            QComboBox {{
                background: white;
                color: {text_color};
                border: 1px solid #ccc;
                padding: 4px;
            }}
        """
        return stylesheet
