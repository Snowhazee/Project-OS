# Process Management Monitor

A desktop process monitor for Windows and Linux. It displays live system CPU
and memory usage, searchable process details, process hierarchy, and basic
process controls in a native window.

## Requirements

- Python 3.10 or newer
- Windows: PowerShell or Windows Terminal
- Linux: a terminal emulator and Tkinter (often packaged as `python3-tk`)

## Install and run

### Windows

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
py process_monitor.py
```

If PowerShell blocks virtual-environment activation, run the program directly
with `.\.venv\Scripts\python.exe process_monitor.py` after installing packages
with `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`.

### Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python process_monitor.py
```

The app uses Python's built-in Tkinter toolkit for the window and `psutil` to
read process information. Process snapshots are collected in a background
thread so the interface remains responsive while the list refreshes every few
seconds. Some process details and control actions require administrator/root
privileges.

## Features and controls

| Control | Action |
| --- | --- |
| Search field | Filter by PID, PPID, process name, user, or status |
| Click a column heading | Sort the process list |
| List / Tree | Toggle parent-child hierarchy |
| Double-click a process | Show process details |
| Suspend / Resume | Ask for confirmation, then suspend or resume the selected process |
| Terminate | Ask for confirmation, then terminate the selected process |
| Window close button | Quit |

For a safe process-control demo, start a test process such as `sleep 300` on
Linux or `Start-Sleep -Seconds 300` in PowerShell, find it in the app, and try
suspend/resume before terminating it.
