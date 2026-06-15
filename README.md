# EMDataStudio

User-friendly GUI for loading, organizing, visualizing, and processing HyperSpy-compatible electron microscopy datasets.

TU Darmstadt - Advanced Electron Microscopy Division

Maintainer: Dr. Tianshu Jiang

## Overview

EMDataStudio is a desktop application for loading, organizing, visualizing, and processing HyperSpy-compatible electron microscopy data.
It is built for workflows that combine HAADF/STEM and EELS signals, with multi-workspace organization, ROI-based extraction, and MDI plotting.

## Getting Started

### Download

Clone the repository from GitHub:

```bash
git clone https://github.com/TianshuJiang/EMDataStudio.git
```

### Install

Install Anaconda or Miniconda, then create the environment from `environment.yml`:

```bash
conda env create -f install/environment.yml
conda activate EMDataStudio
```

## Run

```bash
conda activate EMDataStudio
python main.py
```

Or use `install/run.bat` on Windows.

## Basic Usage

1. Start the application.
2. Use File -> Load File to import one or more HyperSpy-compatible files.
3. Select signals in the Data List to plot, inspect, or organize them.
4. Use the Functions menu for sorting, ROI creation, cropping, and export.

## Key Features

- Load HyperSpy-compatible files such as `.hspy`, `.h5`, `.hdf5`, `.dm3`, `.dm4`, and `.mrc`
- Organize data into multiple workspaces and datasets
- Plot signals in a multi-window MDI viewer
- Sort signals by frame grouping
- Create, move, copy, rename, and close datasets and workspaces
- Export single and multiple ROI crops into new datasets
- Use synchronized ROI workflows across compatible signals

## Project Structure

```text
EMDataStudio/
|-- main.py
|-- README.md
|-- install/
|   |-- run.bat
|   `-- environment.yml
|-- src/
|   |-- app.py
|   |-- config.py
|   |-- data_manager.py
|   `-- widgets/
|       |-- data_list_widget.py
|       |-- settings_dialog.py
|       `-- viewer_widget.py
`-- assets/
```

## Notes

- The project uses compatibility-constrained conda dependencies for stable setup across machines.
- ROI operations are synchronized with HyperSpy ROI objects and shown in MDI thumbnails.
- HyperSpy signal comparisons in the app use identity checks to avoid dimension-comparison errors.

## Acknowledgment

Built for processing atomically resolved, multi-frame in situ STEM-EELS datasets.

## License

This project is released under the MIT License. See [LICENSE](LICENSE) for the full text.
