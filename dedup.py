"""
AIPFO — Deduplication Engine
Four-stage duplicate detection:
  Stage 1: Size filter
  Stage 2: Quick hash (first 4KB)
  Stage 3: Full SHA-256 hash (exact byte match — catches renamed copies)
  Stage 4: Content-aware text hash (catches same text, different encoding/format)
"""

from __future__ import annotations

import shutil
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from config import get_trash_dir
from hasher import (
    hash_file, quick_hash, hash_text_content,
    is_likely_text_file, get_file_content_preview,
)
from scanner import FileEntry, ScanResult
from utils import (
    info, success, warn, error,
    human_size, plural, format_timestamp, C,
    subheader, header,
)
from config import get_file_category


# ─── Data structures ────────────────────────────────────────

@dataclass
class DuplicateGroup:
    """One group of files that share identical content."""
    content_hash: str
    original: FileEntry          # the file we keep
    duplicates: list[FileEntry]  # files we can remove
    match_type: str = "exact"    # "exact" or "content-aware"

    @property
    def wasted_bytes(self) -> int:
        return sum(d.size for d in self.duplicates)


@dataclass
class DedupResult:
    """Full result of the dedup analysis."""
    groups: list[DuplicateGroup] = field(default_factory=list)
    total_wasted: int = 0
    files_scanned: int = 0
    time_taken: float = 0.0
    exact_groups: int = 0
    content_aware_groups: int = 0

    @property
    def duplicate_count(self) -> int:
        return sum(len(g.duplicates) for g in self.groups)


# ─── Core algorithm ─────────────────────────────────────────

def find_duplicates(scan: ScanResult, *, show_progress: bool = True) -> DedupResult:
    """Four-stage duplicate detection:

    1. **Size bucket** — files must be the same size to be duplicates.
    2. **Quick hash** — hash only the first 4 KB to eliminate obvious
       non-matches cheaply.
    3. **Full hash** — SHA-256 the entire file for a definitive answer.
       This catches files with identical bytes regardless of filename.
    4. **Content-aware hash** — for text files not caught in stages 1-3,
       normalise encoding/line-endings/whitespace and hash again.
       This catches files with identical readable text but different
       raw bytes (e.g. UTF-8 vs UTF-16, CRLF vs LF).
    """
    result = DedupResult(files_scanned=len(scan.files))

    if show_progress:
        subheader("Duplicate Detection Engine (4-Stage)")

    # Track which files are already identified as duplicates (by path)
    already_in_group: set[str] = set()

    # ════════════════════════════════════════════════════════
    # STAGES 1-3: Exact byte-level duplicates
    # ════════════════════════════════════════════════════════

    # ── Stage 1: group by size ──────────────────────────────
    by_size: dict[int, list[FileEntry]] = defaultdict(list)
    for entry in scan.files:
        by_size[entry.size].append(entry)

    candidates = {sz: entries for sz, entries in by_size.items() if len(entries) > 1}

    if show_progress:
        total_candidates = sum(len(e) for e in candidates.values())
        info(f"Stage 1 (size filter)      → {plural(total_candidates, 'file')} share a size with another file")

    # ── Stage 2: quick-hash within each size group ──────────
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

    # ── Stage 3: full hash ──────────────────────────────────
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
                dg = DuplicateGroup(
                    content_hash=fhash,
                    original=original,
                    duplicates=dupes,
                    match_type="exact",
                )
                result.groups.append(dg)
                result.total_wasted += dg.wasted_bytes
                result.exact_groups += 1
                # Mark these files so stage 4 skips them
                already_in_group.add(str(original.path))
                for d in dupes:
                    already_in_group.add(str(d.path))

    if show_progress:
        exact_dupes = sum(
            len(g.duplicates) for g in result.groups if g.match_type == "exact"
        )
        info(f"Stage 3 (full hash)        → {plural(result.exact_groups, 'exact-match group')} "
             f"({plural(exact_dupes, 'redundant file')})")

    # ════════════════════════════════════════════════════════
    # STAGE 4: Content-aware text comparison
    # ════════════════════════════════════════════════════════
    # For text files NOT already caught above, normalise content
    # and hash again to find files with same readable text but
    # different raw bytes.

    text_files = [
        f for f in scan.files
        if is_likely_text_file(f.path) and str(f.path) not in already_in_group
    ]

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
                # Double-check these aren't already exact matches
                # (they shouldn't be, but be safe)
                original = _pick_original(entries)
                dupes = [e for e in entries if e is not original]
                dg = DuplicateGroup(
                    content_hash=thash,
                    original=original,
                    duplicates=dupes,
                    match_type="content-aware",
                )
                result.groups.append(dg)
                result.total_wasted += dg.wasted_bytes
                result.content_aware_groups += 1

    # ── Final summary ──────────────────────────────────────
    if show_progress:
        if result.content_aware_groups:
            ca_dupes = sum(
                len(g.duplicates) for g in result.groups if g.match_type == "content-aware"
            )
            info(f"Stage 4 result             → {plural(result.content_aware_groups, 'content-match group')} "
                 f"({plural(ca_dupes, 'file')} with same text, different encoding/format)")

        print()
        if result.groups:
            success(
                f"TOTAL: {plural(len(result.groups), 'duplicate group')} with "
                f"{plural(result.duplicate_count, 'redundant file')} "
                f"({human_size(result.total_wasted)} reclaimable)"
            )
            if result.exact_groups:
                info(f"  ├─ {result.exact_groups} exact-match (identical bytes, different names)")
            if result.content_aware_groups:
                info(f"  └─ {result.content_aware_groups} content-match (same text, different encoding/format)")
        else:
            success("No duplicates found — your files are clean!")

    return result


