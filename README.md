# Process Management Monitor (Linux & Windows)

A comprehensive Operating Systems process monitor and management tool built for Linux (and Windows). It displays running processes, live system CPU/memory/swap usage, visual process hierarchy trees, and provides process control capabilities (signals, suspension/resumption, termination, and priority renicing).

It features **dual operational modes**:
1. **Interactive Terminal TUI** (`curses`): Designed for Linux terminal emulators, SSH sessions, and headless servers without requiring an X11/Wayland display server.
2. **Desktop GUI** (`tkinter`): A desktop dashboard with live metric meters, collapsible tree hierarchy, filter search, and right-click context menus.

---

## Features

- **Live System Metrics**: Overall CPU percentage, logical core count, RAM utilization (Used / Total in GB), Swap memory usage, and task state counters (running, sleeping, stopped, zombie).
- **Process Listing & Filtering**: View PID, PPID, User, Priority (Nice), CPU %, Memory %, State, and Command/Name. Search and filter instantly by any attribute.
- **Process Hierarchy (Tree View)**: Visual parent-child tree (`systemd` / `init` roots with `├── `, `└── `, and `│   ` branch connectors) revealing how processes are spawned and grouped.
- **Process Controls**:
  - **Terminate (`SIGTERM`)**: Graceful termination request allowing processes to save state and clean up resources.
  - **Force Kill (`SIGKILL`)**: Unconditional kernel-level termination for frozen or unresponsive processes.
  - **Suspend / Pause (`SIGSTOP`)**: Freezes process execution without freeing its memory.
  - **Resume (`SIGCONT`)**: Unpauses and resumes stopped processes.
  - **Renice (Priority Adjustment)**: Adjusts CPU scheduling priority (`nice` value from `-20` highest priority to `19` lowest priority on Linux).
  - **Process Inspection**: In-depth inspection window showing full command line, working directory, executable path, thread count, CPU user/system times, and memory breakdown (RSS / VMS).

---

## Operating System Concepts

| OS Concept | Implementation & Description |
| :--- | :--- |
| **Process Table & States** | Monitors processes across POSIX states: Running (`R`), Sleeping (`S`), Disk Sleep (`D`), Stopped (`T`), and Zombie (`Z`). |
| **Process Hierarchy** | Maps `PPID` to `PID` to reconstruct the process tree hierarchy starting from root `PID 1` (`systemd` / `init`). |
| **CPU Scheduling & Nice** | Visualizes and alters process priority values (`-20` to `19`). Negative nice values require root/sudo. |
| **Inter-Process Signals** | Dispatches standard POSIX signals (`SIGTERM` 15, `SIGKILL` 9, `SIGSTOP` 19, `SIGCONT` 18). |
| **Memory Management** | Distinguishes Resident Set Size (RSS - physical RAM held) and Virtual Memory Size (VMS). |

---

## Requirements

- **Python 3.10+**
- **Linux Packages**:
  - `psutil` (via pip)
  - `python3-tk` (optional, only needed for GUI mode on Ubuntu/Debian: `sudo apt install python3-tk`)
  - Standard `curses` is built into Linux Python installations.

---

## Installation & Running

### Linux

1. Clone or navigate to the project directory:
   ```bash
   cd "g:/Project OS"   # or your Linux path
   ```

2. Create and activate a virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. Launch the monitor:
   - **Auto Mode** (launches GUI if display exists; falls back to Terminal TUI if headless or in SSH):
     ```bash
     python3 process_monitor.py
     ```
   - **Terminal TUI Mode** (recommended for terminal / SSH / servers):
     ```bash
     python3 process_monitor.py --tui
     # or directly:
     python3 process_monitor_tui.py
     ```
   - **Desktop GUI Mode**:
     ```bash
     python3 process_monitor.py --gui
     ```

> **Note on Permissions**: To send signals or renice processes owned by other users or system services, run with root privileges: `sudo python3 process_monitor.py --tui`.

---

### Windows

1. Setup virtual environment and dependencies:
   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   py -m pip install -r requirements.txt
   ```

2. Run the program:
   - **Desktop GUI Mode**:
     ```powershell
     py process_monitor.py
     ```
   - **Terminal TUI Mode**:
     ```powershell
     py process_monitor.py --tui
     ```

---

## Interactive Controls

### Terminal (TUI) Mode

| Key | Action |
| :--- | :--- |
| `↑` / `↓` or `k` / `j` | Navigate process rows |
| `PgUp` / `PgDn` | Scroll by 10 rows |
| `Home` / `End` | Jump to first / last row |
| `t` | **Toggle Tree Hierarchy** on/off |
| `/` | **Filter / Search** processes (Enter to submit, Esc to clear) |
| `c` / `m` / `p` / `n` / `u` | **Sort** by CPU%, Memory%, PID, Name, or User |
| `k` | Open **Process Control Action Menu** |
| `x` | Quick **Terminate** (`SIGTERM`) selected process |
| `K` | Quick **Force Kill** (`SIGKILL`) selected process |
| `s` | Quick **Suspend / Resume** (`SIGSTOP` / `SIGCONT`) |
| `r` | **Renice** (adjust process priority -20 to 19) |
| `Enter` or `d` | View full **Process Details** modal |
| `?` or `h` | Open **Help & Shortcuts** screen |
| `q` | Quit |

---

### Desktop (GUI) Mode

- **Search Bar**: Instant live filtering across PID, PPID, user, status, and name.
- **View Button ("View: Flat List" / "View: Tree Hierarchy")**: Switch between sorted table and tree view.
- **Column Headers**: Click any column header (`PID`, `PPID`, `USER`, `NI`, `CPU%`, `MEM%`, `STATUS`) to sort ascending/descending.
- **Buttons / Actions**:
  - `Force Kill (SIGKILL)`: Immediately terminates the process.
  - `Terminate (SIGTERM)`: Polite termination request.
  - `Suspend / Resume`: Pauses or resumes process execution.
  - `Renice`: Dialog prompt to change priority.
  - `Details`: Opens detailed modal with working directory, cmdline, memory breakdown, and thread count.
- **Right-Click Menu**: Right-click on any row to access all control actions and copy PID.

---

## Verification & Safe Testing Demo

To safely test process controls without risking system stability:

1. In a separate terminal, launch a dummy background process:
   ```bash
   # On Linux:
   sleep 500
   
   # On Windows:
   powershell -Command "Start-Sleep -Seconds 500"
   ```

2. Open the Process Monitor, type `sleep` into the filter/search bar.
3. Observe its **PID**, **PPID**, and state (`sleeping` or `S`).
4. Press **`t`** (or click "View: Tree") to observe which shell spawned the sleep process.
5. Select the sleep process and press **`s`** to suspend it (State transitions to `stopped` / `T`).
6. Press **`s`** again to resume it (State transitions back to `sleeping` / `S`).
7. Press **`r`** to renice the process (e.g., set nice value to `10`).
8. Press **`x`** (SIGTERM) or **`K`** (SIGKILL) to terminate the process and observe it disappear from the table.
