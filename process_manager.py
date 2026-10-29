"""Core process management and monitoring logic for Linux and Windows."""

from __future__ import annotations

import datetime
import os
import platform
import time
from dataclasses import dataclass

import psutil


@dataclass
class ProcessInfo:
    pid: int
    ppid: int
    name: str
    username: str
    status: str
    cpu: float
    memory: float
    memory_rss: int = 0
    memory_vms: int = 0
    num_threads: int = 1
    nice: int = 0
    create_time: float = 0.0
    cmdline: str = ""


@dataclass
class SystemStats:
    cpu_percent: float
    cpu_count: int
    memory_total: int
    memory_used: int
    memory_percent: float
    swap_total: int = 0
    swap_used: int = 0
    swap_percent: float = 0.0
    total_processes: int = 0
    running_processes: int = 0
    sleeping_processes: int = 0
    stopped_processes: int = 0
    zombie_processes: int = 0


@dataclass
class TreeRow:
    process: ProcessInfo
    depth: int
    prefix: str
    is_last: bool


class ProcessTracker:
    """Maintains cached psutil.Process instances for accurate CPU% and statistics."""

    def __init__(self) -> None:
        self._proc_cache: dict[int, psutil.Process] = {}
        # Prime system CPU percentage
        psutil.cpu_percent(interval=None)

    def get_snapshot(self) -> tuple[list[ProcessInfo], SystemStats]:
        """Collect live process information and system resource usage."""
        # System resource usage
        cpu_percent = psutil.cpu_percent(interval=None)
        cpu_count = psutil.cpu_count(logical=True) or 1
        vm = psutil.virtual_memory()
        swap = psutil.swap_memory()

        total_memory = vm.total or 1
        processes: list[ProcessInfo] = []

        total_count = 0
        running_count = 0
        sleeping_count = 0
        stopped_count = 0
        zombie_count = 0

        seen_pids: set[int] = set()

        for proc in psutil.process_iter(
            attrs=[
                "pid",
                "ppid",
                "name",
                "username",
                "status",
                "memory_info",
                "num_threads",
                "nice",
                "create_time",
            ]
        ):
            try:
                info = proc.info
                pid = info["pid"]
                seen_pids.add(pid)
                total_count += 1

                status_val = (info["status"] or "unknown").lower()
                if status_val in ("running", psutil.STATUS_RUNNING):
                    running_count += 1
                elif status_val in (
                    "sleeping",
                    "idle",
                    "disk-sleep",
                    psutil.STATUS_SLEEPING,
                    getattr(psutil, "STATUS_IDLE", "idle"),
                    getattr(psutil, "STATUS_DISK_SLEEP", "disk-sleep"),
                ):
                    sleeping_count += 1
                elif status_val in ("stopped", psutil.STATUS_STOPPED):
                    stopped_count += 1
                elif status_val in ("zombie", "dead", psutil.STATUS_ZOMBIE, getattr(psutil, "STATUS_DEAD", "dead")):
                    zombie_count += 1

                # Reuse Process object in cache for accurate CPU delta
                cached_proc = self._proc_cache.get(pid)
                if cached_proc is None:
                    cached_proc = proc
                    self._proc_cache[pid] = proc
                    # First call primes the timer
                    cached_proc.cpu_percent(interval=None)
                    cpu_val = 0.0
                else:
                    try:
                        cpu_val = cached_proc.cpu_percent(interval=None)
                    except (psutil.NoSuchProcess, psutil.ZombieProcess):
                        cpu_val = 0.0

                mem_info = info.get("memory_info")
                rss = mem_info.rss if mem_info else 0
                vms = mem_info.vms if mem_info else 0
                mem_percent = (rss / total_memory * 100.0) if total_memory else 0.0

                processes.append(
                    ProcessInfo(
                        pid=pid,
                        ppid=info["ppid"] or 0,
                        name=info["name"] or "unknown",
                        username=info["username"] or "?",
                        status=info["status"] or "unknown",
                        cpu=cpu_val,
                        memory=mem_percent,
                        memory_rss=rss,
                        memory_vms=vms,
                        num_threads=info.get("num_threads") or 1,
                        nice=info.get("nice") or 0,
                        create_time=info.get("create_time") or 0.0,
                    )
                )
            except (psutil.NoSuchProcess, psutil.ZombieProcess, psutil.AccessDenied):
                continue

        # Purge dead processes from cache
        dead_pids = set(self._proc_cache.keys()) - seen_pids
        for dead_pid in dead_pids:
            self._proc_cache.pop(dead_pid, None)

        stats = SystemStats(
            cpu_percent=cpu_percent,
            cpu_count=cpu_count,
            memory_total=vm.total,
            memory_used=vm.used,
            memory_percent=vm.percent,
            swap_total=swap.total,
            swap_used=swap.used,
            swap_percent=swap.percent,
            total_processes=total_count,
            running_processes=running_count,
            sleeping_processes=sleeping_count,
            stopped_processes=stopped_count,
            zombie_processes=zombie_count,
        )

        return processes, stats


