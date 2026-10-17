"""
AIPFO — Shared Utilities
Small, reusable helpers consumed by every other module.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
from config import SIZE_UNITS


# ─── Formatting ─────────────────────────────────────────────

def human_size(size_bytes: int) -> str:
    """Convert a byte count to a human-readable string (e.g. '4.2 MB')."""
    if size_bytes == 0:
        return "0 B"
    unit_index = 0
    size = float(size_bytes)
    while size >= 1024 and unit_index < len(SIZE_UNITS) - 1:
        size /= 1024
        unit_index += 1
    return f"{size:.1f} {SIZE_UNITS[unit_index]}" if unit_index else f"{int(size)} B"


def plural(count: int, word: str) -> str:
    """Return '1 file' or '3 files'."""
    return f"{count} {word}{'s' if count != 1 else ''}"


def format_timestamp(ts: float) -> str:
    """Convert an os.stat mtime float to a readable date string."""
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


# ─── Terminal colours (best-effort, no dependency) ──────────

class _Colors:
    """ANSI escape codes — gracefully degrades on terminals that don't
    support them (e.g. older Windows cmd without VT processing)."""

    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    RED    = "\033[91m"
    GREEN  = "\033[92m"
    YELLOW = "\033[93m"
    CYAN   = "\033[96m"
    MAGENTA = "\033[95m"
    DIM    = "\033[2m"

    def __init__(self) -> None:
        if not _supports_ansi():
            for attr in list(vars(self)):
                if not attr.startswith("_"):
                    setattr(self, attr, "")


def _supports_ansi() -> bool:
    """Return True when the terminal likely supports ANSI colours."""
    if os.getenv("NO_COLOR"):
        return False
    if sys.platform == "win32":
        return os.getenv("TERM") == "xterm" or os.getenv("WT_SESSION") is not None
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


C = _Colors()


def info(msg: str) -> None:
    print(f"{C.CYAN}ℹ {msg}{C.RESET}")

def success(msg: str) -> None:
    print(f"{C.GREEN}✔ {msg}{C.RESET}")

def warn(msg: str) -> None:
    print(f"{C.YELLOW}⚠ {msg}{C.RESET}")

def error(msg: str) -> None:
    print(f"{C.RED}✖ {msg}{C.RESET}")

def header(msg: str) -> None:
    print(f"\n{C.BOLD}{C.CYAN}{'═' * 60}{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}  {msg}{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}{'═' * 60}{C.RESET}\n")

def subheader(msg: str) -> None:
    print(f"\n{C.BOLD}{C.MAGENTA}── {msg} ──{C.RESET}\n")
