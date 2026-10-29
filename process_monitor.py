"""Desktop process monitor for Windows and Linux."""

from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, ttk

import psutil


REFRESH_MILLISECONDS = 1000
COLORS = {
    "background": "#101820",
    "surface": "#192631",
    "surface_alt": "#223340",
    "text": "#e6edf3",
    "muted": "#9aabb8",
    "accent": "#38bdf8",
    "danger": "#ef6461",
    "green": "#68d391",
}


@dataclass
class ProcessInfo:
    pid: int
    ppid: int
    name: str
    username: str
    status: str
    cpu: float
    memory: float


@dataclass
class Snapshot:
    processes: list[ProcessInfo]
    cpu: float
    memory_used: int
    memory_total: int


def read_processes() -> list[ProcessInfo]:
    """Read a best-effort snapshot; processes may disappear while being read."""
    processes: list[ProcessInfo] = []
    attributes = ["pid", "ppid", "name", "username", "status", "memory_info"]
    total_memory = psutil.virtual_memory().total

    for process in psutil.process_iter(attrs=attributes):
        try:
            info = process.info
            memory_info = info["memory_info"]
            processes.append(
                ProcessInfo(
                    pid=info["pid"],
                    ppid=info["ppid"] or 0,
                    name=info["name"] or "unknown",
                    username=info["username"] or "?",
                    status=info["status"] or "?",
                    cpu=process.cpu_percent(interval=None),
                    memory=(memory_info.rss / total_memory * 100)
                    if memory_info and total_memory
                    else 0.0,
                )
            )
        except (psutil.NoSuchProcess, psutil.ZombieProcess, psutil.AccessDenied):
            continue

    return processes


def process_tree(processes: list[ProcessInfo]) -> list[tuple[ProcessInfo, int]]:
    """Return processes in parent-first order with their display indentation."""
    by_pid = {process.pid: process for process in processes}
    children: dict[int, list[ProcessInfo]] = {}
    for process in processes:
        children.setdefault(process.ppid, []).append(process)
    for group in children.values():
        group.sort(key=lambda process: process.pid)

    ordered: list[tuple[ProcessInfo, int]] = []
    visited: set[int] = set()

    def add_branch(process: ProcessInfo, depth: int) -> None:
        if process.pid in visited:
            return
        visited.add(process.pid)
        ordered.append((process, depth))
        for child in children.get(process.pid, []):
            add_branch(child, depth + 1)

    roots = sorted(
        (process for process in processes if process.ppid not in by_pid),
        key=lambda process: process.pid,
    )
    for root in roots:
        add_branch(root, 0)
    for process in sorted(processes, key=lambda item: item.pid):
        add_branch(process, 0)
    return ordered


