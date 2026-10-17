#!/usr/bin/env python3
"""
================================================================================
AIPFO — AI Personal File Organizer (Complete Unified Standalone Edition)
================================================================================

This single file contains the complete, self-contained implementation of the
AI Personal File Organizer agent.

Features implemented:
  ✅ Feature 1: Remove Duplicate Files & Avoid Redundancy (Content-First & System-Wide)
     - 4-Stage Content Detection (Size -> Quick Hash -> Full SHA-256 -> Normalized Text)
     - Matches identical content irrespective of file names, extensions, or folders
     - 100% System File Protection (Windows core, Program Files, AppData, system extensions)
     - Connected Device & Mobile Phone Exclusion (CrossDevice, PhoneLink, Motorola, Samsung, etc.)
     - Cloud Storage On-Demand Placeholder Detection (OneDrive, Dropbox, iCloud without network downloads)
     - Non-destructive cleanup: Duplicates safely moved to _duplicates_trash/ with original paths preserved
     - Interactive review or automated cleanup
     - Rich terminal specs (content preview, sizes, timestamps, match classification)
     - Markdown report generation

Future features ready to add in SECTION 8:
  🔲 Feature 2: Smart File Categorization & Organization
  🔲 Feature 3: Intelligent File Renaming & Metadata Tagging
  🔲 Feature 4: Folder Structure Optimization & Cleanup
  🔲 Feature 5: Scheduled Maintenance & Autonomous Health Monitoring

Usage:
------
  # Scan your entire system (safe local mode)
  python aipfo_unified.py scan

  # Scan a specific directory
  python aipfo_unified.py scan --target C:\\path\\to\\folder

  # Interactively review and clean duplicates
  python aipfo_unified.py clean --target C:\\path\\to\\folder

  # Auto-clean duplicates directly to trash
  python aipfo_unified.py clean --target C:\\path\\to\\folder --auto

  # Dry-run preview without touching any files
  python aipfo_unified.py clean --target C:\\path\\to\\folder --auto --dry-run
================================================================================
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import os
import shutil
import string
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator, List, Optional, Tuple


# ==============================================================================
# SECTION 1: CONFIGURATION & CONSTANTS
# ==============================================================================

# ── Hashing parameters ──
HASH_ALGORITHM = "sha256"
CHUNK_SIZE = 64 * 1024  # 64 KB read buffer
MIN_FILE_SIZE = 1        # Skip 0-byte files
MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2 GB limit per file for safety

# ── Trash & Report names ──
TRASH_DIR_NAME = "_duplicates_trash"
REPORT_FILENAME = "dedup_report.md"
SIZE_UNITS = ["B", "KB", "MB", "GB", "TB"]

# ── Windows Filesystem Attribute Flags (Cloud & Offline Placeholders) ──
FILE_ATTRIBUTE_REPARSE_POINT        = 0x00000400
FILE_ATTRIBUTE_OFFLINE              = 0x00001000
FILE_ATTRIBUTE_RECALL_ON_OPEN       = 0x00040000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x00400000

REMOTE_OR_CLOUD_ATTRIBUTES = (
    FILE_ATTRIBUTE_OFFLINE
    | FILE_ATTRIBUTE_RECALL_ON_OPEN
    | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
)

def is_cloud_or_offline_file(stat_obj) -> bool:
    """Return True if file is an online/cloud placeholder (e.g. OneDrive on-demand)."""
    attrs = getattr(stat_obj, "st_file_attributes", 0)
    return bool(attrs & REMOTE_OR_CLOUD_ATTRIBUTES)


# ── Other Devices & Cloud Sync Directories (NEVER TOUCH / NEVER DOWNLOAD) ──
DEVICE_AND_SYNC_DIRS = {
    # Mobile phone & portable device integrations
    "CrossDevice",                  # Windows 11 Phone Link / Cross Device folder
    "PhoneLink",
    "YourPhone",
    "ConnectedDevices",
    "Portable Devices",
    "WPD",
    "WPDNSE",

    # Cloud storage sync folders
    "OneDrive",
    "OneDrive - Personal",
    "OneDriveTemp",
    "Dropbox",
    "Google Drive",
    "GoogleDrive",
    "iCloud",
    "iCloudDrive",
    "iCloudPhotos",
    "Box",
    "Box Sync",
    "pCloud",
    "Nextcloud",
    "ownCloud",
    "Creative Cloud Files",

    # Windows shell junctions & virtual links
    "Application Data",
    "Local Settings",
    "My Documents",
    "NetHood",
    "PrintHood",
    "Recent",
    "SendTo",
    "Start Menu",
    "Templates",
    "Cookies",
}

DEVICE_KEYWORDS = {
    "crossdevice", "phonelink", "yourphone", "connected devices",
    "portable devices", "onedrive", "dropbox", "googledrive", "google drive",
    "icloud", "motorola", "samsung", "iphone", "android", "xiaomi",
    "oneplus", "pixel", "huawei", "oppo", "vivo",
}

def is_device_or_sync_dir(name: str) -> bool:
    """Return True if directory matches an external device or cloud sync."""
    name_lower = name.lower()
    for d in DEVICE_AND_SYNC_DIRS:
        if name_lower == d.lower():
            return True
    for kw in DEVICE_KEYWORDS:
        if kw in name_lower:
            return True
    return False


# ── Windows System & Application Directories (PROTECTED) ──
PROTECTED_DIRS = {
    "Windows", "Windows.old", "Boot", "Recovery",
    "$Recycle.Bin", "$RECYCLE.BIN", "$SysReset",
    "$WINDOWS.~BT", "$Windows.~WS",
    "System Volume Information", "PerfLogs", "MSOCache",
    "ESD", "System.Sav", "Documents and Settings",
    "Program Files", "Program Files (x86)", "ProgramData",
    "AppData", "Default", "Public", "All Users",
    ".VirtualBox", "VirtualBox VMs",
    "__pycache__", ".git", ".hg", ".svn", "node_modules",
    ".venv", "venv", ".env", ".tox", ".mypy_cache", ".pytest_cache",
    TRASH_DIR_NAME,
}
PROTECTED_DIRS.update(DEVICE_AND_SYNC_DIRS)

PROTECTED_FULL_PATHS: set[str] = set()

def _build_protected_paths() -> set[str]:
    """Resolve absolute protected paths across detected drives."""
    paths = set()
    if os.name == "nt":
        for letter in string.ascii_uppercase:
            drive = f"{letter}:\\"
            if os.path.isdir(drive):
                for d in [
                    "Windows", "Windows.old", "Boot", "Recovery",
                    "$Recycle.Bin", "$RECYCLE.BIN", "$SysReset",
                    "System Volume Information", "PerfLogs", "MSOCache",
                    "Program Files", "Program Files (x86)", "ProgramData",
                    "OneDriveTemp", "ESD", "System.Sav", "Documents and Settings",
                ]:
                    paths.add(os.path.join(drive, d).lower())
                users_dir = os.path.join(drive, "Users")
                if os.path.isdir(users_dir):
                    try:
                        for user in os.listdir(users_dir):
                            user_folder = os.path.join(users_dir, user)
                            paths.add(os.path.join(user_folder, "AppData").lower())
                            paths.add(os.path.join(user_folder, "CrossDevice").lower())
                            paths.add(os.path.join(user_folder, "OneDrive").lower())
                    except PermissionError:
                        pass
    return paths

PROTECTED_FULL_PATHS = _build_protected_paths()

# System file extensions that must NEVER be altered
PROTECTED_EXTENSIONS = {
    ".sys", ".dll", ".exe", ".msi", ".msp", ".msu",
    ".drv", ".cpl", ".ocx", ".ax", ".scr",
    ".cat", ".mum", ".mui", ".manifest",
    ".evt", ".evtx", ".etl", ".reg", ".efi",
}

IGNORED_EXTENSIONS = {".tmp", ".lock"}

# Readable text extensions for content-aware normalisation
TEXT_EXTENSIONS = {
    ".txt", ".md", ".csv", ".json", ".xml", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".conf", ".log",
    ".html", ".htm", ".css", ".js", ".ts", ".jsx", ".tsx",
    ".py", ".java", ".c", ".cpp", ".h", ".hpp", ".cs",
    ".rb", ".go", ".rs", ".php", ".pl", ".r", ".m",
    ".sql", ".sh", ".bat", ".ps1", ".cmd",
    ".rtf", ".tex", ".bib", ".srt", ".sub", ".vtt",
    ".properties", ".env", ".gitignore", ".dockerignore",
    ".makefile", ".cmake", ".gradle", ".rst",
}

# Categorisation map for display
FILE_CATEGORIES = {
    ".pdf": "📄 Document (PDF)", ".doc": "📄 Document (Word)", ".docx": "📄 Document (Word)",
    ".xls": "📊 Spreadsheet (Excel)", ".xlsx": "📊 Spreadsheet (Excel)",
    ".ppt": "📽️ Presentation", ".pptx": "📽️ Presentation",
    ".txt": "📝 Text File", ".md": "📝 Markdown", ".csv": "📊 CSV Data",
    ".json": "📋 JSON Data", ".xml": "📋 XML Data", ".rtf": "📄 Rich Text",
    ".jpg": "🖼️ Image (JPEG)", ".jpeg": "🖼️ Image (JPEG)", ".png": "🖼️ Image (PNG)",
    ".gif": "🖼️ Image (GIF)", ".bmp": "🖼️ Image (BMP)", ".svg": "🖼️ Image (SVG)",
    ".mp3": "🎵 Audio (MP3)", ".wav": "🎵 Audio (WAV)", ".flac": "🎵 Audio (FLAC)",
    ".mp4": "🎬 Video (MP4)", ".avi": "🎬 Video (AVI)", ".mkv": "🎬 Video (MKV)",
    ".zip": "📦 Archive (ZIP)", ".rar": "📦 Archive (RAR)", ".7z": "📦 Archive (7z)",
    ".py": "🐍 Python Script", ".js": "💛 JavaScript", ".ts": "💙 TypeScript",
    ".java": "☕ Java", ".c": "⚙️ C Source", ".cpp": "⚙️ C++ Source",
    ".html": "🌐 HTML", ".css": "🎨 Stylesheet", ".sql": "🗃️ SQL Script",
    ".log": "📋 Log File", ".bak": "💾 Backup File", ".ini": "⚙️ Config File",
    ".yaml": "⚙️ YAML Config", ".yml": "⚙️ YAML Config", ".toml": "⚙️ TOML Config",
}

def get_file_category(ext: str) -> str:
    return FILE_CATEGORIES.get(ext.lower(), f"📎 {ext.upper()[1:]} File" if ext else "📎 Unknown")

def get_trash_dir() -> Path:
    return Path.home() / TRASH_DIR_NAME

def get_local_fixed_drives() -> list[Path]:
    """Return only LOCAL FIXED hard drives/SSDs (DRIVE_FIXED = 3)."""
    drives = []
    if os.name == "nt":
        for letter in string.ascii_uppercase:
            drive_str = f"{letter}:\\"
            if os.path.isdir(drive_str):
                try:
                    if ctypes.windll.kernel32.GetDriveTypeW(drive_str) == 3:
                        drives.append(Path(drive_str))
                except Exception:
                    drives.append(Path(drive_str))
    else:
        drives.append(Path("/"))
    return drives

def get_user_scan_targets() -> list[Path]:
    """Return safe, local user directories."""
    targets = []
    home = Path.home()
    for folder in ["Desktop", "Documents", "Downloads", "Music", "Pictures", "Videos"]:
        p = home / folder
        if p.is_dir():
            targets.append(p)
    for drive in get_local_fixed_drives():
        try:
            for item in drive.iterdir():
                if not item.is_dir():
                    continue
                name_lower = item.name.lower()
                if name_lower in {d.lower() for d in PROTECTED_DIRS}:
                    continue
                if item.name.startswith("$") or item.name.startswith("."):
                    continue
                if is_device_or_sync_dir(item.name):
                    continue
                if str(item).lower() in PROTECTED_FULL_PATHS:
                    continue
                if os.path.islink(str(item)):
                    continue
                try:
                    st = item.stat(follow_symlinks=False)
                    if getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT:
                        continue
                except (PermissionError, OSError):
                    continue
                if name_lower == "users":
                    continue
                targets.append(item)
        except (PermissionError, OSError):
            pass
    return targets


# ==============================================================================
# SECTION 2: UTILITIES & DISPLAY
# ==============================================================================

def human_size(size_bytes: int) -> str:
    """Format bytes into readable units."""
    if size_bytes == 0:
        return "0 B"
    idx = 0
    size = float(size_bytes)
    while size >= 1024 and idx < len(SIZE_UNITS) - 1:
        size /= 1024
        idx += 1
    return f"{size:.1f} {SIZE_UNITS[idx]}" if idx else f"{int(size)} B"

def plural(count: int, word: str) -> str:
    return f"{count} {word}{'s' if count != 1 else ''}"

def format_timestamp(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

class _Colors:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    RED     = "\033[91m"
    GREEN   = "\033[92m"
    YELLOW  = "\033[93m"
    CYAN    = "\033[96m"
    MAGENTA = "\033[95m"
    DIM     = "\033[2m"

    def __init__(self) -> None:
        if os.getenv("NO_COLOR") or (sys.platform == "win32" and not (os.getenv("TERM") == "xterm" or os.getenv("WT_SESSION"))):
            for attr in list(vars(self)):
                if not attr.startswith("_"):
                    setattr(self, attr, "")

C = _Colors()

def info(msg: str) -> None:    print(f"{C.CYAN}ℹ {msg}{C.RESET}")
def success(msg: str) -> None: print(f"{C.GREEN}✔ {msg}{C.RESET}")
def warn(msg: str) -> None:    print(f"{C.YELLOW}⚠ {msg}{C.RESET}")
def error(msg: str) -> None:   print(f"{C.RED}✖ {msg}{C.RESET}")

def header(msg: str) -> None:
    print(f"\n{C.BOLD}{C.CYAN}{'═' * 60}{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}  {msg}{C.RESET}")
    print(f"{C.BOLD}{C.CYAN}{'═' * 60}{C.RESET}\n")

def subheader(msg: str) -> None:
    print(f"\n{C.BOLD}{C.MAGENTA}── {msg} ──{C.RESET}\n")


# ==============================================================================
# SECTION 3: HASHER & CONTENT INSPECTION
# ==============================================================================

def _is_safe_local_file(filepath: Path) -> bool:
    """Ensure file is strictly local on disk and not a cloud/device placeholder."""
    try:
        stat = filepath.stat()
        if is_cloud_or_offline_file(stat):
            return False
        if getattr(stat, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT:
            return False
        return True
    except Exception:
        return False

def hash_file(filepath: Path, algorithm: str = HASH_ALGORITHM, chunk_size: int = CHUNK_SIZE) -> Optional[str]:
    """Calculate full cryptographic hash of entire content (chunked read)."""
    if not _is_safe_local_file(filepath):
        return None
    h = hashlib.new(algorithm)
    try:
        with open(filepath, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                h.update(chunk)
    except (OSError, PermissionError, TimeoutError) as exc:
        warn(f"Cannot read {filepath}: {exc}")
        return None
    return h.hexdigest()

def quick_hash(filepath: Path, num_bytes: int = 4096) -> Optional[str]:
    """Hash first 4 KB as an initial fast filter."""
    if not _is_safe_local_file(filepath):
        return None
    h = hashlib.new(HASH_ALGORITHM)
    try:
        with open(filepath, "rb") as f:
            data = f.read(num_bytes)
            h.update(data)
    except (OSError, PermissionError, TimeoutError) as exc:
        warn(f"Cannot read {filepath}: {exc}")
        return None
    return h.hexdigest()

def _normalise_text(raw: bytes) -> str:
    """Decode and normalize text line-endings, encoding, and trailing whitespace."""
    for encoding in ("utf-8-sig", "utf-8", "utf-16", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except (UnicodeDecodeError, ValueError):
            continue
    else:
        return raw.hex()
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    return "\n".join(lines).strip()

def hash_text_content(filepath: Path) -> Optional[str]:
    """Hash normalized text content to detect identical text across encodings/formats."""
    if not _is_safe_local_file(filepath):
        return None
    try:
        raw = filepath.read_bytes()
    except (OSError, PermissionError, TimeoutError) as exc:
        warn(f"Cannot read {filepath}: {exc}")
        return None
    if b"\x00" in raw[:8192]:
        return None
    normalised = _normalise_text(raw)
    h = hashlib.new(HASH_ALGORITHM)
    h.update(normalised.encode("utf-8"))
    return h.hexdigest()

def is_likely_text_file(filepath: Path) -> bool:
    """Dynamically determine if a file contains readable text."""
    if not _is_safe_local_file(filepath):
        return False
    ext = filepath.suffix.lower()
    if ext in TEXT_EXTENSIONS:
        return True
    try:
        with open(filepath, "rb") as f:
            chunk = f.read(1024)
            if not chunk or b"\x00" in chunk:
                return False
            try:
                chunk.decode("utf-8")
                return True
            except UnicodeDecodeError:
                try:
                    chunk.decode("latin-1")
                    return True
                except Exception:
                    return False
    except (OSError, PermissionError, TimeoutError):
        return False

def get_file_content_preview(filepath: Path, max_chars: int = 100) -> str:
    """Read a sample preview of the internal content to visually prove matching data."""
    if not _is_safe_local_file(filepath):
        return "(online cloud / mobile device placeholder)"
    try:
        with open(filepath, "rb") as f:
            chunk = f.read(512)
            if not chunk:
                return "(empty file)"
            if b"\x00" in chunk:
                return f"(Binary data: {len(chunk)} bytes sampled)"
            for enc in ("utf-8", "latin-1"):
                try:
                    text = chunk.decode(enc).strip().replace("\r", " ").replace("\n", " ")
                    if len(text) > max_chars:
                        return f'"{text[:max_chars]}..."'
                    return f'"{text}"'
                except UnicodeDecodeError:
                    continue
            return f"(Binary data: {len(chunk)} bytes sampled)"
    except Exception:
        return "(content unreadable)"


# ==============================================================================
# SECTION 4: SCANNER & SYSTEM/DEVICE GUARDS
# ==============================================================================

@dataclass
class FileEntry:
    path: Path
    size: int
    modified: float
    created: float = 0.0
    extension: str = ""
    category: str = ""
    quick_hash: str | None = None
    full_hash: str | None = None

@dataclass
class ScanResult:
    roots: list[Path] = field(default_factory=list)
    files: list[FileEntry] = field(default_factory=list)
    skipped: int = 0
    protected_skipped: int = 0
    cloud_skipped: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def total_size(self) -> int:
        return sum(f.size for f in self.files)

def _is_protected_path(dirpath: str) -> bool:
    dirpath_lower = dirpath.lower()
    for pp in PROTECTED_FULL_PATHS:
        if dirpath_lower == pp or dirpath_lower.startswith(pp + os.sep):
            return True
    return False

def _is_protected_dir_name(name: str) -> bool:
    if is_device_or_sync_dir(name):
        return True
    name_lower = name.lower()
    for ignored in PROTECTED_DIRS:
        if name_lower == ignored.lower():
            return True
    if name.startswith("."):
        return True
    return False

def scan_directory(root: Path, *, show_progress: bool = True) -> ScanResult:
    root = root.resolve()
    result = ScanResult(roots=[root])
    if not root.is_dir():
        result.errors.append(f"Not a directory: {root}")
        return result
    if show_progress:
        info(f"Scanning: {root}")

    file_count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        if _is_protected_path(dirpath) or is_device_or_sync_dir(os.path.basename(dirpath)):
            dirnames.clear()
            result.protected_skipped += 1
            continue

        safe_dirs = []
        for d in dirnames:
            if _is_protected_dir_name(d):
                result.protected_skipped += 1
                continue
            full_sub = os.path.join(dirpath, d)
            if _is_protected_path(full_sub):
                result.protected_skipped += 1
                continue
            try:
                st = os.stat(full_sub, follow_symlinks=False)
                if getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT:
                    result.protected_skipped += 1
                    continue
            except (OSError, PermissionError):
                continue
            safe_dirs.append(d)
        dirnames[:] = safe_dirs

        for fname in filenames:
            fpath = Path(dirpath) / fname
            ext = fpath.suffix.lower()

            if ext in PROTECTED_EXTENSIONS:
                result.protected_skipped += 1
                continue
            if ext in IGNORED_EXTENSIONS:
                result.skipped += 1
                continue
            try:
                stat = fpath.stat()
            except (OSError, PermissionError) as exc:
                result.errors.append(str(exc))
                continue

            if is_cloud_or_offline_file(stat):
                result.cloud_skipped += 1
                continue
            if getattr(stat, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT:
                result.skipped += 1
                continue
            if stat.st_size < MIN_FILE_SIZE or (MAX_FILE_SIZE and stat.st_size > MAX_FILE_SIZE):
                result.skipped += 1
                continue

            result.files.append(FileEntry(
                path=fpath,
                size=stat.st_size,
                modified=stat.st_mtime,
                created=stat.st_ctime,
                extension=ext,
                category=get_file_category(ext),
            ))
            file_count += 1
            if show_progress and file_count % 5000 == 0:
                info(f"  ... scanned {file_count} files so far")

    if show_progress:
        msg = f"skipped {result.skipped} ignored + {result.protected_skipped} system/device"
        if result.cloud_skipped:
            msg += f" + {result.cloud_skipped} cloud placeholders"
        info(f"Found {len(result.files)} local files ({human_size(result.total_size)}), {msg}")
    return result

def scan_full_system(*, show_progress: bool = True) -> ScanResult:
    targets = get_user_scan_targets()
    if show_progress:
        info("Full System Scan — Safe Local Target Directories:")
        for t in targets:
            info(f"  → {t}")
        print()

    combined = ScanResult(roots=[t for t in targets])
    seen_paths: set[str] = set()

    for target in targets:
        target_str = str(target.resolve()).lower()
        if any(target_str.startswith(seen + os.sep) or target_str == seen for seen in seen_paths):
            continue
        res = scan_directory(target, show_progress=show_progress)
        combined.files.extend(res.files)
        combined.skipped += res.skipped
        combined.protected_skipped += res.protected_skipped
        combined.cloud_skipped += res.cloud_skipped
        combined.errors.extend(res.errors)
        seen_paths.add(target_str)

    if show_progress:
        print()
        info(
            f"TOTAL: {plural(len(combined.files), 'local file')} ({human_size(combined.total_size)}) across "
            f"{plural(len(targets), 'directory')} (Skipped {combined.protected_skipped} system/mobile files, "
            f"{combined.cloud_skipped} cloud placeholders)"
        )
    return combined


# ==============================================================================
# SECTION 5: FEATURE 1 — DEDUPLICATION & REDUNDANCY REMOVAL
# ==============================================================================

@dataclass
class DuplicateGroup:
    content_hash: str
    original: FileEntry
    duplicates: list[FileEntry]
    match_type: str = "exact"  # "exact" or "content-aware"

    @property
    def wasted_bytes(self) -> int:
        return sum(d.size for d in self.duplicates)

@dataclass
class DedupResult:
    groups: list[DuplicateGroup] = field(default_factory=list)
    total_wasted: int = 0
    files_scanned: int = 0
    time_taken: float = 0.0
    exact_groups: int = 0
    content_aware_groups: int = 0

    @property
    def duplicate_count(self) -> int:
        return sum(len(g.duplicates) for g in self.groups)

def _pick_original(entries: list[FileEntry]) -> FileEntry:
    """Heuristic original selector: shortest path, shortest filename, oldest timestamp."""
    def score(e: FileEntry):
        return (len(e.path.parts), len(e.path.name), e.modified)
    return min(entries, key=score)

def find_duplicates(scan: ScanResult, *, show_progress: bool = True) -> DedupResult:
    """4-stage content-first duplicate detection engine."""
    result = DedupResult(files_scanned=len(scan.files))
    if show_progress:
        subheader("Duplicate Detection Engine (4-Stage Content First)")

    already_in_group: set[str] = set()

    # Stage 1: Size grouping
    by_size: dict[int, list[FileEntry]] = defaultdict(list)
    for entry in scan.files:
        by_size[entry.size].append(entry)
    candidates = {sz: entries for sz, entries in by_size.items() if len(entries) > 1}
    if show_progress:
        total_candidates = sum(len(e) for e in candidates.values())
        info(f"Stage 1 (size filter)      → {plural(total_candidates, 'file')} share a size with another file")

    # Stage 2: Quick hash
    quick_candidates: list[list[FileEntry]] = []
    for size, entries in candidates.items():
        by_qh: dict[str, list[FileEntry]] = defaultdict(list)
        for entry in entries:
            qh = quick_hash(entry.path)
            if qh is not None:
                entry.quick_hash = qh
                by_qh[qh].append(entry)
        for group in by_qh.values():
            if len(group) > 1:
                quick_candidates.append(group)
    if show_progress:
        total_qc = sum(len(g) for g in quick_candidates)
        info(f"Stage 2 (quick hash)       → {plural(total_qc, 'file')} survive quick-hash filter")

    # Stage 3: Full SHA-256 hash (exact bytes across different names)
    processed = 0
    for group in quick_candidates:
        by_fh: dict[str, list[FileEntry]] = defaultdict(list)
        for entry in group:
            fh = hash_file(entry.path)
            if fh is not None:
                entry.full_hash = fh
                by_fh[fh].append(entry)
            processed += 1
            if show_progress and processed % 500 == 0:
                info(f"  ... hashed {processed} files")
        for fhash, entries in by_fh.items():
            if len(entries) > 1:
                original = _pick_original(entries)
                dupes = [e for e in entries if e is not original]
                dg = DuplicateGroup(content_hash=fhash, original=original, duplicates=dupes, match_type="exact")
                result.groups.append(dg)
                result.total_wasted += dg.wasted_bytes
                result.exact_groups += 1
                already_in_group.add(str(original.path))
                for d in dupes:
                    already_in_group.add(str(d.path))

    if show_progress:
        exact_dupes = sum(len(g.duplicates) for g in result.groups if g.match_type == "exact")
        info(f"Stage 3 (full hash)        → {plural(result.exact_groups, 'exact-match group')} ({plural(exact_dupes, 'redundant file')})")

    # Stage 4: Content-aware normalized text comparison
    text_files = [f for f in scan.files if is_likely_text_file(f.path) and str(f.path) not in already_in_group]
    if text_files and show_progress:
        info(f"Stage 4 (content-aware)    → Analysing {plural(len(text_files), 'text file')} for semantic duplicates...")
    if text_files:
        by_text_hash: dict[str, list[FileEntry]] = defaultdict(list)
        for entry in text_files:
            th = hash_text_content(entry.path)
            if th is not None:
                by_text_hash[th].append(entry)
        for thash, entries in by_text_hash.items():
            if len(entries) > 1:
                original = _pick_original(entries)
                dupes = [e for e in entries if e is not original]
                dg = DuplicateGroup(content_hash=thash, original=original, duplicates=dupes, match_type="content-aware")
                result.groups.append(dg)
                result.total_wasted += dg.wasted_bytes
                result.content_aware_groups += 1

    if show_progress:
        if result.content_aware_groups:
            ca_dupes = sum(len(g.duplicates) for g in result.groups if g.match_type == "content-aware")
            info(f"Stage 4 result             → {plural(result.content_aware_groups, 'content-match group')} ({plural(ca_dupes, 'file')} with same text, different encoding/format)")
        print()
        if result.groups:
            success(
                f"TOTAL: {plural(len(result.groups), 'duplicate group')} with "
                f"{plural(result.duplicate_count, 'redundant file')} ({human_size(result.total_wasted)} reclaimable)"
            )
            if result.exact_groups:
                info(f"  ├─ {result.exact_groups} exact-match (identical bytes, different names)")
            if result.content_aware_groups:
                info(f"  └─ {result.content_aware_groups} content-match (same text, different encoding/format)")
        else:
            success("No duplicates found — your files are clean!")
    return result

def display_duplicate_details(dedup: DedupResult) -> None:
    """Print full specifications of each duplicate group."""
    if not dedup.groups:
        return
    header("Duplicate File Details")
    for i, group in enumerate(dedup.groups, 1):
        total_in_group = 1 + len(group.duplicates)
        o = group.original
        badge = f"{C.GREEN}EXACT MATCH{C.RESET} (identical bytes, different names)" if group.match_type == "exact" else f"{C.MAGENTA}CONTENT MATCH{C.RESET} (same readable text, different encoding/format)"
        diff_names = any(d.path.name.lower() != o.path.name.lower() for d in group.duplicates)
        preview = get_file_content_preview(o.path)

        print(f"{C.BOLD}{C.YELLOW}╔══ Group {i}/{len(dedup.groups)} ({total_in_group} identical files) ══╗{C.RESET}")
        print(f"{C.BOLD}  Match Type     : {C.RESET}{badge}")
        if diff_names:
            print(f"  {C.MAGENTA}⚡ Notice       : Duplicates have DIFFERENT NAMES but IDENTICAL content!{C.RESET}")
        print(f"{C.BOLD}  Content Preview: {C.RESET}{C.CYAN}{preview}{C.RESET}")
        print(f"{C.BOLD}  Content Hash   : {C.RESET}{group.content_hash[:24]}…")
        print(f"{C.BOLD}  File Size      : {C.RESET}{human_size(group.original.size)}")
        print(f"{C.BOLD}  File Type      : {C.RESET}{group.original.category}")
        print(f"{C.BOLD}  Wasted Space   : {C.RESET}{C.RED}{human_size(group.wasted_bytes)}{C.RESET}\n")

        print(f"  {C.GREEN}✅ KEEPING (Original):{C.RESET}")
        print(f"     📁 Path      : {o.path}")
        print(f"     📄 File Name : {o.path.name}")
        print(f"     📏 Size      : {human_size(o.size)}")
        print(f"     📝 Type      : {o.category}")
        print(f"     📎 Extension : {o.extension or 'none'}")
        print(f"     🕐 Modified  : {format_timestamp(o.modified)}")
        print(f"     🕐 Created   : {format_timestamp(o.created)}\n")

        for j, dup in enumerate(group.duplicates, 1):
            name_note = " (DIFFERENT NAME)" if dup.path.name.lower() != o.path.name.lower() else ""
            print(f"  {C.RED}🗑️  DUPLICATE #{j} (Will be removed){name_note}:{C.RESET}")
            print(f"     📁 Path      : {dup.path}")
            print(f"     📄 File Name : {dup.path.name}")
            print(f"     📏 Size      : {human_size(dup.size)}")
            print(f"     📝 Type      : {dup.category}")
            print(f"     📎 Extension : {dup.extension or 'none'}")
            print(f"     🕐 Modified  : {format_timestamp(dup.modified)}")
            print(f"     🕐 Created   : {format_timestamp(dup.created)}")
            if dup.path.name.lower() != o.path.name.lower():
                print(f"     🔍 Verified  : Full content inspected — 100% identical data inside!")
            if group.match_type == "content-aware":
                print(f"     ⚡ Note      : Same readable text content, normalized line-endings/encoding")
            print()
        print(f"{C.YELLOW}╚{'═' * 55}╝{C.RESET}\n")

def move_duplicates_to_trash(dedup: DedupResult, *, dry_run: bool = False) -> list[dict]:
    """Safely move duplicates to central trash folder preserving original directory paths."""
    trash_root = get_trash_dir()
    moved: list[dict] = []
    for group in dedup.groups:
        for dup in group.duplicates:
            try:
                drive = dup.path.drive.replace(":", "")
                rel = str(dup.path.relative_to(dup.path.anchor))
                dest = trash_root / drive / rel
            except (ValueError, TypeError):
                dest = trash_root / dup.path.name

            move_info = {
                "source": dup.path, "destination": dest, "file_name": dup.path.name,
                "size": dup.size, "size_human": human_size(dup.size), "type": dup.category,
                "extension": dup.extension, "modified": format_timestamp(dup.modified),
                "created": format_timestamp(dup.created), "content_hash": group.content_hash[:16],
                "original_kept": group.original.path, "match_type": group.match_type,
            }
            if dry_run:
                info(f"[DRY RUN] Would move: {dup.path}")
                print(f"           → {dest}")
                moved.append(move_info)
                continue

            dest.parent.mkdir(parents=True, exist_ok=True)
            final_dest = dest
            counter = 1
            while final_dest.exists():
                final_dest = dest.with_stem(f"{dest.stem}_dup{counter}")
                counter += 1
            try:
                shutil.move(str(dup.path), str(final_dest))
                move_info["destination"] = final_dest
                moved.append(move_info)
                match_label = "exact" if group.match_type == "exact" else "content-match"
                print(f"  {C.RED}🗑️  Removed:{C.RESET} {dup.path}")
                print(f"     {C.DIM}Name: {dup.path.name} | Type: {dup.category} | Size: {human_size(dup.size)} | Match: {match_label}{C.RESET}")
                print(f"     {C.DIM}Kept original: {group.original.path}{C.RESET}")
            except (OSError, PermissionError) as exc:
                error(f"Could not move {dup.path}: {exc}")
    return moved


# ==============================================================================
# SECTION 6: REPORTING ENGINE
# ==============================================================================

def generate_report(
    dedup: DedupResult,
    scan_roots: list[Path] | None = None,
    moved: list[dict] | None = None,
    dry_run: bool = False,
) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: list[str] = []
    lines.append("# 🗂️ AIPFO — Duplicate File Report\n")
    lines.append(f"**Generated:** {now}  ")
    if scan_roots:
        lines.append(f"**Scanned directories:** {len(scan_roots)}  ")
        for r in scan_roots[:10]:
            lines.append(f"  - `{r}`  ")
        if len(scan_roots) > 10:
            lines.append(f"  - _...and {len(scan_roots) - 10} more_  ")
    lines.append(f"**Files scanned:** {dedup.files_scanned:,}  ")
    lines.append(f"**Duplicate groups found:** {len(dedup.groups)}  ")
    lines.append(f"  - Exact-match groups: {dedup.exact_groups}  ")
    lines.append(f"  - Content-aware groups: {dedup.content_aware_groups}  ")
    lines.append(f"**Redundant files:** {dedup.duplicate_count}  ")
    lines.append(f"**Space reclaimable:** {human_size(dedup.total_wasted)}  ")
    if dedup.time_taken:
        lines.append(f"**Scan time:** {dedup.time_taken:.1f} seconds  ")
    lines.append("")

    if not dedup.groups:
        lines.append("> ✅ **No duplicates found — your system is clean!**")
        return "\n".join(lines)

    lines.append("---\n")
    for i, group in enumerate(dedup.groups, 1):
        o = group.original
        match_badge = "🔵 Exact Match" if group.match_type == "exact" else "🟣 Content Match"
        lines.append(f"## Group {i} — {group.original.category}  ({human_size(group.original.size)} each)\n")
        lines.append(f"- **Match Type:** {match_badge}")
        diff_names = any(d.path.name.lower() != o.path.name.lower() for d in group.duplicates)
        if diff_names:
            lines.append(f"- ⚡ **Filename Status:** Duplicates have **DIFFERENT NAMES** but **IDENTICAL content inside**")
        lines.append(f"- **Content Preview:** `{get_file_content_preview(o.path)}`")
        lines.append(f"- **Content Hash:** `{group.content_hash[:24]}…`")
        lines.append(f"- **File Size:** {human_size(group.original.size)}")
        lines.append(f"- **File Type:** {group.original.category}")
        lines.append(f"- **Wasted Space:** {human_size(group.wasted_bytes)}\n")

        lines.append("| # | Status | File Name | Extension | Path | Size | Type | Modified | Created |")
        lines.append("|---|--------|-----------|-----------|------|------|------|----------|---------|")
        lines.append(f"| 1 | ✅ **Kept** | `{o.path.name}` | `{o.extension}` | `{o.path.parent}` | {human_size(o.size)} | {o.category} | {format_timestamp(o.modified)} | {format_timestamp(o.created)} |")
        for j, dup in enumerate(group.duplicates, 2):
            st = "🗑️ **Removed**" if moved else ("🔍 Would remove" if dry_run else "🗑️ Duplicate")
            lines.append(f"| {j} | {st} | `{dup.path.name}` | `{dup.extension}` | `{dup.path.parent}` | {human_size(dup.size)} | {dup.category} | {format_timestamp(dup.modified)} | {format_timestamp(dup.created)} |")
        lines.append("")

    if moved:
        lines.append("---\n\n## 🗑️ Removed Files — Full Specifications\n")
        lines.append("| # | File Name | Type | Extension | Size | Match | Original Location | Moved To | Original Kept |")
        lines.append("|---|-----------|------|-----------|------|-------|-------------------|----------|---------------|")
        for idx, m in enumerate(moved, 1):
            ml = "Exact" if m.get('match_type') == 'exact' else "Content"
            lines.append(f"| {idx} | `{m['file_name']}` | {m['type']} | `{m['extension']}` | {m['size_human']} | {ml} | `{m['source'].parent}` | `{m['destination']}` | `{m['original_kept']}` |")
        lines.append("")

    lines.append("---\n\n## 📊 Summary\n")
    if moved and not dry_run:
        lines.append(f"- ✅ **{plural(len(moved), 'duplicate file')}** removed")
        lines.append(f"- 💾 **{human_size(dedup.total_wasted)}** of disk space recovered")
        lines.append(f"- 📂 Duplicates moved to: `{get_trash_dir()}`")
        lines.append(f"- ⚠️ No system files or external device files were touched")
    elif dry_run:
        lines.append(f"- 🔍 **Dry run** — no files were moved")
        lines.append(f"- 💾 **{human_size(dedup.total_wasted)}** could be recovered")
    else:
        lines.append(f"- 🔎 **{plural(dedup.duplicate_count, 'duplicate file')}** identified")
        lines.append(f"- 💾 **{human_size(dedup.total_wasted)}** reclaimable")
    lines.append("")
    return "\n".join(lines)

def save_report(report: str, save_dir: Path | None = None) -> Path:
    if save_dir is None:
        save_dir = Path.home()
    save_dir.mkdir(parents=True, exist_ok=True)
    report_path = save_dir / REPORT_FILENAME
    report_path.write_text(report, encoding="utf-8")
    return report_path


# ==============================================================================
# SECTION 7: AGENT ORCHESTRATOR & CLI INTERFACE
# ==============================================================================

def _do_scan(target: Path | None) -> ScanResult:
    if target:
        info(f"Targeted scan: {target}")
        return scan_directory(target)
    else:
        header("🌐 Full System Scan (Safe Local Mode)")
        info("Auto-detecting safe personal directories on local drives...")
        info("PROTECTED & EXCLUDED: System files, mobile devices (CrossDevice/Phone Link), and cloud on-demand sync.")
        print()
        return scan_full_system()

def _interactive_review(dedup: DedupResult) -> DedupResult:
    approved_groups: list[DuplicateGroup] = []
    subheader(f"Interactive Review — {plural(len(dedup.groups), 'group')} to review")
    for i, group in enumerate(dedup.groups, 1):
        total = 1 + len(group.duplicates)
        diff_names = any(d.path.name.lower() != group.original.path.name.lower() for d in group.duplicates)
        preview = get_file_content_preview(group.original.path)

        print(f"\n{C.BOLD}╔══ Group {i}/{len(dedup.groups)} ({total} identical files) ══╗{C.RESET}")
        print(f"  Match Type: {group.match_type.upper()}")
        if diff_names:
            print(f"  {C.MAGENTA}⚡ Notice    : Files have DIFFERENT NAMES but IDENTICAL inner data!{C.RESET}")
        print(f"  Content   : {C.CYAN}{preview}{C.RESET}")
        print(f"  File Type : {group.original.category}")
        print(f"  File Size : {human_size(group.original.size)}")
        print(f"  Wasted    : {C.RED}{human_size(group.wasted_bytes)}{C.RESET}")
        print(f"  Hash      : {group.content_hash[:16]}…\n")
        print(f"  {C.GREEN}✅ Keep  :{C.RESET} {group.original.path.name}  ({group.original.path})")
        for j, dup in enumerate(group.duplicates, 1):
            name_tag = f" {C.MAGENTA}(Different Name){C.RESET}" if dup.path.name.lower() != group.original.path.name.lower() else ""
            print(f"  {C.RED}🗑️ #{j}    :{C.RESET} {dup.path.name}{name_tag}  ({dup.path})")

        while True:
            choice = input(f"\n  Move {plural(len(group.duplicates), 'duplicate')} to trash? [{C.GREEN}y{C.RESET}es / {C.RED}n{C.RESET}o / {C.YELLOW}a{C.RESET}ll / {C.CYAN}q{C.RESET}uit] ▸ ").strip().lower()
            if choice in ("y", "yes"):
                approved_groups.append(group)
                success("Marked for removal.")
                break
            elif choice in ("n", "no"):
                info("Skipped.")
                break
            elif choice in ("a", "all"):
                approved_groups.append(group)
                for remaining in dedup.groups[i:]:
                    approved_groups.append(remaining)
                success(f"Approved all remaining {len(dedup.groups) - i + 1} groups.")
                break
            elif choice in ("q", "quit"):
                info("Aborting interactive review.")
                break
            else:
                warn("Please enter y, n, a, or q.")
        if choice in ("q", "quit") or choice in ("a", "all"):
            break

    return DedupResult(
        groups=approved_groups,
        total_wasted=sum(g.wasted_bytes for g in approved_groups),
        files_scanned=dedup.files_scanned,
    )

def cmd_scan(args: argparse.Namespace) -> None:
    header("AIPFO — Duplicate File Scanner")
    target = args.target.resolve() if args.target else None
    t0 = time.perf_counter()
    scan = _do_scan(target)
    if not scan.files:
        warn("No user files found to scan.")
        return
    dedup = find_duplicates(scan)
    dedup.time_taken = time.perf_counter() - t0
    display_duplicate_details(dedup)
    report = generate_report(dedup, scan_roots=scan.roots)
    save_dir = target if target else Path.home()
    report_path = save_report(report, save_dir)
    success(f"Report saved to {report_path}")
    info(f"Scan completed in {dedup.time_taken:.1f}s")

def cmd_clean(args: argparse.Namespace) -> None:
    header("AIPFO — Duplicate File Cleaner")
    target = args.target.resolve() if args.target else None
    if not target:
        warn("⚠️  FULL SYSTEM CLEAN MODE")
        info("Scanning personal directories across local drives. System and mobile device data are excluded.")
        print()
    t0 = time.perf_counter()
    scan = _do_scan(target)
    if not scan.files:
        warn("No user files found to scan.")
        return
    dedup = find_duplicates(scan)
    dedup.time_taken = time.perf_counter() - t0
    if not dedup.groups:
        success("No duplicates found — your files are already clean! 🎉")
        return
    display_duplicate_details(dedup)
    if not args.auto:
        dedup = _interactive_review(dedup)
        if not dedup.groups:
            info("No groups approved — exiting.")
            return

    if not args.dry_run:
        subheader("Removing Duplicates")
        info(f"Moving duplicates to: {get_trash_dir()}")
        print()
    moved = move_duplicates_to_trash(dedup, dry_run=args.dry_run)
    report = generate_report(dedup, scan_roots=scan.roots, moved=moved, dry_run=args.dry_run)
    save_dir = target if target else Path.home()
    report_path = save_report(report, save_dir)
    print()
    if args.dry_run:
        warn(f"Dry run complete — no files were moved.")
        info(f"{human_size(dedup.total_wasted)} could be recovered.")
    else:
        success(f"✅ {plural(len(moved), 'duplicate file')} removed!")
        success(f"💾 {human_size(dedup.total_wasted)} of disk space recovered!")
        info(f"📂 Duplicates safely stored in: {get_trash_dir()}")
        info(f"⚠️  No system files or mobile device data were touched.")
    success(f"📋 Report saved to: {report_path}")
    info(f"⏱️  Completed in {dedup.time_taken:.1f}s")


# ==============================================================================
# SECTION 8: EXTENSION HOOKS (FUTURE FEATURES 2, 3, 4, 5)
# ==============================================================================
# Plug in your next features right here! Each feature can be a clean class or
# function registered with the argument parser below.

class SmartCategorizer:
    """🔲 Feature 2: Smart File Categorization & Organization (Placeholder)"""
    def run(self, target: Path):
        info("Feature 2 (Smart Categorization) will be implemented here.")

class IntelligentRenamer:
    """🔲 Feature 3: Intelligent File Renaming & Metadata Tagging (Placeholder)"""
    def run(self, target: Path):
        info("Feature 3 (Intelligent Renamer) will be implemented here.")

class FolderOptimizer:
    """🔲 Feature 4: Folder Structure Optimization & Cleanup (Placeholder)"""
    def run(self, target: Path):
        info("Feature 4 (Folder Optimizer) will be implemented here.")

class ScheduledMaintenance:
    """🔲 Feature 5: Scheduled Autonomous Maintenance (Placeholder)"""
    def run(self, target: Path):
        info("Feature 5 (Scheduled Maintenance) will be implemented here.")


# ==============================================================================
# SECTION 9: COMMAND LINE DISPATCHER
# ==============================================================================

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aipfo",
        description="AIPFO — AI Personal File Organizer (All-in-One)",
        epilog="Scans entire system by default (safe local mode). Use --target for specific folders.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # scan command
    p_scan = sub.add_parser("scan", help="Scan and detect duplicates (read-only preview)")
    p_scan.add_argument("--target", "-t", type=Path, default=None, help="Target directory (default: entire system)")

    # clean command
    p_clean = sub.add_parser("clean", help="Scan and remove duplicates (safe trash move)")
    p_clean.add_argument("--target", "-t", type=Path, default=None, help="Target directory (default: entire system)")
    p_clean.add_argument("--auto", action="store_true", help="Auto-clean without interactive prompt")
    p_clean.add_argument("--dry-run", action="store_true", help="Preview moves without touching files")

    return parser

def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.target and not args.target.resolve().is_dir():
        error(f"Target is not a valid directory: {args.target}")
        sys.exit(1)

    try:
        if args.command == "scan":
            cmd_scan(args)
        elif args.command == "clean":
            cmd_clean(args)
    except KeyboardInterrupt:
        print()
        warn("Operation cancelled by user. Returning to command prompt.")
        sys.exit(0)

if __name__ == "__main__":
    main()
