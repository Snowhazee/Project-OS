"""Desktop and Terminal process monitor for Linux and Windows."""

from __future__ import annotations

import argparse
import os
import platform
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from process_manager import (
    ProcessInfo,
    ProcessTracker,
    SystemStats,
    TreeRow,
    build_process_tree,
    control_kill,
    control_renice,
    control_resume,
    control_suspend,
    control_terminate,
    get_process_details,
)

REFRESH_MILLISECONDS = 1000

COLORS = {
    "background": "#0f172a",
    "surface": "#1e293b",
    "surface_alt": "#334155",
    "border": "#475569",
    "text": "#f8fafc",
    "muted": "#94a3b8",
    "accent": "#38bdf8",
    "accent_hover": "#7dd3fc",
    "danger": "#ef4444",
    "danger_hover": "#dc2626",
    "warning": "#f59e0b",
    "green": "#10b981",
}


class ProcessMonitorGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.tracker = ProcessTracker()
        self.processes: list[ProcessInfo] = []
        self.stats: SystemStats | None = None
        self.snapshot_queue: queue.Queue[tuple[tuple[list[ProcessInfo], SystemStats] | None, str | None]] = (
            queue.Queue()
        )
        self.refresh_in_progress = False
        self.closing = False
        self.tree_mode = False
        self.sort_column = "cpu"
        self.sort_descending = True
        self.search_text = tk.StringVar()
        self.status_text = tk.StringVar(value="Starting process monitor...")

        self.cpu_text = tk.StringVar(value="CPU: --%")
        self.memory_text = tk.StringVar(value="MEM: -- / -- GB (--%)")
        self.swap_text = tk.StringVar(value="SWP: -- / -- GB (--%)")
        self.tasks_text = tk.StringVar(value="Tasks: -- total")

        self._configure_window()
        self._build_ui()
        self._create_context_menu()

        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.search_text.trace_add("write", self._search_changed)
        self.root.after(100, self._poll_snapshot)
        self._request_snapshot()

    def _configure_window(self) -> None:
        self.root.title("Process Management Monitor (Linux & Windows)")
        self.root.geometry("1220x780")
        self.root.minsize(880, 520)
        self.root.configure(bg=COLORS["background"])

        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        font_table = ("DejaVu Sans Mono", 10) if platform.system() == "Linux" else ("Consolas", 10)

        style.configure(
            ".",
            background=COLORS["background"],
            foreground=COLORS["text"],
            font=("Segoe UI" if platform.system() == "Windows" else "Sans", 10),
        )
        style.configure("TFrame", background=COLORS["background"])
        style.configure("Card.TFrame", background=COLORS["surface"])
        style.configure("TLabel", background=COLORS["background"], foreground=COLORS["text"])
        style.configure("Card.TLabel", background=COLORS["surface"], foreground=COLORS["text"])
        style.configure("Muted.TLabel", background=COLORS["background"], foreground=COLORS["muted"])
        style.configure(
            "Title.TLabel",
            background=COLORS["background"],
            foreground=COLORS["text"],
            font=("Segoe UI" if platform.system() == "Windows" else "Sans", 18, "bold"),
        )
        style.configure(
            "Metric.TLabel",
            background=COLORS["surface"],
            foreground=COLORS["accent"],
            font=("Segoe UI" if platform.system() == "Windows" else "Sans", 11, "bold"),
        )
        style.configure(
            "TEntry",
            fieldbackground=COLORS["surface"],
            foreground=COLORS["text"],
            insertcolor=COLORS["text"],
            padding=6,
        )
        style.configure(
            "Accent.TButton",
            background=COLORS["accent"],
            foreground="#0f172a",
            padding=(10, 6),
            borderwidth=0,
            font=("Segoe UI" if platform.system() == "Windows" else "Sans", 9, "bold"),
        )
        style.map(
            "Accent.TButton",
            background=[("active", COLORS["accent_hover"]), ("disabled", COLORS["surface_alt"])],
        )
        style.configure(
            "Danger.TButton",
            background=COLORS["danger"],
            foreground="#ffffff",
            padding=(10, 6),
            borderwidth=0,
            font=("Segoe UI" if platform.system() == "Windows" else "Sans", 9, "bold"),
        )
        style.map("Danger.TButton", background=[("active", COLORS["danger_hover"])])
        style.configure(
            "Warning.TButton",
            background="#b45309",
            foreground="#ffffff",
            padding=(10, 6),
            borderwidth=0,
            font=("Segoe UI" if platform.system() == "Windows" else "Sans", 9, "bold"),
        )
        style.map("Warning.TButton", background=[("active", COLORS["warning"])])
        style.configure(
            "Standard.TButton",
            background=COLORS["surface_alt"],
            foreground=COLORS["text"],
            padding=(10, 6),
            borderwidth=0,
        )
        style.map("Standard.TButton", background=[("active", COLORS["border"])])

        style.configure(
            "Treeview",
            background=COLORS["surface"],
            fieldbackground=COLORS["surface"],
            foreground=COLORS["text"],
            font=font_table,
            rowheight=26,
            borderwidth=0,
        )
        style.configure(
            "Treeview.Heading",
            background=COLORS["surface_alt"],
            foreground=COLORS["text"],
            font=("Segoe UI" if platform.system() == "Windows" else "Sans", 9, "bold"),
            padding=(6, 8),
            relief="flat",
        )
        style.map(
            "Treeview",
            background=[("selected", "#0284c7")],
            foreground=[("selected", "#ffffff")],
        )

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=(18, 14))
        outer.pack(fill=tk.BOTH, expand=True)

        # 1. Header & System Resources Dashboard
        header = ttk.Frame(outer)
        header.pack(fill=tk.X, pady=(0, 12))

        title_block = ttk.Frame(header)
        title_block.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(title_block, text="Process Management Monitor", style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(
            title_block,
            text="Live system resource monitoring, hierarchy visualization, and signal control",
            style="Muted.TLabel",
        ).pack(anchor=tk.W, pady=(2, 0))

        # Metrics Card Frame
        cards_frame = ttk.Frame(header, style="Card.TFrame", padding=(12, 8))
        cards_frame.pack(side=tk.RIGHT)

        ttk.Label(cards_frame, textvariable=self.cpu_text, style="Metric.TLabel").pack(side=tk.LEFT, padx=(0, 16))
        ttk.Label(cards_frame, textvariable=self.memory_text, style="Metric.TLabel").pack(side=tk.LEFT, padx=(0, 16))
        ttk.Label(cards_frame, textvariable=self.swap_text, style="Metric.TLabel").pack(side=tk.LEFT, padx=(0, 16))
        ttk.Label(cards_frame, textvariable=self.tasks_text, style="Card.TLabel").pack(side=tk.LEFT)

        # 2. Controls Toolbar
        controls = ttk.Frame(outer)
        controls.pack(fill=tk.X, pady=(0, 10))

        search_frame = ttk.Frame(controls)
        search_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(search_frame, text="Filter:").pack(side=tk.LEFT, padx=(0, 6))
        self.search_entry = ttk.Entry(search_frame, textvariable=self.search_text, width=32)
        self.search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.tree_btn = ttk.Button(
            controls,
            text="View: Flat List",
            style="Standard.TButton",
            command=self._toggle_tree,
        )
        self.tree_btn.pack(side=tk.LEFT, padx=(12, 0))

        ttk.Button(
            controls,
            text="Refresh Now",
            style="Standard.TButton",
            command=self._request_snapshot,
        ).pack(side=tk.LEFT, padx=(8, 0))

        # 3. Process Table
        table_frame = ttk.Frame(outer)
        table_frame.pack(fill=tk.BOTH, expand=True)
        columns = ("pid", "ppid", "user", "nice", "cpu", "memory", "status", "name")
        self.table = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
        )

        headings = {
            "pid": ("PID", 75, tk.E),
            "ppid": ("PPID", 75, tk.E),
            "user": ("USER", 110, tk.W),
            "nice": ("NI", 50, tk.E),
            "cpu": ("CPU %", 85, tk.E),
            "memory": ("MEM %", 85, tk.E),
            "status": ("STATUS", 95, tk.W),
            "name": ("PROCESS / COMMAND HIERARCHY", 550, tk.W),
        }

        for column, (label, width, anchor) in headings.items():
            self.table.heading(
                column,
                text=label,
                anchor=anchor,
                command=lambda col=column: self._sort_by(col),
            )
            self.table.column(
                column,
                width=width,
                minwidth=45,
                anchor=anchor,
                stretch=column == "name",
            )

        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.table.yview)
        self.table.configure(yscrollcommand=scrollbar.set)
        self.table.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.table.bind("<<TreeviewSelect>>", self._selection_changed)
        self.table.bind("<Double-1>", self._show_details)
        self.table.bind("<Button-3>", self._on_right_click)  # Right-click context menu

        # 4. Action Buttons Footer
        footer = ttk.Frame(outer)
        footer.pack(fill=tk.X, pady=(10, 0))

        self.details_label = ttk.Label(
            footer,
            text="Select a process to view actions and details.",
            style="Muted.TLabel",
        )
        self.details_label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        ttk.Button(
            footer,
            text="Details",
            style="Standard.TButton",
            command=self._show_details,
        ).pack(side=tk.RIGHT, padx=(6, 0))

        ttk.Button(
            footer,
            text="Renice",
            style="Standard.TButton",
            command=self._renice_process,
        ).pack(side=tk.RIGHT, padx=(6, 0))

        ttk.Button(
            footer,
            text="Suspend / Resume",
            style="Warning.TButton",
            command=self._toggle_suspend,
        ).pack(side=tk.RIGHT, padx=(6, 0))

        ttk.Button(
            footer,
            text="Terminate (SIGTERM)",
            style="Danger.TButton",
            command=self._terminate,
        ).pack(side=tk.RIGHT, padx=(6, 0))

        ttk.Button(
            footer,
            text="Force Kill (SIGKILL)",
            style="Danger.TButton",
            command=self._kill,
        ).pack(side=tk.RIGHT)

        ttk.Label(
            outer,
            textvariable=self.status_text,
            style="Muted.TLabel",
        ).pack(anchor=tk.W, pady=(6, 0))

    def _create_context_menu(self) -> None:
        self.context_menu = tk.Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="Process Details", command=self._show_details)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Terminate (SIGTERM)", command=self._terminate)
        self.context_menu.add_command(label="Force Kill (SIGKILL)", command=self._kill)
        self.context_menu.add_command(label="Suspend / Resume", command=self._toggle_suspend)
        self.context_menu.add_command(label="Change Priority (Renice)", command=self._renice_process)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="Copy PID", command=self._copy_pid)

    def _on_right_click(self, event: tk.Event) -> None:
        item = self.table.identify_row(event.y)
        if item:
            self.table.selection_set(item)
            self._selection_changed()
            try:
                self.context_menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.context_menu.grab_release()

    def _copy_pid(self) -> None:
        proc = self._selected_process()
        if proc:
            self.root.clipboard_clear()
            self.root.clipboard_append(str(proc.pid))
            self.status_text.set(f"Copied PID {proc.pid} to clipboard.")

    def _request_snapshot(self) -> None:
        if self.refresh_in_progress or self.closing:
            return
        self.refresh_in_progress = True

        def collect() -> None:
            try:
                procs, stats = self.tracker.get_snapshot()
                self.snapshot_queue.put(((procs, stats), None))
            except Exception as err:
                self.snapshot_queue.put((None, str(err)))

        threading.Thread(target=collect, daemon=True).start()

    def _poll_snapshot(self) -> None:
        if self.closing:
            return
        try:
            while True:
                data, error = self.snapshot_queue.get_nowait()
                self.refresh_in_progress = False
                if error is not None:
                    self.status_text.set(f"Error collecting processes: {error}")
                elif data is not None:
                    self.processes, self.stats = data

                    # Update system metric labels
                    self.cpu_text.set(f"CPU: {self.stats.cpu_percent:4.1f}%")
                    mem_used_gb = self.stats.memory_used / (1024**3)
                    mem_tot_gb = self.stats.memory_total / (1024**3)
                    self.memory_text.set(f"MEM: {mem_used_gb:.1f} / {mem_tot_gb:.1f} GB ({self.stats.memory_percent:.0f}%)")

                    swp_used_gb = self.stats.swap_used / (1024**3)
                    swp_tot_gb = self.stats.swap_total / (1024**3)
                    self.swap_text.set(f"SWP: {swp_used_gb:.1f} / {swp_tot_gb:.1f} GB ({self.stats.swap_percent:.0f}%)")

                    self.tasks_text.set(
                        f"Tasks: {self.stats.total_processes} total "
                        f"({self.stats.running_processes} run, {self.stats.sleeping_processes} sleep, {self.stats.stopped_processes} stop)"
                    )
                    self.status_text.set(
                        f"{len(self.processes)} processes tracked  |  Last updated: {time.strftime('%H:%M:%S')}"
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
            p
            for p in self.processes
            if query in str(p.pid)
            or query in str(p.ppid)
            or query in p.name.casefold()
            or query in p.username.casefold()
            or query in p.status.casefold()
        ]

    def _render_processes(self) -> None:
        selected = self._selected_process()
        selected_pid = selected.pid if selected else None
        self.table.delete(*self.table.get_children(""))
        processes = self._visible_processes()

        if self.tree_mode:
            tree_rows: list[TreeRow] = build_process_tree(processes)
            for row in tree_rows:
                p = row.process
                display_name = f"{row.prefix}{p.name}"
                values = (
                    p.pid,
                    p.ppid,
                    p.username,
                    p.nice,
                    f"{p.cpu:5.1f}",
                    f"{p.memory:5.2f}",
                    p.status,
                    display_name,
                )
                self.table.insert("", tk.END, iid=str(p.pid), values=values)
        else:
            key_funcs = {
                "pid": lambda p: p.pid,
                "ppid": lambda p: p.ppid,
                "user": lambda p: p.username.casefold(),
                "nice": lambda p: p.nice,
                "cpu": lambda p: p.cpu,
                "memory": lambda p: p.memory,
                "status": lambda p: p.status.casefold(),
                "name": lambda p: p.name.casefold(),
            }
            sort_fn = key_funcs.get(self.sort_column, lambda p: p.cpu)
            processes.sort(key=sort_fn, reverse=self.sort_descending)

            for p in processes:
                values = (
                    p.pid,
                    p.ppid,
                    p.username,
                    p.nice,
                    f"{p.cpu:5.1f}",
                    f"{p.memory:5.2f}",
                    p.status,
                    p.name,
                )
                self.table.insert("", tk.END, iid=str(p.pid), values=values)

        if selected_pid is not None and self.table.exists(str(selected_pid)):
            self.table.selection_set(str(selected_pid))
            self.table.see(str(selected_pid))
        elif self.table.get_children(""):
            first = self.table.get_children("")[0]
            self.table.selection_set(first)
            self._selection_changed()
        else:
            self.details_label.configure(text="No matching processes found.")

    def _selected_process(self) -> ProcessInfo | None:
        selection = self.table.selection()
        if not selection:
            return None
        try:
            pid = int(selection[0])
            return next((p for p in self.processes if p.pid == pid), None)
        except ValueError:
            return None

    def _selection_changed(self, _event: tk.Event | None = None) -> None:
        proc = self._selected_process()
        if proc is not None:
            self.details_label.configure(
                text=(
                    f"Selected: {proc.name} (PID: {proc.pid}, PPID: {proc.ppid})  |  "
                    f"User: {proc.username}  |  State: {proc.status}  |  "
                    f"CPU: {proc.cpu:.1f}%  |  MEM: {proc.memory:.2f}% ({(proc.memory_rss / 1024**2):.1f} MB)"
                )
            )

    def _search_changed(self, *_args: str) -> None:
        self._render_processes()

    def _sort_by(self, column: str) -> None:
        if self.tree_mode:
            self.status_text.set("Switch to Flat List view to sort columns.")
            return
        if self.sort_column == column:
            self.sort_descending = not self.sort_descending
        else:
            self.sort_column = column
            self.sort_descending = column in ("cpu", "memory")
        self._render_processes()

    def _toggle_tree(self) -> None:
        self.tree_mode = not self.tree_mode
        self.tree_btn.configure(text="View: Tree Hierarchy" if self.tree_mode else "View: Flat List")
        self._render_processes()

    def _show_details(self, _event: tk.Event | None = None) -> None:
        proc = self._selected_process()
        if proc is None:
            return

        details = get_process_details(proc.pid)
        win = tk.Toplevel(self.root)
        win.title(f"Process Details - {proc.name} (PID {proc.pid})")
        win.geometry("640x520")
        win.configure(bg=COLORS["surface"])
        win.transient(self.root)
        win.grab_set()

        content = ttk.Frame(win, padding=16, style="Card.TFrame")
        content.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            content,
            text=f"Process: {proc.name} (PID {proc.pid})",
            style="Title.TLabel",
        ).pack(anchor=tk.W, pady=(0, 12))

        table_area = ttk.Frame(content, style="Card.TFrame")
        table_area.pack(fill=tk.BOTH, expand=True)

        row_idx = 0
        for k, v in details.items():
            ttk.Label(table_area, text=f"{k}:", style="Metric.TLabel").grid(
                row=row_idx, column=0, sticky=tk.W, pady=3, padx=(0, 10)
            )
            val_lbl = ttk.Label(table_area, text=str(v), style="Card.TLabel", wraplength=460)
            val_lbl.grid(row=row_idx, column=1, sticky=tk.W, pady=3)
            row_idx += 1

        btn_row = ttk.Frame(content, style="Card.TFrame")
        btn_row.pack(fill=tk.X, pady=(16, 0))

        ttk.Button(btn_row, text="Close", style="Standard.TButton", command=win.destroy).pack(side=tk.RIGHT)
        ttk.Button(
            btn_row,
            text="Force Kill (SIGKILL)",
            style="Danger.TButton",
            command=lambda: [self._kill(), win.destroy()],
        ).pack(side=tk.RIGHT, padx=(0, 8))
        ttk.Button(
            btn_row,
            text="Terminate (SIGTERM)",
            style="Warning.TButton",
            command=lambda: [self._terminate(), win.destroy()],
        ).pack(side=tk.RIGHT, padx=(0, 8))

    def _terminate(self) -> None:
        proc = self._selected_process()
        if proc is None:
            self.status_text.set("Select a process to terminate.")
            return
        if not messagebox.askyesno(
            "Confirm Termination",
            f"Send SIGTERM to {proc.name} (PID {proc.pid})?\n\nThis requests the process to terminate gracefully.",
            parent=self.root,
        ):
            return
        success, msg = control_terminate(proc.pid)
        self.status_text.set(msg)
        self._request_snapshot()

    def _kill(self) -> None:
        proc = self._selected_process()
        if proc is None:
            self.status_text.set("Select a process to kill.")
            return
        if not messagebox.askyesno(
            "Confirm Force Kill",
            f"Force KILL (SIGKILL) {proc.name} (PID {proc.pid})?\n\n"
            "Warning: This immediately terminates the process without cleanup.",
            parent=self.root,
        ):
            return
        success, msg = control_kill(proc.pid)
        self.status_text.set(msg)
        self._request_snapshot()

    def _toggle_suspend(self) -> None:
        proc = self._selected_process()
        if proc is None:
            self.status_text.set("Select a process to suspend or resume.")
            return
        is_stopped = proc.status.lower() in ("stopped", "t")
        action = "resume (SIGCONT)" if is_stopped else "suspend (SIGSTOP)"
        if not messagebox.askyesno(
            f"Confirm {action.title()}",
            f"{action.title()} process {proc.name} (PID {proc.pid})?",
            parent=self.root,
        ):
            return
        if is_stopped:
            success, msg = control_resume(proc.pid)
        else:
            success, msg = control_suspend(proc.pid)
        self.status_text.set(msg)
        self._request_snapshot()

    def _renice_process(self) -> None:
        proc = self._selected_process()
        if proc is None:
            self.status_text.set("Select a process to renice.")
            return
        val = simpledialog.askinteger(
            "Renice Process",
            f"Enter new nice value for {proc.name} (PID {proc.pid})\n"
            f"Range: -20 (highest priority) to 19 (lowest priority).\n"
            f"Current nice: {proc.nice}",
            initialvalue=proc.nice,
            minvalue=-20,
            maxvalue=19,
            parent=self.root,
        )
        if val is not None:
            success, msg = control_renice(proc.pid, val)
            self.status_text.set(msg)
            self._request_snapshot()

    def close(self) -> None:
        self.closing = True
        self.root.destroy()


