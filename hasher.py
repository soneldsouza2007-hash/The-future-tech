"""
AIPFO — File Hasher
Two hashing strategies:
  1. Byte-level hash  — exact binary match (catches renamed copies)
  2. Content-aware hash — normalises text before hashing (catches
     same text with different encodings, line endings, BOM, whitespace)

Safety:
  Strictly guards against opening cloud-only placeholders or remote mobile
  files that would trigger Windows to download files over the network.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

from config import (
    HASH_ALGORITHM, CHUNK_SIZE, TEXT_EXTENSIONS,
    FILE_ATTRIBUTE_REPARSE_POINT, is_cloud_or_offline_file,
)
from utils import warn


def _is_safe_local_file(filepath: Path) -> bool:
    """Ensure the file is truly local on disk and not a cloud/device placeholder."""
    try:
        stat = filepath.stat()
        if is_cloud_or_offline_file(stat):
            return False
        if getattr(stat, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT:
            return False
        return True
    except Exception:
        return False


# ─── Byte-level hashing ─────────────────────────────────────

def hash_file(filepath: Path, algorithm: str = HASH_ALGORITHM,
              chunk_size: int = CHUNK_SIZE) -> Optional[str]:
    """Return the hex-digest of *filepath* using *algorithm*.

    Returns ``None`` if the file cannot be read or is a remote/cloud placeholder.
    """
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
    """Hash only the first *num_bytes* of a file as a fast pre-filter."""
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


# ─── Content-aware text hashing ─────────────────────────────

def _normalise_text(raw: bytes) -> str:
    """Decode raw bytes to text, normalising away superficial differences."""
    for encoding in ("utf-8-sig", "utf-8", "utf-16", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except (UnicodeDecodeError, ValueError):
            continue
    else:
        return raw.hex()

    # Normalise line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Strip trailing whitespace per line + leading/trailing blank lines
    lines = [line.rstrip() for line in text.split("\n")]
    text = "\n".join(lines).strip()

    return text


def hash_text_content(filepath: Path) -> Optional[str]:
    """Hash the *normalised text content* of a file."""
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
    """Return True if the file contains readable text, regardless of extension or name."""
    if not _is_safe_local_file(filepath):
        return False

    ext = filepath.suffix.lower()
    if ext in TEXT_EXTENSIONS:
        return True
    try:
        with open(filepath, "rb") as f:
            chunk = f.read(1024)
            if not chunk:
                return False
            if b"\x00" in chunk:
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
    """Return a short preview of the internal content to prove matching data."""
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
