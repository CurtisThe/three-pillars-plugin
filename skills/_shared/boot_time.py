"""Boot-time helper: did a file predate the last machine boot?"""
import os


def boot_epoch(proc_stat="/proc/stat"):
    """Return the integer btime from proc_stat, or None if unavailable."""
    try:
        with open(proc_stat) as fh:
            for line in fh:
                parts = line.split()
                if len(parts) >= 2 and parts[0] == "btime":
                    return int(parts[1])
    except (OSError, ValueError):
        return None
    return None


def predates_boot(path, boot=None):
    """True only when path exists and its mtime is strictly before boot."""
    if boot is None:
        boot = boot_epoch()
    if boot is None:
        return False
    try:
        return os.stat(path).st_mtime < boot
    except (OSError, ValueError):
        return False