def run_gui() -> None:
    root = tk.Tk()
    ProcessMonitorGUI(root)
    root.mainloop()


def run_tui() -> None:
    try:
        from process_monitor_tui import main as tui_main
        tui_main()
    except ImportError:
        import curses
        curses.wrapper(lambda stdscr: None)


def main() -> None:
    parser = argparse.ArgumentParser(description="Process Management Monitor for Linux & Windows")
    parser.add_argument("--gui", action="store_true", help="Launch GUI interface (requires X11 / Wayland on Linux)")
    parser.add_argument("--tui", "--cli", action="store_true", help="Launch Terminal / Curses TUI interface")
    args = parser.parse_args()

    if args.tui:
        run_tui()
        return

    if args.gui:
        run_gui()
        return

    # Default auto-detection:
    # On Linux, if DISPLAY or WAYLAND_DISPLAY is not set, launch TUI automatically
    is_linux = platform.system() == "Linux"
    has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))

    if is_linux and not has_display:
        print("[*] No graphical display detected (DISPLAY not set). Launching Terminal (TUI) mode...")
        run_tui()
    else:
        try:
            run_gui()
        except tk.TclError as exc:
            print(f"[*] GUI initialization failed ({exc}). Falling back to Terminal (TUI) mode...")
            run_tui()


if __name__ == "__main__":
    main()
