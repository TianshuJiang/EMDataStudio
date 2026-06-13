"""
data_manager.py
Handles loading HyperSpy files and classifying signals.
"""
import os
import json
import tempfile
import zipfile
from datetime import datetime


def load_hyperspy_file(filepath: str):
    """
    Load a HyperSpy-compatible file and return a list of signals.
    Supports .hspy, .hdf5, .h5, .dm3, .dm4, .mrc, etc.
    """
    try:
        import hyperspy.api as hs
    except ImportError as e:
        raise ImportError(
            "HyperSpy is not installed.\n"
            "Run: conda install -c conda-forge hyperspy"
        ) from e

    signals = hs.load(filepath, lazy=False)

    # Always return as list
    if not isinstance(signals, list):
        signals = [signals]

    # Tag each signal with its source path so the app can detect accidental
    # overwrites.  This attribute is a plain Python attribute and is NOT
    # serialised by HyperSpy, so it will never appear in the saved file.
    abs_path = os.path.abspath(filepath)
    for sig in signals:
        try:
            sig._ev_source_path = abs_path
        except Exception:
            pass

    return signals


def classify_signal(signal) -> str:
    """
    Return a detailed type label for a HyperSpy signal.
    Tries to distinguish between EELS CoreLoss and LowLoss based on energy offset.
    """
    cls = type(signal).__name__

    if cls == "EELSSpectrum":
        try:
            title = signal.metadata.General.title
            if "energy_offset_index=0" in title:
                return "EELS LowLoss"
            elif "energy_offset_index=1" in title:
                return "EELS CoreLoss"
            else:
                if "dtd=" in title:
                    import re
                    match = re.search(r'dtd=([0-9.]+)\s*eV', title)
                    if match:
                        offset_ev = float(match.group(1))
                        if offset_ev < 50:
                            return "EELS LowLoss"
                        else:
                            return "EELS CoreLoss"
        except Exception:
            pass
        return "EELS Spectrum"
    elif cls == "Signal2D":
        try:
            title = signal.metadata.General.title
            if "HAADF" in title:
                return "HAADF Image"
            elif "DF" in title:
                return "DF Image"
        except Exception:
            pass
        return "2D Image"
    elif cls == "EDSSpectrum":
        return "EDS Spectrum"
    elif cls == "Signal1D":
        return "1D Signal"
    else:
        return cls


def get_signal_title(signal) -> str:
    """Return the signal's display name.

    Checks the app-level display-name override (``_ev_display_name``) first so
    that UI renames are reflected without touching ``signal.metadata``.  Falls
    back to the metadata title recorded in the file, then to the class name.
    """
    try:
        name = getattr(signal, "_ev_display_name", None)
        if name:
            return name
    except Exception:
        pass
    try:
        title = signal.metadata.General.title
        if title:
            return title
    except Exception:
        pass
    return type(signal).__name__


def get_dimensions_str(signal) -> str:
    """Return a compact dimension string, e.g. '(64, 64 | 2048)'."""
    try:
        nav = signal.axes_manager.navigation_shape
        sig = signal.axes_manager.signal_shape
        nav_str = ", ".join(str(n) for n in nav) if nav else "—"
        sig_str = ", ".join(str(s) for s in sig)
        return f"({nav_str} | {sig_str})"
    except Exception:
        return str(signal.data.shape)


def extract_frame_number(signal_title: str):
    """
    Extract numeric frame index from signal title.
    Examples: "HAADF_0" → 0, "EELS Spectrum Image_3 (...)" → 3
    """
    import re
    match = re.search(r'_([0-9]+)', signal_title)
    if match:
        return int(match.group(1))
    return None


def extract_frame_index(signal_title: str) -> str:
    """
    Extract frame index from signal title.
    Examples: "HAADF_0" → "Frame 0", "EELS Spectrum Image_3 (..." → "Frame 3"
    """
    frame_number = extract_frame_number(signal_title)
    if frame_number is not None:
        return f"Frame {frame_number}"
    return "Unknown Frame"


def _frame_key_numeric(frame_key: str):
    import re
    match = re.search(r'Frame\s*([0-9]+)', frame_key)
    if match:
        return int(match.group(1))
    return float('inf')


def sort_and_group_signals(signals: list) -> dict:
    """
    Group signals by frame index and type.
    Returns dict: {"Frame 0": [HAADF, CoreLoss, LowLoss], "Frame 1": [...], ...}
    """
    grouped = {}

    for signal in signals:
        title = get_signal_title(signal)
        frame_number = extract_frame_number(title)
        frame_key = f"Frame {frame_number}" if frame_number is not None else "Unknown Frame"

        if frame_key not in grouped:
            grouped[frame_key] = []

        grouped[frame_key].append(signal)

    type_priority = {"HAADF": 0, "DF": 1, "EELS CoreLoss": 2, "EELS LowLoss": 3}

    for frame_key in grouped:
        grouped[frame_key].sort(
            key=lambda sig: type_priority.get(classify_signal(sig), 99)
        )

    ordered_grouped = {}
    for frame_key in sorted(grouped.keys(), key=_frame_key_numeric):
        ordered_grouped[frame_key] = grouped[frame_key]

    return ordered_grouped