def build_process_tree(processes: list[ProcessInfo]) -> list[TreeRow]:
    """Construct parent-child process hierarchy with tree branch connectors."""
    by_pid = {p.pid: p for p in processes}
    children: dict[int, list[ProcessInfo]] = {}
    for p in processes:
        children.setdefault(p.ppid, []).append(p)

    for group in children.values():
        group.sort(key=lambda item: (item.name.casefold(), item.pid))

    ordered: list[TreeRow] = []
    visited: set[int] = set()

    # Roots: PPID is not in visible processes, or PPID == PID, or PPID <= 0
    roots = [p for p in processes if p.ppid not in by_pid or p.ppid == p.pid or p.ppid <= 0]
    roots.sort(key=lambda item: (item.name.casefold(), item.pid))

    def traverse(proc: ProcessInfo, depth: int, is_last_stack: list[bool]) -> None:
        if proc.pid in visited:
            return
        visited.add(proc.pid)

        if depth == 0:
            prefix = ""
        else:
            parts: list[str] = []
            for is_last in is_last_stack[:-1]:
                parts.append("    " if is_last else "│   ")
            parts.append("└── " if is_last_stack[-1] else "├── ")
            prefix = "".join(parts)

        is_last_node = is_last_stack[-1] if is_last_stack else True
        ordered.append(TreeRow(process=proc, depth=depth, prefix=prefix, is_last=is_last_node))

        proc_children = children.get(proc.pid, [])
        for i, child in enumerate(proc_children):
            traverse(child, depth + 1, is_last_stack + [i == len(proc_children) - 1])

    for i, root in enumerate(roots):
        traverse(root, 0, [i == len(roots) - 1])

    # Add any disconnected/unvisited processes
    for proc in sorted(processes, key=lambda item: (item.name.casefold(), item.pid)):
        if proc.pid not in visited:
            traverse(proc, 0, [True])

    return ordered


def control_terminate(pid: int) -> tuple[bool, str]:
    """Send SIGTERM to safely request process termination."""
    try:
        proc = psutil.Process(pid)
        proc.terminate()
        return True, f"Terminate signal (SIGTERM) sent to PID {pid} ({proc.name()})."
    except psutil.NoSuchProcess:
        return False, f"PID {pid} no longer exists."
    except psutil.AccessDenied:
        return False, f"Permission denied for PID {pid}. (Root or sudo privileges required)."
    except Exception as exc:
        return False, f"Failed to terminate PID {pid}: {exc}"


def control_kill(pid: int) -> tuple[bool, str]:
    """Send SIGKILL to unconditionally terminate process immediately."""
    try:
        proc = psutil.Process(pid)
        proc.kill()
        return True, f"Force kill signal (SIGKILL) sent to PID {pid} ({proc.name()})."
    except psutil.NoSuchProcess:
        return False, f"PID {pid} no longer exists."
    except psutil.AccessDenied:
        return False, f"Permission denied to kill PID {pid}. (Root or sudo privileges required)."
    except Exception as exc:
        return False, f"Failed to kill PID {pid}: {exc}"


