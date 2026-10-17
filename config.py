"""
AIPFO — Central Configuration
All tuneable constants live here so every module stays in sync.
Includes strict exclusions for:
  - System directories and files
  - Connected mobile phones / portable devices (e.g. CrossDevice / Phone Link)
  - Cloud storage on-demand placeholders (OneDrive, iCloud, Dropbox, Google Drive)
  - Network drives and remote shares
"""

import os
import string
import ctypes
from pathlib import Path

# ─── Hashing ────────────────────────────────────────────────
HASH_ALGORITHM = "sha256"
# Read files in 64 KB chunks to keep memory usage low on large files.
CHUNK_SIZE = 64 * 1024  # 64 KB

# ─── Scanner ────────────────────────────────────────────────
# Minimum file size (bytes) to consider. Zero-byte files are always
# "duplicates" of each other but rarely meaningful — skip them.
MIN_FILE_SIZE = 1  # 1 byte

# Maximum file size to hash (skip very large files to keep runtime sane).
MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2 GB

# ─── WINDOWS FILE ATTRIBUTES (OFFLINE / CLOUD PLACEHOLDERS) ─
# These flags are used by OneDrive, iCloud, and Windows Phone Link.
# If a program touches or opens a file with these attributes, Windows
# halts the process to download the file from the cloud/phone over the network!
FILE_ATTRIBUTE_REPARSE_POINT        = 0x00000400
FILE_ATTRIBUTE_OFFLINE              = 0x00001000
FILE_ATTRIBUTE_RECALL_ON_OPEN       = 0x00040000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x00400000

# Any file with one of these attributes is NOT fully local on disk.
REMOTE_OR_CLOUD_ATTRIBUTES = (
    FILE_ATTRIBUTE_OFFLINE
    | FILE_ATTRIBUTE_RECALL_ON_OPEN
    | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
)


def is_cloud_or_offline_file(stat_obj) -> bool:
    """Return True if the file is an online/cloud placeholder that would
    trigger a remote download if opened."""
    attrs = getattr(stat_obj, "st_file_attributes", 0)
    return bool(attrs & REMOTE_OR_CLOUD_ATTRIBUTES)


# ─── OTHER DEVICE & CLOUD SYNC DIRECTORIES (NEVER TOUCH) ───
DEVICE_AND_SYNC_DIRS = {
    # ── Mobile phone & portable device links ──
    "CrossDevice",                  # Windows 11 Phone Link / Cross Device
    "PhoneLink",
    "YourPhone",
    "ConnectedDevices",
    "Portable Devices",
    "WPD",
    "WPDNSE",

    # ── Cloud storage sync & on-demand placeholders ──
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

    # ── Windows shell junctions & virtual links ──
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
    """Check if directory name matches an external device or cloud sync folder."""
    name_lower = name.lower()
    for d in DEVICE_AND_SYNC_DIRS:
        if name_lower == d.lower():
            return True
    for kw in DEVICE_KEYWORDS:
        if kw in name_lower:
            return True
    return False


# ─── SYSTEM / PROTECTED DIRECTORIES (NEVER TOUCH) ──────────
PROTECTED_DIRS = {
    # ── Windows core ──
    "Windows",
    "Windows.old",
    "Boot",
    "Recovery",
    "$Recycle.Bin",
    "$RECYCLE.BIN",
    "$SysReset",
    "$WINDOWS.~BT",
    "$Windows.~WS",
    "System Volume Information",
    "PerfLogs",
    "MSOCache",
    "ESD",
    "System.Sav",
    "Documents and Settings",  # Windows legacy junction to Users

    # ── Program installations ──
    "Program Files",
    "Program Files (x86)",
    "ProgramData",

    # ── User-level system directories ──
    "AppData",          # covers Local, LocalLow, Roaming entirely
    "Default",
    "Public",
    "All Users",

    # ── Virtualization & Dev tooling ──
    ".VirtualBox",
    "VirtualBox VMs",
    "__pycache__",
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".venv",
    "venv",
    ".env",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",

    # ── Our own trash folder ──
    "_duplicates_trash",
}

# Add all device/sync dirs to protected list
PROTECTED_DIRS.update(DEVICE_AND_SYNC_DIRS)

# Full absolute paths that should be skipped (resolved at runtime).
PROTECTED_FULL_PATHS: set[str] = set()


def _build_protected_paths() -> set[str]:
    """Build full protected paths for all detected drives."""
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
                    "OneDriveTemp", "ESD", "System.Sav",
                ]:
                    paths.add(os.path.join(drive, d).lower())
                # Also protect AppData and CrossDevice for every user
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