def create_hyperspy_signal(type_name: str, shape: tuple, name: str = "New Signal"):
    """
    Create a new empty HyperSpy signal of the given type and shape.

    type_name : 'BaseSignal' | 'Signal1D' | 'Signal2D' |
                'EELSSpectrum' | 'EDSTEMSpectrum' | 'EDSSEMSpectrum' |
                'EDSSpectrum'  | 'DielectricFunction'
    shape     : tuple of ints, e.g. (100, 100) or (10, 10, 1024)
    name      : metadata title for the new signal
    """
    import numpy as np
    import hyperspy.api as hs

    data = np.zeros(shape, dtype=float)

    hs_types    = ("BaseSignal", "Signal1D", "Signal2D")
    exspy_types = ("EELSSpectrum", "EDSTEMSpectrum", "EDSSEMSpectrum",
                   "EDSSpectrum", "DielectricFunction")

    if type_name in hs_types:
        sig = getattr(hs.signals, type_name)(data)
    elif type_name in exspy_types:
        try:
            import exspy
            cls = getattr(exspy.signals, type_name, None)
            sig = cls(data) if cls is not None else hs.signals.BaseSignal(data)
        except ImportError:
            sig = hs.signals.BaseSignal(data)
    else:
        sig = hs.signals.BaseSignal(data)

    sig.metadata.General.title = name
    return sig


def export_eelspack(filepath: str, signals: list, entries: list = None, pack_name: str = None):
    """Export multiple signals into a native .eelspack zip container.

    The container includes:
    - manifest.json (order + source metadata)
    - one .hspy file per signal under signals/
    """
    if not isinstance(signals, list) or not signals:
        raise ValueError("No signals provided for export.")

    temp_dir = tempfile.mkdtemp(prefix="eelspack_export_")
    try:
        sig_dir = os.path.join(temp_dir, "signals")
        os.makedirs(sig_dir, exist_ok=True)

        manifest = {
            "format": "eelspack",
            "version": 1,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "name": pack_name or os.path.splitext(os.path.basename(filepath))[0],
            "count": len(signals),
            "signals": [],
        }

        for idx, sig in enumerate(signals):
            file_name = f"signal_{idx + 1:04d}.hspy"
            rel_path = f"signals/{file_name}"
            abs_path = os.path.join(sig_dir, file_name)
            sig.save(abs_path, overwrite=True)

            entry = entries[idx] if isinstance(entries, list) and idx < len(entries) else {}
            manifest["signals"].append({
                "index": idx,
                "file": rel_path,
                "title": entry.get("title") or get_signal_title(sig),
                "signal_class": entry.get("signal_class") or type(sig).__name__,
                "source_workspace": entry.get("source_workspace") or "",
                "source_dataset": entry.get("source_dataset") or "",
                # Explicit ordering keys so import can reconstruct exact sequence.
                "workspace_order": entry.get("workspace_order", 0),
                "dataset_order": entry.get("dataset_order", 0),
                "dataset_signal_order": entry.get("dataset_signal_order", idx),
            })

        manifest_path = os.path.join(temp_dir, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        with zipfile.ZipFile(filepath, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for root, _dirs, files in os.walk(temp_dir):
                for name in files:
                    abs_file = os.path.join(root, name)
                    arc_name = os.path.relpath(abs_file, temp_dir).replace("\\", "/")
                    zf.write(abs_file, arcname=arc_name)
    finally:
        try:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass


def load_eelspack(filepath: str):
    """Load a .eelspack container and return (signals, manifest)."""
    temp_dir = tempfile.mkdtemp(prefix="eelspack_import_")
    try:
        with zipfile.ZipFile(filepath, "r") as zf:
            zf.extractall(temp_dir)

        manifest_path = os.path.join(temp_dir, "manifest.json")
        if os.path.exists(manifest_path):
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        else:
            manifest = {
                "format": "eelspack",
                "version": 1,
                "name": os.path.splitext(os.path.basename(filepath))[0],
                "signals": [],
            }

        try:
            import hyperspy.api as hs
        except ImportError as e:
            raise ImportError(
                "HyperSpy is not installed.\n"
                "Run: conda install -c conda-forge hyperspy"
            ) from e

        signals = []
        manifest_signals = manifest.get("signals") if isinstance(manifest, dict) else None

        if isinstance(manifest_signals, list) and manifest_signals:
            # Always iterate in strict manifest index order so signal list
            # matches the original export sequence exactly.
            ordered_entries = sorted(manifest_signals, key=lambda e: e.get("index", 0))
            for entry in ordered_entries:
                rel_path = entry.get("file")
                if not rel_path:
                    continue
                abs_path = os.path.join(temp_dir, rel_path.replace("/", os.sep))
                if not os.path.exists(abs_path):
                    continue
                loaded = hs.load(abs_path, lazy=False)
                if isinstance(loaded, list):
                    if len(loaded) == 1:
                        signals.append(loaded[0])
                    else:
                        signals.extend(loaded)
                else:
                    signals.append(loaded)
        else:
            sig_dir = os.path.join(temp_dir, "signals")
            if os.path.isdir(sig_dir):
                for name in sorted(os.listdir(sig_dir)):
                    if not name.lower().endswith(".hspy"):
                        continue
                    loaded = hs.load(os.path.join(sig_dir, name), lazy=False)
                    if isinstance(loaded, list):
                        if len(loaded) == 1:
                            signals.append(loaded[0])
                        else:
                            signals.extend(loaded)
                    else:
                        signals.append(loaded)

        # Tag each signal so the app can detect if a save would overwrite the
        # .eelspack source file.  This plain Python attribute is not serialised
        # by HyperSpy and will never appear in any saved output.
        eelspack_abs = os.path.abspath(filepath)
        for sig in signals:
            try:
                sig._ev_source_path = eelspack_abs
            except Exception:
                pass

        return signals, manifest
    finally:
        try:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass
