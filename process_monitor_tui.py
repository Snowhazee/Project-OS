"""Terminal (TUI) process monitor for Linux using curses and psutil."""

from __future__ import annotations

import curses
import os
import platform
import socket
import sys
import time
from typing import Any

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


def format_bytes(bytes_val: int) -> str:
    """Format bytes into human-readable B, K, M, G units."""
    if bytes_val < 1024:
        return f"{bytes_val} B"
    kb = bytes_val / 1024
    if kb < 1024:
        return f"{kb:.1f} KB"
    mb = kb / 1024
    if mb < 1024:
        return f"{mb:.1f} MB"
    gb = mb / 1024
    return f"{gb:.2f} GB"


def draw_bar(width: int, percent: float) -> str:
    """Render a text progress bar."""
    if width <= 0:
        return ""
    percent = max(0.0, min(100.0, percent))
    filled_len = int(round((percent / 100.0) * width))
    bar = "|" * filled_len + " " * (width - filled_len)
    return f"[{bar}] {percent:5.1f}%"


class TUIProcessMonitor:
    def __init__(self, stdscr: curses.window) -> None:
        self.stdscr = stdscr
        self.tracker = ProcessTracker()
        self.processes: list[ProcessInfo] = []
        self.stats: SystemStats | None = None
        self.tree_mode: bool = False
        self.sort_key: str = "cpu"
        self.sort_descending: bool = True
        self.filter_query: str = ""
        self.selected_index: int = 0
        self.scroll_offset: int = 0
        self.status_message: str = "Welcome to Linux Process Monitor. Press [?] for help."
        self.status_time: float = time.time()
        self.running: bool = True

        self._init_curses()

    def _init_curses(self) -> None:
        curses.curs_set(0)
        self.stdscr.nodelay(True)
        self.stdscr.keypad(True)
        curses.use_default_colors()

        if curses.has_colors():
            # (Pair ID, FG, BG)
            curses.init_pair(1, curses.COLOR_CYAN, -1)     # Header / Accent
            curses.init_pair(2, curses.COLOR_GREEN, -1)    # Good / Stats
            curses.init_pair(3, curses.COLOR_YELLOW, -1)   # Warning / Nice
            curses.init_pair(4, curses.COLOR_RED, -1)      # Danger / Terminate
            curses.init_pair(5, curses.COLOR_BLACK, curses.COLOR_CYAN)   # Selected row
            curses.init_pair(6, curses.COLOR_WHITE, curses.COLOR_BLUE)   # Top Bar
            curses.init_pair(7, curses.COLOR_BLACK, curses.COLOR_WHITE)  # Key shortcut bar
            curses.init_pair(8, curses.COLOR_MAGENTA, -1)  # Tree connector

    def set_status(self, message: str) -> None:
        self.status_message = message
        self.status_time = time.time()

    def run(self) -> None:
        last_refresh = 0.0
        while self.running:
            now = time.time()
            if now - last_refresh >= 1.0 or not self.processes:
                self.processes, self.stats = self.tracker.get_snapshot()
                last_refresh = now

            self._draw()
            self._handle_input()
            time.sleep(0.05)

    def _get_visible_rows(self) -> list[tuple[ProcessInfo, str]]:
        """Return list of (ProcessInfo, display_name_or_tree_prefix)."""
        filtered = self.processes
        if self.filter_query:
            q = self.filter_query.casefold()
            filtered = [
                p
                for p in self.processes
                if q in str(p.pid)
                or q in str(p.ppid)
                or q in p.name.casefold()
                or q in p.username.casefold()
                or q in p.status.casefold()
            ]

        if self.tree_mode:
            tree_rows: list[TreeRow] = build_process_tree(filtered)
            return [(r.process, f"{r.prefix}{r.process.name}") for r in tree_rows]

        key_funcs = {
            "pid": lambda p: p.pid,
            "ppid": lambda p: p.ppid,
            "cpu": lambda p: p.cpu,
            "memory": lambda p: p.memory,
            "name": lambda p: p.name.casefold(),
            "user": lambda p: p.username.casefold(),
            "status": lambda p: p.status.casefold(),
            "nice": lambda p: p.nice,
        }
        sort_func = key_funcs.get(self.sort_key, lambda p: p.cpu)
        sorted_procs = sorted(filtered, key=sort_func, reverse=self.sort_descending)
        return [(p, p.name) for p in sorted_procs]

    def _draw(self) -> None:
        self.stdscr.erase()
        max_y, max_x = self.stdscr.getmaxyx()
        if max_y < 12 or max_x < 60:
            try:
                self.stdscr.addstr(0, 0, "Terminal window too small (min 60x12).")
            except curses.error:
                pass
            self.stdscr.refresh()
            return

        # 1. Header Banner
        hostname = socket.gethostname()
        top_title = f" PROCESS MANAGEMENT MONITOR (Linux)  |  Host: {hostname}  |  {time.strftime('%H:%M:%S')} "
        try:
            self.stdscr.addstr(0, 0, top_title.ljust(max_x)[:max_x], curses.color_pair(6) | curses.A_BOLD)
        except curses.error:
            pass

        # 2. System Resource Meters
        if self.stats:
            meter_w = max(10, min(30, max_x - 45))
            cpu_bar = draw_bar(meter_w, self.stats.cpu_percent)
            mem_bar = draw_bar(meter_w, self.stats.memory_percent)
            swp_bar = draw_bar(meter_w, self.stats.swap_percent)

            mem_text = f"{format_bytes(self.stats.memory_used)} / {format_bytes(self.stats.memory_total)}"
            swp_text = f"{format_bytes(self.stats.swap_used)} / {format_bytes(self.stats.swap_total)}"

            try:
                self.stdscr.addstr(1, 1, "CPU:", curses.A_BOLD)
                self.stdscr.addstr(1, 6, cpu_bar, curses.color_pair(2) | curses.A_BOLD)
                self.stdscr.addstr(1, 8 + len(cpu_bar), f"({self.stats.cpu_count} logical cores)")

                self.stdscr.addstr(2, 1, "MEM:", curses.A_BOLD)
                self.stdscr.addstr(2, 6, mem_bar, curses.color_pair(1) | curses.A_BOLD)
                self.stdscr.addstr(2, 8 + len(mem_bar), mem_text)

                self.stdscr.addstr(3, 1, "SWP:", curses.A_BOLD)
                self.stdscr.addstr(3, 6, swp_bar, curses.color_pair(3) | curses.A_BOLD)
                self.stdscr.addstr(3, 8 + len(swp_bar), swp_text)

                tasks_line = (
                    f"Tasks: {self.stats.total_processes} total, "
                    f"{self.stats.running_processes} running, "
                    f"{self.stats.sleeping_processes} sleeping, "
                    f"{self.stats.stopped_processes} stopped, "
                    f"{self.stats.zombie_processes} zombie"
                )
                self.stdscr.addstr(4, 1, tasks_line[: max_x - 2], curses.A_DIM)
            except curses.error:
                pass

        # 3. Status and Filter Indicator
        mode_str = "TREE" if self.tree_mode else f"LIST (Sort: {self.sort_key.upper()} {'DESC' if self.sort_descending else 'ASC'})"
        filter_str = f"Filter: '{self.filter_query}'" if self.filter_query else "Filter: None"
        info_line = f"Mode: {mode_str}  |  {filter_str}  |  {self.status_message}"
        try:
            self.stdscr.addstr(5, 1, info_line[: max_x - 2], curses.color_pair(1))
        except curses.error:
            pass

        # 4. Table Column Header
        header_y = 6
        table_start_y = 7
        footer_y = max_y - 1
        visible_rows_count = max(0, footer_y - table_start_y)

        header_fmt = "{:<7} {:<7} {:<12} {:>4} {:>7} {:>7} {:<9} {}"
        header_text = header_fmt.format("PID", "PPID", "USER", "NI", "CPU%", "MEM%", "STATE", "COMMAND / TREE")
        try:
            self.stdscr.addstr(header_y, 0, header_text.ljust(max_x)[:max_x], curses.A_REVERSE | curses.A_BOLD)
        except curses.error:
            pass

        # 5. Process Rows
        rows = self._get_visible_rows()
        if not rows:
            try:
                self.stdscr.addstr(table_start_y, 2, "No matching processes found.", curses.A_DIM)
            except curses.error:
                pass
        else:
            # Clamp selection and scroll
            self.selected_index = max(0, min(self.selected_index, len(rows) - 1))
            if self.selected_index < self.scroll_offset:
                self.scroll_offset = self.selected_index
            elif self.selected_index >= self.scroll_offset + visible_rows_count:
                self.scroll_offset = self.selected_index - visible_rows_count + 1

            for i in range(visible_rows_count):
                row_idx = self.scroll_offset + i
                if row_idx >= len(rows):
                    break
                proc, display_name = rows[row_idx]
                curr_y = table_start_y + i

                line_text = header_fmt.format(
                    proc.pid,
                    proc.ppid,
                    proc.username[:12],
                    proc.nice,
                    f"{proc.cpu:5.1f}",
                    f"{proc.memory:5.1f}",
                    proc.status[:9],
                    display_name,
                )
                padded_line = line_text.ljust(max_x)[: max_x - 1]

                is_selected = row_idx == self.selected_index
                style = curses.color_pair(5) | curses.A_BOLD if is_selected else curses.A_NORMAL

                try:
                    self.stdscr.addstr(curr_y, 0, padded_line, style)
                except curses.error:
                    pass

        # 6. Bottom Keybindings Bar
        bottom_keys = (
            " [q]Quit [t]Tree [/]Filter [k]Action [x]Term [K]Kill [s]Suspend/Resume [r]Renice [d]Details [?]Help "
        )
        try:
            self.stdscr.addstr(footer_y, 0, bottom_keys.ljust(max_x)[:max_x], curses.color_pair(7))
        except curses.error:
            pass

        self.stdscr.refresh()

    def _handle_input(self) -> None:
        try:
            key = self.stdscr.getch()
        except curses.error:
            return

        if key == -1:
            return

        rows = self._get_visible_rows()

        if key in (ord("q"), ord("Q")):
            self.running = False
        elif key in (curses.KEY_UP, ord("k")):
            if self.selected_index > 0:
                self.selected_index -= 1
        elif key in (curses.KEY_DOWN, ord("j")):
            if self.selected_index < len(rows) - 1:
                self.selected_index += 1
        elif key in (curses.KEY_PPAGE, 2):  # Page Up
            self.selected_index = max(0, self.selected_index - 10)
        elif key in (curses.KEY_NPAGE, 6):  # Page Down
            self.selected_index = min(len(rows) - 1, self.selected_index + 10)
        elif key in (curses.KEY_HOME, ord("g")):
            self.selected_index = 0
        elif key in (curses.KEY_END, ord("G")):
            self.selected_index = max(0, len(rows) - 1)
        elif key in (ord("t"), ord("T")):
            self.tree_mode = not self.tree_mode
            self.set_status(f"Tree hierarchy {'enabled' if self.tree_mode else 'disabled'}.")
        elif key in (ord("/"),):
            self._prompt_filter()
        elif key in (27,):  # Escape
            if self.filter_query:
                self.filter_query = ""
                self.set_status("Filter cleared.")
        elif key in (ord("c"), ord("C")):
            self._set_sort("cpu")
        elif key in (ord("m"), ord("M")):
            self._set_sort("memory")
        elif key in (ord("p"), ord("P")):
            self._set_sort("pid")
        elif key in (ord("n"), ord("N")):
            self._set_sort("name")
        elif key in (ord("u"), ord("U")):
            self._set_sort("user")
        elif key in (ord("k"),):
            self._open_action_menu()
        elif key in (ord("x"),):
            self._quick_action("terminate")
        elif key in (ord("K"),):
            self._quick_action("kill")
        elif key in (ord("s"), ord("S")):
            self._quick_action("suspend_resume")
        elif key in (ord("r"), ord("R")):
            self._prompt_renice()
        elif key in (10, 13, curses.KEY_ENTER, ord("d"), ord("D")):
            self._show_details_modal()
        elif key in (ord("?"), ord("h"), ord("H")):
            self._show_help_modal()

    def _set_sort(self, column: str) -> None:
        if self.tree_mode:
            self.set_status("Disable Tree mode ([t]) to sort flat process list.")
            return
        if self.sort_key == column:
            self.sort_descending = not self.sort_descending
        else:
            self.sort_key = column
            self.sort_descending = column in ("cpu", "memory")
        self.set_status(f"Sorted by {column.upper()} ({'DESC' if self.sort_descending else 'ASC'}).")

    def _get_selected_proc(self) -> ProcessInfo | None:
        rows = self._get_visible_rows()
        if not rows or self.selected_index >= len(rows):
            return None
        return rows[self.selected_index][0]

    def _prompt_filter(self) -> None:
        curses.echo()
        curses.curs_set(1)
        max_y, max_x = self.stdscr.getmaxyx()
        prompt = "Filter processes (Enter to submit, empty to clear): "
        self.stdscr.addstr(max_y - 1, 0, " " * (max_x - 1))
        self.stdscr.addstr(max_y - 1, 0, prompt, curses.A_BOLD)
        self.stdscr.refresh()

        self.stdscr.nodelay(False)
        try:
            query = self.stdscr.getstr(max_y - 1, len(prompt)).decode("utf-8", "ignore").strip()
            self.filter_query = query
            self.selected_index = 0
            self.set_status(f"Filter set to: '{query}'" if query else "Filter cleared.")
        except Exception:
            pass
        finally:
            curses.noecho()
            curses.curs_set(0)
            self.stdscr.nodelay(True)

    def _quick_action(self, action_type: str) -> None:
        proc = self._get_selected_proc()
        if proc is None:
            self.set_status("No process selected.")
            return

        if action_type == "terminate":
            if self._confirm_action(f"Send SIGTERM to {proc.name} (PID {proc.pid})?"):
                success, msg = control_terminate(proc.pid)
                self.set_status(msg)
        elif action_type == "kill":
            if self._confirm_action(f"Force KILL (SIGKILL) {proc.name} (PID {proc.pid})?"):
                success, msg = control_kill(proc.pid)
                self.set_status(msg)
        elif action_type == "suspend_resume":
            is_stopped = proc.status.lower() in ("stopped", "t")
            act_name = "Resume (SIGCONT)" if is_stopped else "Suspend (SIGSTOP)"
            if self._confirm_action(f"{act_name} {proc.name} (PID {proc.pid})?"):
                if is_stopped:
                    success, msg = control_resume(proc.pid)
                else:
                    success, msg = control_suspend(proc.pid)
                self.set_status(msg)

    def _confirm_action(self, prompt: str) -> bool:
        max_y, max_x = self.stdscr.getmaxyx()
        query = f" {prompt} [y/N]: "
        self.stdscr.addstr(max_y - 1, 0, " " * (max_x - 1))
        self.stdscr.addstr(max_y - 1, 0, query[: max_x - 1], curses.color_pair(4) | curses.A_BOLD)
        self.stdscr.refresh()

        self.stdscr.nodelay(False)
        ch = self.stdscr.getch()
        self.stdscr.nodelay(True)
        return ch in (ord("y"), ord("Y"))

    def _prompt_renice(self) -> None:
        proc = self._get_selected_proc()
        if proc is None:
            self.set_status("No process selected.")
            return

        curses.echo()
        curses.curs_set(1)
        max_y, max_x = self.stdscr.getmaxyx()
        prompt = f"Set nice value for {proc.name} (PID {proc.pid}) [-20 to 19, currently {proc.nice}]: "
        self.stdscr.addstr(max_y - 1, 0, " " * (max_x - 1))
        self.stdscr.addstr(max_y - 1, 0, prompt[: max_x - 1], curses.A_BOLD)
        self.stdscr.refresh()

        self.stdscr.nodelay(False)
        try:
            val_str = self.stdscr.getstr(max_y - 1, min(len(prompt), max_x - 5)).decode("utf-8", "ignore").strip()
            if val_str:
                new_nice = int(val_str)
                if -20 <= new_nice <= 19:
                    success, msg = control_renice(proc.pid, new_nice)
                    self.set_status(msg)
                else:
                    self.set_status("Nice value must be between -20 (highest priority) and 19 (lowest priority).")
        except ValueError:
            self.set_status("Invalid number entered for nice value.")
        except Exception as exc:
            self.set_status(f"Error: {exc}")
        finally:
            curses.noecho()
            curses.curs_set(0)
            self.stdscr.nodelay(True)

    def _open_action_menu(self) -> None:
        proc = self._get_selected_proc()
        if proc is None:
            self.set_status("No process selected.")
            return

        max_y, max_x = self.stdscr.getmaxyx()
        h, w = 12, 60
        start_y = max(1, (max_y - h) // 2)
        start_x = max(1, (max_x - w) // 2)

        win = curses.newwin(h, w, start_y, start_x)
        win.keypad(True)
        win.box()

        win.addstr(0, 2, f" Process Control - {proc.name} (PID {proc.pid}) ", curses.A_BOLD | curses.color_pair(1))
        win.addstr(2, 4, "1. Terminate (SIGTERM - polite request)")
        win.addstr(3, 4, "2. Force Kill (SIGKILL - unconditional kill)")
        win.addstr(4, 4, "3. Suspend (SIGSTOP - pause execution)")
        win.addstr(5, 4, "4. Resume (SIGCONT - continue execution)")
        win.addstr(6, 4, "5. Renice (Change process priority)")
        win.addstr(7, 4, "6. Process Details (Inspect full metadata)")
        win.addstr(9, 4, "Press [1-6] to choose, or any other key to cancel", curses.A_DIM)
        win.refresh()

        ch = win.getch()
        del win

        if ch == ord("1"):
            self._quick_action("terminate")
        elif ch == ord("2"):
            self._quick_action("kill")
        elif ch == ord("3"):
            success, msg = control_suspend(proc.pid)
            self.set_status(msg)
        elif ch == ord("4"):
            success, msg = control_resume(proc.pid)
            self.set_status(msg)
        elif ch == ord("5"):
            self._prompt_renice()
        elif ch in (ord("6"), 10, 13):
            self._show_details_modal()

    def _show_details_modal(self) -> None:
        proc = self._get_selected_proc()
        if proc is None:
            return

        details = get_process_details(proc.pid)
        max_y, max_x = self.stdscr.getmaxyx()
        h = min(20, max_y - 2)
        w = min(75, max_x - 4)
        start_y = max(1, (max_y - h) // 2)
        start_x = max(1, (max_x - w) // 2)

        win = curses.newwin(h, w, start_y, start_x)
        win.keypad(True)
        win.box()

        title = f" Process Details: PID {proc.pid} ({proc.name}) "
        win.addstr(0, 2, title[: w - 4], curses.A_BOLD | curses.color_pair(1))

        curr_y = 2
        for key, val in details.items():
            if curr_y >= h - 2:
                break
            line = f"{key:<16}: {val}"
            win.addstr(curr_y, 2, line[: w - 4])
            curr_y += 1

        win.addstr(h - 2, 2, "Press [Enter], [Esc], or [q] to close", curses.A_REVERSE)
        win.refresh()

        while True:
            ch = win.getch()
            if ch in (10, 13, 27, ord("q"), ord("Q"), ord("d"), ord("D")):
                break
            time.sleep(0.05)
        del win

    def _show_help_modal(self) -> None:
        max_y, max_x = self.stdscr.getmaxyx()
        h = min(22, max_y - 2)
        w = min(70, max_x - 4)
        start_y = max(1, (max_y - h) // 2)
        start_x = max(1, (max_x - w) // 2)

        win = curses.newwin(h, w, start_y, start_x)
        win.keypad(True)
        win.box()

        win.addstr(0, 2, " Linux Process Monitor - Help & Controls ", curses.A_BOLD | curses.color_pair(1))

        shortcuts = [
            ("Up / Down / j / k", "Navigate process list"),
            ("PgUp / PgDown", "Scroll 10 rows"),
            ("Home / End", "Jump to first / last process"),
            ("t", "Toggle Process Tree (Hierarchy view)"),
            ("/", "Search and filter processes"),
            ("Esc", "Clear filter"),
            ("c, m, p, n, u", "Sort by CPU%, MEM%, PID, Name, User"),
            ("k", "Open Process Control action menu"),
            ("x", "Send SIGTERM (Polite termination)"),
            ("K", "Send SIGKILL (Force kill immediately)"),
            ("s", "Suspend (SIGSTOP) or Resume (SIGCONT)"),
            ("r", "Renice (Change process priority -20..19)"),
            ("d or Enter", "Show full process details"),
            ("q", "Quit monitor"),
        ]

        for i, (key, desc) in enumerate(shortcuts):
            if 2 + i >= h - 2:
                break
            win.addstr(2 + i, 3, f"{key:<20}", curses.color_pair(2) | curses.A_BOLD)
            win.addstr(2 + i, 24, f"{desc}"[: w - 26])

        win.addstr(h - 2, 3, "Press [Enter], [Esc], or [q] to return", curses.A_REVERSE)
        win.refresh()

        while True:
            ch = win.getch()
            if ch in (10, 13, 27, ord("q"), ord("Q"), ord("?"), ord("h")):
                break
            time.sleep(0.05)
        del win


def main() -> None:
    try:
        curses.wrapper(lambda stdscr: TUIProcessMonitor(stdscr).run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