# File extensions that are system/binary and should NEVER be touched.
PROTECTED_EXTENSIONS = {
    ".sys", ".dll", ".exe", ".msi", ".msp", ".msu",
    ".drv", ".cpl", ".ocx", ".ax", ".scr",
    ".cat", ".mum", ".mui", ".manifest",
    ".evt", ".evtx",  # event logs
    ".etl",           # trace logs
    ".reg",           # registry exports
    ".efi",           # firmware
}

IGNORED_DIRS = PROTECTED_DIRS

IGNORED_EXTENSIONS = {
    ".tmp",
    ".lock",
}

# ─── Text file extensions (for content-aware comparison) ───
TEXT_EXTENSIONS = {
    ".txt", ".md", ".csv", ".json", ".xml", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".conf", ".log",
    ".html", ".htm", ".css", ".js", ".ts", ".jsx", ".tsx",
    ".py", ".java", ".c", ".cpp", ".h", ".hpp", ".cs",
    ".rb", ".go", ".rs", ".php", ".pl", ".r", ".m",
    ".sql", ".sh", ".bat", ".ps1", ".cmd",
    ".rtf", ".tex", ".bib", ".srt", ".sub", ".vtt",
    ".properties", ".env", ".gitignore", ".dockerignore",
    ".makefile", ".cmake", ".gradle",
}

# ─── Drive Detection (ONLY LOCAL FIXED DRIVES) ─────────────

def get_local_fixed_drives() -> list[Path]:
    """Return a list of LOCAL FIXED hard drives/SSDs on the system.
    
    Explicitly ignores:
      - Network drives / mapped shares (DRIVE_REMOTE = 4)
      - Mobile / USB / removable storage (DRIVE_REMOVABLE = 2)
      - CD/DVD drives (DRIVE_CDROM = 5)
      - RAM disks (DRIVE_RAMDISK = 6)
    """
    drives = []
    if os.name == "nt":
        for letter in string.ascii_uppercase:
            drive_str = f"{letter}:\\"
            if os.path.isdir(drive_str):
                # 3 = DRIVE_FIXED (Local Hard Drive / SSD)
                try:
                    dtype = ctypes.windll.kernel32.GetDriveTypeW(drive_str)
                    if dtype == 3:  # DRIVE_FIXED
                        drives.append(Path(drive_str))
                except Exception:
                    # Fallback to checking path if call fails
                    drives.append(Path(drive_str))
    else:
        drives.append(Path("/"))
    return drives


# ─── User directories (the REAL scan targets) ──────────────

def get_user_scan_targets() -> list[Path]:
    """Return safe, local user-owned directories to scan.

    Strictly excludes:
      - Mobile phone directories (CrossDevice, PhoneLink, etc.)
      - Cloud storage on-demand folders (OneDrive, Dropbox, etc.)
      - Windows system directories
    """
    targets = []
    home = Path.home()

    # Safe personal folders (only purely local ones)
    for folder in [
        "Desktop", "Documents", "Downloads", "Music",
        "Pictures", "Videos",
    ]:
        p = home / folder
        if p.is_dir():
            targets.append(p)

    # Also scan non-system root-level folders on every FIXED local drive
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
                # Skip junctions, symlinks, and reparse points
                if os.path.islink(str(item)):
                    continue
                try:
                    st = item.stat(follow_symlinks=False)
                    if getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT:
                        continue
                except (PermissionError, OSError):
                    continue
                # Skip Users folder (we already scan user personal folders above)
                if name_lower == "users":
                    continue
                targets.append(item)
        except (PermissionError, OSError):
            pass

    return targets


