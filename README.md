# ExamScan

A Raspberry Pi-based document scanner that captures high-resolution images of exam papers using a fixed overhead camera and automatically advances pages with a stepper motor.

## Hardware

| Component | Details |
|---|---|
| Camera | Raspberry Pi Camera Module 3 (IMX708) |
| Motor | NEMA 17 SM24240 stepper motor |
| Motor Driver | DRV8825 |

### Wiring

| Signal | GPIO (BCM) |
|---|---|
| STEP | 21 |
| DIR | 20 |
| ENABLE | 16 |

Camera is mounted approximately 43 cm above the scanning surface with a fixed lens position.

## Project Structure

```
ExamScan/
├── hardware/
│   ├── camera.py       # Camera streaming and capture server
│   └── motor.py        # Stepper motor control
├── static/
│   └── index.html      # Web UI for live preview and capture
├── captures/           # Saved images (auto-created)
└── main.py             # Entry point
```

## Setup

### What is uv?

`uv` is a fast Python package manager (a replacement for `pip` + `venv`). It manages the virtual environment and dependencies for this project. The `--system-site-packages` flag is required here so the virtual environment can access `libcamera`, which is a system-level Raspberry Pi library that cannot be installed via pip.

### 1. Install system dependencies

```bash
sudo apt install libcap-dev liblgpio-dev swig -y
```

### 2. Install uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Restart your terminal after installing, or run:
```bash
source $HOME/.local/bin/env
```

### 3. Create the virtual environment

```bash
uv venv --system-site-packages
```

### 4. Install Python dependencies

```bash
uv sync
```

## Usage

```bash
python3 main.py
```