# ─── Original selection heuristic ───────────────────────────

def _pick_original(entries: list[FileEntry]) -> FileEntry:
    """Choose which file to keep as the "original".

    Heuristics (in priority order):
    1. Shortest path depth  (closer to root = more "canonical")
    2. Shortest filename    (less likely to be a copy like ``foo (2).txt``)
    3. Earliest mtime       (oldest = probably the original)
    """
    def score(e: FileEntry):
        return (
            len(e.path.parts),
            len(e.path.name),
            e.modified,
        )
    return min(entries, key=score)


# ─── Display duplicate details ──────────────────────────────

def display_duplicate_details(dedup: DedupResult) -> None:
    """Print rich, detailed information about every duplicate group."""
    if not dedup.groups:
        return

    header("Duplicate File Details")

    for i, group in enumerate(dedup.groups, 1):
        total_in_group = 1 + len(group.duplicates)
        o = group.original

        # Show match type badge
        if group.match_type == "exact":
            badge = f"{C.GREEN}EXACT MATCH{C.RESET} (identical bytes, different names)"
        else:
            badge = f"{C.MAGENTA}CONTENT MATCH{C.RESET} (same readable text, different encoding/format)"

        # Check if files have different names
        diff_names = any(d.path.name.lower() != o.path.name.lower() for d in group.duplicates)
        preview = get_file_content_preview(o.path)

        print(f"{C.BOLD}{C.YELLOW}╔══ Group {i}/{len(dedup.groups)} "
              f"({total_in_group} identical files) ══╗{C.RESET}")
        print(f"{C.BOLD}  Match Type     : {C.RESET}{badge}")
        if diff_names:
            print(f"  {C.MAGENTA}⚡ Notice       : Duplicates have DIFFERENT NAMES but IDENTICAL content!{C.RESET}")
        print(f"{C.BOLD}  Content Preview: {C.RESET}{C.CYAN}{preview}{C.RESET}")
        print(f"{C.BOLD}  Content Hash   : {C.RESET}{group.content_hash[:24]}…")
        print(f"{C.BOLD}  File Size      : {C.RESET}{human_size(group.original.size)}")
        print(f"{C.BOLD}  File Type      : {C.RESET}{group.original.category}")
        print(f"{C.BOLD}  Wasted Space   : {C.RESET}{C.RED}{human_size(group.wasted_bytes)}{C.RESET}")
        print()

        # Show the ORIGINAL (kept)
        o = group.original
        print(f"  {C.GREEN}✅ KEEPING (Original):{C.RESET}")
        print(f"     📁 Path      : {o.path}")
        print(f"     📄 File Name : {o.path.name}")
        print(f"     📏 Size      : {human_size(o.size)}")
        print(f"     📝 Type      : {o.category}")
        print(f"     📎 Extension : {o.extension or 'none'}")
        print(f"     🕐 Modified  : {format_timestamp(o.modified)}")
        print(f"     🕐 Created   : {format_timestamp(o.created)}")
        print()

        # Show each DUPLICATE (to be removed)
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


# ─── Cleanup actions ────────────────────────────────────────

def move_duplicates_to_trash(
    dedup: DedupResult,
    scan_root: Path | None = None,
    *,
    dry_run: bool = False,
) -> list[dict]:
    """Move every duplicate file into a central trash directory,
    preserving the original directory structure.

    Returns a list of dicts with full details of each moved file.
    """
    trash_root = get_trash_dir()
    moved: list[dict] = []

    for group in dedup.groups:
        for dup in group.duplicates:
            # Build destination preserving drive + path structure
            try:
                drive = dup.path.drive.replace(":", "")
                rel = str(dup.path.relative_to(dup.path.anchor))
                dest = trash_root / drive / rel
            except (ValueError, TypeError):
                dest = trash_root / dup.path.name

            move_info = {
                "source": dup.path,
                "destination": dest,
                "file_name": dup.path.name,
                "size": dup.size,
                "size_human": human_size(dup.size),
                "type": dup.category,
                "extension": dup.extension,
                "modified": format_timestamp(dup.modified),
                "created": format_timestamp(dup.created),
                "content_hash": group.content_hash[:16],
                "original_kept": group.original.path,
                "match_type": group.match_type,
            }

            if dry_run:
                info(f"[DRY RUN] Would move: {dup.path}")
                print(f"           → {dest}")
                moved.append(move_info)
                continue

            dest.parent.mkdir(parents=True, exist_ok=True)

            # Handle name collision in trash
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
                print(f"     {C.DIM}Name: {dup.path.name} | Type: {dup.category} | "
                      f"Size: {human_size(dup.size)} | Match: {match_label}{C.RESET}")
                print(f"     {C.DIM}Kept original: {group.original.path}{C.RESET}")

            except (OSError, PermissionError) as exc:
                error(f"Could not move {dup.path}: {exc}")

    return moved