def control_suspend(pid: int) -> tuple[bool, str]:
    """Send SIGSTOP to suspend/pause process execution."""
    try:
        proc = psutil.Process(pid)
        proc.suspend()
        return True, f"Suspend signal (SIGSTOP) sent to PID {pid} ({proc.name()})."
    except psutil.NoSuchProcess:
        return False, f"PID {pid} no longer exists."
    except psutil.AccessDenied:
        return False, f"Permission denied to suspend PID {pid}."
    except Exception as exc:
        return False, f"Failed to suspend PID {pid}: {exc}"


def control_resume(pid: int) -> tuple[bool, str]:
    """Send SIGCONT to resume suspended process."""
    try:
        proc = psutil.Process(pid)
        proc.resume()
        return True, f"Resume signal (SIGCONT) sent to PID {pid} ({proc.name()})."
    except psutil.NoSuchProcess:
        return False, f"PID {pid} no longer exists."
    except psutil.AccessDenied:
        return False, f"Permission denied to resume PID {pid}."
    except Exception as exc:
        return False, f"Failed to resume PID {pid}: {exc}"


def control_renice(pid: int, new_nice: int) -> tuple[bool, str]:
    """Adjust process priority (nice value from -20 to 19 on Linux)."""
    try:
        proc = psutil.Process(pid)
        proc.nice(new_nice)
        return True, f"Priority for PID {pid} set to nice value {new_nice}."
    except psutil.NoSuchProcess:
        return False, f"PID {pid} no longer exists."
    except psutil.AccessDenied:
        return False, (
            f"Permission denied to renice PID {pid}. "
            "Negative nice values (higher priority) require root/sudo privileges."
        )
    except Exception as exc:
        return False, f"Failed to change nice value for PID {pid}: {exc}"


def get_process_details(pid: int) -> dict[str, str]:
    """Retrieve in-depth information about a specific process."""
    try:
        proc = psutil.Process(pid)
        with proc.oneshot():
            name = proc.name()
            ppid = proc.ppid()
            status = proc.status()
            username = proc.username()
            try:
                exe = proc.exe() or "N/A"
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                exe = "Access Denied"
            try:
                cmdline = " ".join(proc.cmdline()) or name
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                cmdline = "Access Denied"
            try:
                cwd = proc.cwd() or "N/A"
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                cwd = "Access Denied"
            try:
                num_threads = proc.num_threads()
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                num_threads = "N/A"
            try:
                nice = proc.nice()
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                nice = "N/A"
            try:
                cpu_times = proc.cpu_times()
                cpu_time_str = f"user={cpu_times.user:.2f}s, sys={cpu_times.system:.2f}s"
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                cpu_time_str = "N/A"
            try:
                mem_info = proc.memory_info()
                rss_mb = mem_info.rss / (1024 * 1024)
                vms_mb = mem_info.vms / (1024 * 1024)
                mem_str = f"RSS: {rss_mb:.1f} MB, VMS: {vms_mb:.1f} MB"
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                mem_str = "N/A"
            try:
                created = datetime.datetime.fromtimestamp(proc.create_time()).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                created = "N/A"

            return {
                "PID": str(pid),
                "PPID": str(ppid),
                "Name": name,
                "Status": status,
                "User": username,
                "Priority (Nice)": str(nice),
                "Threads": str(num_threads),
                "CPU Time": cpu_time_str,
                "Memory": mem_str,
                "Start Time": created,
                "Executable": exe,
                "Working Dir": cwd,
                "Command Line": cmdline,
            }
    except psutil.NoSuchProcess:
        return {"Error": f"Process {pid} no longer exists."}
    except Exception as exc:
        return {"Error": f"Could not query process {pid}: {exc}"}