class ProcessMonitor:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.processes: list[ProcessInfo] = []
        self.snapshot_queue: queue.Queue[tuple[Snapshot | None, str | None]] = (
            queue.Queue()
        )
        self.refresh_in_progress = False
        self.closing = False
        self.tree_mode = False
        self.sort_column = "cpu"
        self.sort_descending = True
        self.search_text = tk.StringVar()
        self.status_text = tk.StringVar(value="Starting process monitor...")
        self.cpu_text = tk.StringVar(value="CPU  --")
        self.memory_text = tk.StringVar(value="MEMORY  --")

        self._configure_window()
        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.search_text.trace_add("write", self._search_changed)
        self.root.after(100, self._poll_snapshot)
        self._request_snapshot()

    def _configure_window(self) -> None:
        self.root.title("Process Management Monitor")
        self.root.geometry("1180x740")
        self.root.minsize(850, 500)
        self.root.configure(bg=COLORS["background"])

        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(
            ".",
            background=COLORS["background"],
            foreground=COLORS["text"],
            font=("Segoe UI", 10),
        )
        style.configure("TFrame", background=COLORS["background"])
        style.configure(
            "Card.TFrame",
            background=COLORS["surface"],
        )
        style.configure(
            "TLabel",
            background=COLORS["background"],
            foreground=COLORS["text"],
        )
        style.configure(
            "Card.TLabel",
            background=COLORS["surface"],
            foreground=COLORS["text"],
        )
        style.configure(
            "Muted.TLabel",
            background=COLORS["background"],
            foreground=COLORS["muted"],
        )
        style.configure(
            "TEntry",
            fieldbackground=COLORS["surface"],
            foreground=COLORS["text"],
            insertcolor=COLORS["text"],
            padding=8,
        )
        style.configure(
            "Metric.TLabel",
            background=COLORS["surface"],
            foreground=COLORS["accent"],
            font=("Segoe UI Semibold", 16),
        )
        style.configure(
            "Title.TLabel",
            background=COLORS["background"],
            foreground=COLORS["text"],
            font=("Segoe UI Semibold", 20),
        )
        style.configure(
            "Accent.TButton",
            background=COLORS["accent"],
            foreground="#08131c",
            padding=(12, 8),
            borderwidth=0,
        )
        style.map(
            "Accent.TButton",
            background=[("active", "#7dd3fc"), ("disabled", COLORS["surface_alt"])],
            foreground=[("disabled", COLORS["muted"])],
        )
        style.configure(
            "Danger.TButton",
            background="#8f3437",
            foreground=COLORS["text"],
            padding=(12, 8),
            borderwidth=0,
        )
        style.map("Danger.TButton", background=[("active", COLORS["danger"])])
        style.configure(
            "Treeview",
            background=COLORS["surface"],
            fieldbackground=COLORS["surface"],
            foreground=COLORS["text"],
            rowheight=29,
            borderwidth=0,
        )
        style.configure(
            "Treeview.Heading",
            background=COLORS["surface_alt"],
            foreground=COLORS["muted"],
            padding=(8, 9),
            relief="flat",
        )
        style.map(
            "Treeview",
            background=[("selected", "#164e63")],
            foreground=[("selected", "#f0f9ff")],
        )

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=(22, 18))
        outer.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(outer)
        header.pack(fill=tk.X, pady=(0, 16))
        title_block = ttk.Frame(header)
        title_block.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(
            title_block, text="Process Monitor", style="Title.TLabel"
        ).pack(anchor=tk.W)
        ttk.Label(
            title_block,
            text="Live system activity and process controls",
            style="Muted.TLabel",
        ).pack(anchor=tk.W, pady=(3, 0))

        metrics = ttk.Frame(header)
        metrics.pack(side=tk.RIGHT)
        ttk.Label(
            metrics, textvariable=self.cpu_text, style="Metric.TLabel"
        ).pack(side=tk.LEFT, padx=(8, 18))
        ttk.Label(
            metrics, textvariable=self.memory_text, style="Metric.TLabel"
        ).pack(side=tk.LEFT, padx=(8, 0))

        controls = ttk.Frame(outer)
        controls.pack(fill=tk.X, pady=(0, 12))

        search_frame = ttk.Frame(controls)
        search_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(search_frame, text="Search").pack(side=tk.LEFT, padx=(0, 8))
        self.search_entry = ttk.Entry(
            search_frame, textvariable=self.search_text, width=38
        )
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(
            controls,
            text="List / Tree",
            command=self._toggle_tree,
        ).pack(side=tk.LEFT, padx=(12, 0))
        ttk.Button(
            controls,
            text="Refresh",
            command=self._request_snapshot,
        ).pack(side=tk.LEFT, padx=(8, 0))

        table_frame = ttk.Frame(outer)
        table_frame.pack(fill=tk.BOTH, expand=True)
        columns = ("pid", "ppid", "cpu", "memory", "status", "username", "name")
        self.table = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
        )
        headings = {
            "pid": ("PID", 85, tk.E),
            "ppid": ("PPID", 85, tk.E),
            "cpu": ("CPU %", 100, tk.E),
            "memory": ("MEM %", 100, tk.E),
            "status": ("STATUS", 120, tk.W),
            "username": ("USER", 190, tk.W),
            "name": ("PROCESS", 400, tk.W),
        }
        for column, (label, width, anchor) in headings.items():
            self.table.heading(
                column,
                text=label,
                anchor=anchor,
                command=lambda selected=column: self._sort_by(selected),
            )
            self.table.column(
                column,
                width=width,
                minwidth=65,
                anchor=anchor,
                stretch=column in ("username", "name"),
            )
        scrollbar = ttk.Scrollbar(
            table_frame, orient=tk.VERTICAL, command=self.table.yview
        )
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.table.bind("<<TreeviewSelect>>", self._selection_changed)
        self.table.bind("<Double-1>", self._show_details)

        footer = ttk.Frame(outer)
        footer.pack(fill=tk.X, pady=(12, 0))
        self.details_label = ttk.Label(
            footer,
            text="Select a process to see its details.",
            style="Muted.TLabel",
        )
        self.details_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(
            footer,
            text="Suspend / Resume",
            command=self._toggle_suspend,
        ).pack(side=tk.RIGHT, padx=(8, 0))
        ttk.Button(
            footer,
            text="Terminate",
            style="Danger.TButton",
            command=self._terminate,
        ).pack(side=tk.RIGHT)

        ttk.Label(
            outer,
            textvariable=self.status_text,
            style="Muted.TLabel",
        ).pack(anchor=tk.W, pady=(10, 0))

    def _request_snapshot(self) -> None:
        if self.refresh_in_progress or self.closing:
            return
        self.refresh_in_progress = True
        self.status_text.set("Updating process list...")

        def collect() -> None:
            try:
                processes = read_processes()
                memory = psutil.virtual_memory()
                snapshot = Snapshot(
                    processes=processes,
                    cpu=psutil.cpu_percent(interval=None),
                    memory_used=memory.used,
                    memory_total=memory.total,
                )
                self.snapshot_queue.put((snapshot, None))
            except (psutil.Error, OSError) as error:
                self.snapshot_queue.put((None, str(error)))

        threading.Thread(target=collect, daemon=True).start()

    def _poll_snapshot(self) -> None:
        if self.closing:
            return
        try:
            while True:
                snapshot, error = self.snapshot_queue.get_nowait()
                self.refresh_in_progress = False
                if error is not None:
                    self.status_text.set(f"Could not refresh processes: {error}")
                elif snapshot is not None:
                    self.processes = snapshot.processes
                    self.cpu_text.set(f"CPU  {snapshot.cpu:.1f}%")
                    self.memory_text.set(
                        f"MEMORY  {snapshot.memory_used / 1024**3:.1f} / "
                        f"{snapshot.memory_total / 1024**3:.1f} GB"
                    )
                    self.status_text.set(
                        f"{len(snapshot.processes)} processes"
                        f"  |  Updated {time.strftime('%H:%M:%S')}"
                    )
                    self._render_processes()
                self.root.after(REFRESH_MILLISECONDS, self._request_snapshot)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_snapshot)

    def _visible_processes(self) -> list[ProcessInfo]:
        query = self.search_text.get().strip().casefold()
        if not query:
            return self.processes.copy()
        return [
            process
            for process in self.processes
            if query
            in " ".join(
                (
                    str(process.pid),
                    str(process.ppid),
                    process.name,
                    process.username,
                    process.status,
                )
            ).casefold()
        ]

    def _render_processes(self) -> None:
        selected = self._selected_process()
        selected_pid = selected.pid if selected else None
        self.table.delete(*self.table.get_children(""))
        processes = self._visible_processes()
        if self.tree_mode:
            rows = process_tree(processes)
            visible_pids = {process.pid for process in processes}
            inserted_pids: set[int] = set()
            for process, _depth in rows:
                parent = (
                    str(process.ppid)
                    if process.ppid in visible_pids
                    and process.ppid in inserted_pids
                    and process.ppid != process.pid
                    else ""
                )
                self.table.insert(
                    parent,
                    tk.END,
                    iid=str(process.pid),
                    values=self._row_values(process),
                    open=True,
                )
                inserted_pids.add(process.pid)
        else:
            values = {
                "pid": lambda process: process.pid,
                "ppid": lambda process: process.ppid,
                "cpu": lambda process: process.cpu,
                "memory": lambda process: process.memory,
                "status": lambda process: process.status.casefold(),
                "username": lambda process: process.username.casefold(),
                "name": lambda process: process.name.casefold(),
            }
            processes.sort(
                key=values[self.sort_column],
                reverse=self.sort_descending,
            )
            for process in processes:
                self.table.insert(
                    "",
                    tk.END,
                    iid=str(process.pid),
                    values=self._row_values(process),
                )
        if selected_pid is not None and self.table.exists(str(selected_pid)):
            self.table.selection_set(str(selected_pid))
            self.table.see(str(selected_pid))
        elif self.table.get_children(""):
            first = self.table.get_children("")[0]
            self.table.selection_set(first)
            self._selection_changed()
        else:
            self.details_label.configure(text="No matching processes.")

    @staticmethod
    def _row_values(process: ProcessInfo) -> tuple[str | int, ...]:
        return (
            process.pid,
            process.ppid,
            f"{process.cpu:.1f}",
            f"{process.memory:.2f}",
            process.status,
            process.username,
            process.name,
        )

    def _selected_process(self) -> ProcessInfo | None:
        selection = self.table.selection()
        if not selection:
            return None
        try:
            selected_pid = int(selection[0])
        except ValueError:
            return None
        return next(
            (process for process in self.processes if process.pid == selected_pid),
            None,
        )

    def _selection_changed(self, _event: tk.Event | None = None) -> None:
        process = self._selected_process()
        if process is not None:
            self.details_label.configure(
                text=(
                    f"{process.name}  |  PID {process.pid}  |  PPID {process.ppid}"
                    f"  |  {process.username}  |  {process.status}"
                )
            )

    def _search_changed(self, *_args: str) -> None:
        self._render_processes()

    def _sort_by(self, column: str) -> None:
        if self.tree_mode:
            self.status_text.set("Turn off Tree view to sort the process list.")
            return
        if self.sort_column == column:
            self.sort_descending = not self.sort_descending
        else:
            self.sort_column = column
            self.sort_descending = column in ("cpu", "memory")
        self._render_processes()

    def _toggle_tree(self) -> None:
        self.tree_mode = not self.tree_mode
        self._render_processes()

    def _show_details(self, _event: tk.Event | None = None) -> None:
        process = self._selected_process()
        if process is None:
            return
        messagebox.showinfo(
            f"Process details - PID {process.pid}",
            (
                f"Name: {process.name}\n"
                f"PID: {process.pid}\n"
                f"Parent PID: {process.ppid}\n"
                f"User: {process.username}\n"
                f"Status: {process.status}\n"
                f"CPU: {process.cpu:.1f}%\n"
                f"Memory: {process.memory:.2f}%"
            ),
            parent=self.root,
        )

    def _terminate(self) -> None:
        process_info = self._selected_process()
        if process_info is None:
            self.status_text.set("Select a process to terminate.")
            return
        if not messagebox.askyesno(
            "Confirm termination",
            f"Send a terminate signal to {process_info.name} "
            f"(PID {process_info.pid})?",
            parent=self.root,
        ):
            return
        try:
            psutil.Process(process_info.pid).terminate()
            self.status_text.set(
                f"Terminate signal sent to PID {process_info.pid}."
            )
        except psutil.NoSuchProcess:
            self.status_text.set(f"PID {process_info.pid} no longer exists.")
        except psutil.AccessDenied:
            self.status_text.set(f"Permission denied for PID {process_info.pid}.")
        except psutil.Error as error:
            self.status_text.set(f"Could not terminate PID {process_info.pid}: {error}")

    def _toggle_suspend(self) -> None:
        process_info = self._selected_process()
        if process_info is None:
            self.status_text.set("Select a process to suspend or resume.")
            return
        try:
            process = psutil.Process(process_info.pid)
            is_stopped = process.status() == psutil.STATUS_STOPPED
            action = "resume" if is_stopped else "suspend"
            if not messagebox.askyesno(
                f"Confirm {action}",
                f"{action.capitalize()} {process_info.name} "
                f"(PID {process_info.pid})?",
                parent=self.root,
            ):
                return
            if is_stopped:
                process.resume()
            else:
                process.suspend()
            self.status_text.set(f"{action.capitalize()} signal sent to PID {process_info.pid}.")
        except psutil.NoSuchProcess:
            self.status_text.set(f"PID {process_info.pid} no longer exists.")
        except psutil.AccessDenied:
            self.status_text.set(f"Permission denied for PID {process_info.pid}.")
        except psutil.Error as error:
            self.status_text.set(f"Could not control PID {process_info.pid}: {error}")

    def close(self) -> None:
        self.closing = True
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    ProcessMonitor(root)
    root.mainloop()


if __name__ == "__main__":
    main()