# ─── Dedup ──────────────────────────────────────────────────
TRASH_DIR_NAME = "_duplicates_trash"

def get_trash_dir() -> Path:
    """Central trash directory in user's home."""
    return Path.home() / TRASH_DIR_NAME

# ─── Reporting ──────────────────────────────────────────────
REPORT_FILENAME = "dedup_report.md"

# ─── Display ────────────────────────────────────────────────
SIZE_UNITS = ["B", "KB", "MB", "GB", "TB"]

# ─── File type categories ──────────────────────────────────
FILE_CATEGORIES = {
    # Documents
    ".pdf": "📄 Document (PDF)",
    ".doc": "📄 Document (Word)",
    ".docx": "📄 Document (Word)",
    ".xls": "📊 Spreadsheet (Excel)",
    ".xlsx": "📊 Spreadsheet (Excel)",
    ".ppt": "📽️ Presentation",
    ".pptx": "📽️ Presentation",
    ".txt": "📝 Text File",
    ".md": "📝 Markdown",
    ".csv": "📊 CSV Data",
    ".json": "📋 JSON Data",
    ".xml": "📋 XML Data",
    ".rtf": "📄 Rich Text",
    ".odt": "📄 Document (OpenDoc)",

    # Images
    ".jpg": "🖼️ Image (JPEG)",
    ".jpeg": "🖼️ Image (JPEG)",
    ".png": "🖼️ Image (PNG)",
    ".gif": "🖼️ Image (GIF)",
    ".bmp": "🖼️ Image (BMP)",
    ".svg": "🖼️ Image (SVG)",
    ".webp": "🖼️ Image (WebP)",
    ".ico": "🖼️ Icon",
    ".tiff": "🖼️ Image (TIFF)",
    ".raw": "🖼️ Image (RAW)",

    # Audio
    ".mp3": "🎵 Audio (MP3)",
    ".wav": "🎵 Audio (WAV)",
    ".flac": "🎵 Audio (FLAC)",
    ".aac": "🎵 Audio (AAC)",
    ".ogg": "🎵 Audio (OGG)",
    ".wma": "🎵 Audio (WMA)",
    ".m4a": "🎵 Audio (M4A)",

    # Video
    ".mp4": "🎬 Video (MP4)",
    ".avi": "🎬 Video (AVI)",
    ".mkv": "🎬 Video (MKV)",
    ".mov": "🎬 Video (MOV)",
    ".wmv": "🎬 Video (WMV)",
    ".flv": "🎬 Video (FLV)",
    ".webm": "🎬 Video (WebM)",

    # Archives
    ".zip": "📦 Archive (ZIP)",
    ".rar": "📦 Archive (RAR)",
    ".7z": "📦 Archive (7z)",
    ".tar": "📦 Archive (TAR)",
    ".gz": "📦 Archive (GZ)",

    # Code
    ".py": "🐍 Python Script",
    ".js": "💛 JavaScript",
    ".ts": "💙 TypeScript",
    ".java": "☕ Java",
    ".c": "⚙️ C Source",
    ".cpp": "⚙️ C++ Source",
    ".h": "⚙️ Header File",
    ".cs": "🟪 C# Source",
    ".html": "🌐 HTML",
    ".css": "🎨 Stylesheet",
    ".sql": "🗃️ SQL Script",
    ".sh": "🐚 Shell Script",
    ".ps1": "🐚 PowerShell Script",
    ".bat": "🐚 Batch Script",

    # Misc
    ".iso": "💿 Disk Image",
    ".torrent": "🔗 Torrent",
    ".log": "📋 Log File",
    ".bak": "💾 Backup File",
    ".ini": "⚙️ Config File",
    ".cfg": "⚙️ Config File",
    ".yaml": "⚙️ YAML Config",
    ".yml": "⚙️ YAML Config",
    ".toml": "⚙️ TOML Config",
}


def get_file_category(ext: str) -> str:
    """Return a human-friendly category for a file extension."""
    return FILE_CATEGORIES.get(ext.lower(), f"📎 {ext.upper()[1:]} File" if ext else "📎 Unknown")
