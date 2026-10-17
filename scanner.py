"""
AIPFO — Directory Scanner
Walk directory trees and collect file metadata while strictly avoiding:
  - System and OS protected paths
  - Connected mobile phones / portable devices (CrossDevice, Phone Link)
  - Cloud storage on-demand placeholders (OneDrive, iCloud, Dropbox)
  - Reparse points, directory junctions, and remote network links
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from config import (
    IGNORED_DIRS, IGNORED_EXTENSIONS, PROTECTED_EXTENSIONS,
    PROTECTED_FULL_PATHS, MIN_FILE_SIZE, MAX_FILE_SIZE,
    FILE_ATTRIBUTE_REPARSE_POINT,
    is_device_or_sync_dir, is_cloud_or_offline_file,
    get_user_scan_targets, get_file_category,
)
from utils import info, warn, human_size, plural


@dataclass
class FileEntry:
    """Lightweight record for one on-disk file."""
    path: Path
    size: int                       # bytes
    modified: float                 # os.stat st_mtime
    created: float = 0.0            # os.stat st_ctime
    extension: str = ""             # e.g. ".pdf"
    category: str = ""              # e.g. "📄 Document (PDF)"
    quick_hash: str | None = None
    full_hash: str | None = None


@dataclass
class ScanResult:
    """Aggregated output of a directory scan."""
    roots: list[Path] = field(default_factory=list)
    files: list[FileEntry] = field(default_factory=list)
    skipped: int = 0
    protected_skipped: int = 0
    cloud_skipped: int = 0          # remote / cloud placeholders skipped
    errors: list[str] = field(default_factory=list)

    @property
    def total_size(self) -> int:
        return sum(f.size for f in self.files)


def _is_protected_path(dirpath: str) -> bool:
    """Check if a directory path is system-protected or a device/sync path."""
    dirpath_lower = dirpath.lower()
    for pp in PROTECTED_FULL_PATHS:
        if dirpath_lower == pp or dirpath_lower.startswith(pp + os.sep):
            return True
    return False


def _is_protected_dir_name(name: str) -> bool:
    """Check if a directory name matches a protected pattern or mobile/cloud sync."""
    if is_device_or_sync_dir(name):
        return True
    name_lower = name.lower()
    for ignored in IGNORED_DIRS:
        if name_lower == ignored.lower():
            return True
    if name.startswith("."):
        return True
    return False


def scan_directory(root: Path, *, show_progress: bool = True) -> ScanResult:
    """Recursively scan *root*, skipping system/protected paths and device/cloud data.

    Returns a :class:`ScanResult` with all eligible user files.
    """
    root = root.resolve()
    result = ScanResult(roots=[root])

    if not root.is_dir():
        result.errors.append(f"Not a directory: {root}")
        return result

    if show_progress:
        info(f"Scanning: {root}")

    file_count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        # ── Check if current dir is protected or device folder ──
        if _is_protected_path(dirpath) or is_device_or_sync_dir(os.path.basename(dirpath)):
            dirnames.clear()  # don't descend
            result.protected_skipped += 1
            continue

        # ── Prune subdirectories in-place (prunes junctions, devices, system) ──
        safe_dirs = []
        for d in dirnames:
            if _is_protected_dir_name(d):
                result.protected_skipped += 1
                continue
            full_sub = os.path.join(dirpath, d)
            if _is_protected_path(full_sub):
                result.protected_skipped += 1
                continue
            # Skip symlinks, junctions, and reparse points (avoids infinite loops & mounted phones)
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

            # Skip system file extensions
            if ext in PROTECTED_EXTENSIONS:
                result.protected_skipped += 1
                continue

            # Skip ignored extensions
            if ext in IGNORED_EXTENSIONS:
                result.skipped += 1
                continue

            # Stat the file without triggering online hydration
            try:
                stat = fpath.stat()
            except (OSError, PermissionError) as exc:
                result.errors.append(str(exc))
                continue

            # ── STRICT CHECK: Skip online/cloud placeholders and remote phone files ──
            if is_cloud_or_offline_file(stat):
                result.cloud_skipped += 1
                continue

            # Skip reparse points (symlinks / cloud tags)
            if getattr(stat, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT:
                result.skipped += 1
                continue

            # Skip tiny / zero-byte files
            if stat.st_size < MIN_FILE_SIZE:
                result.skipped += 1
                continue

            # Skip very large files
            if MAX_FILE_SIZE and stat.st_size > MAX_FILE_SIZE:
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
        skip_msg = f"skipped {result.skipped} ignored + {result.protected_skipped} system/device"
        if result.cloud_skipped:
            skip_msg += f" + {result.cloud_skipped} cloud placeholders"
        info(
            f"Found {len(result.files)} local files "
            f"({human_size(result.total_size)}), {skip_msg}"
        )

    return result


def scan_full_system(*, show_progress: bool = True) -> ScanResult:
    """Scan all safe user-accessible directories across the entire system.

    Excludes:
      - All system & OS directories
      - All other devices (connected mobile phones, CrossDevice, Phone Link)
      - All cloud-only on-demand storage (OneDrive, Dropbox, Google Drive)
      - All network / remote shares
    """
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

        # Skip if this is a subdirectory of something we already scanned
        already_covered = False
        for seen in seen_paths:
            if target_str.startswith(seen + os.sep) or target_str == seen:
                already_covered = True
                break
        if already_covered:
            continue

        result = scan_directory(target, show_progress=show_progress)
        combined.files.extend(result.files)
        combined.skipped += result.skipped
        combined.protected_skipped += result.protected_skipped
        combined.cloud_skipped += result.cloud_skipped
        combined.errors.extend(result.errors)
        seen_paths.add(target_str)

    if show_progress:
        print()
        skip_total = combined.skipped + combined.protected_skipped + combined.cloud_skipped
        info(
            f"TOTAL: {plural(len(combined.files), 'local file')} "
            f"({human_size(combined.total_size)}) across "
            f"{plural(len(targets), 'directory')} "
            f"(Skipped {combined.protected_skipped} system/mobile files, "
            f"{combined.cloud_skipped} cloud placeholders)"
        )

    return combined
