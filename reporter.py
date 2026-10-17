"""
AIPFO — Report Generator
Produces a human-readable Markdown report with full file specifications
after a dedup run — now includes match type (exact vs content-aware).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from config import REPORT_FILENAME, get_trash_dir
from dedup import DedupResult
from hasher import get_file_content_preview
from utils import human_size, plural, format_timestamp


def generate_report(
    dedup: DedupResult,
    scan_roots: list[Path] | None = None,
    moved: list[dict] | None = None,
    dry_run: bool = False,
) -> str:
    """Return a Markdown string summarising the dedup analysis with
    full file specifications."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines: list[str] = []

    lines.append("# 🗂️ AIPFO — Duplicate File Report")
    lines.append("")
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

    lines.append("---")
    lines.append("")

    # ── Per-group details with full specifications ──────────
    for i, group in enumerate(dedup.groups, 1):
        o = group.original
        match_badge = "🔵 Exact Match" if group.match_type == "exact" else "🟣 Content Match"
        lines.append(f"## Group {i} — {group.original.category}  "
                      f"({human_size(group.original.size)} each)")
        lines.append("")
        lines.append(f"- **Match Type:** {match_badge}")
        diff_names = any(d.path.name.lower() != o.path.name.lower() for d in group.duplicates)
        if diff_names:
            lines.append(f"- ⚡ **Filename Status:** Duplicates have **DIFFERENT NAMES** but **IDENTICAL content inside**")
        lines.append(f"- **Content Preview:** `{get_file_content_preview(o.path)}`")
        if group.match_type == "exact":
            lines.append(f"  - _Identical bytes — same content, possibly different file names_")
        else:
            lines.append(f"  - _Same readable text — different encoding, line endings, or whitespace_")
        lines.append(f"- **Content Hash:** `{group.content_hash[:24]}…`")
        lines.append(f"- **File Size:** {human_size(group.original.size)}")
        lines.append(f"- **File Type:** {group.original.category}")
        lines.append(f"- **Wasted Space:** {human_size(group.wasted_bytes)}")
        lines.append("")

        # Table header
        lines.append("| # | Status | File Name | Extension | Path | Size | Type | Modified | Created |")
        lines.append("|---|--------|-----------|-----------|------|------|------|----------|---------|")

        # Original
        o = group.original
        lines.append(
            f"| 1 | ✅ **Kept** | `{o.path.name}` | `{o.extension}` | "
            f"`{o.path.parent}` | {human_size(o.size)} | {o.category} | "
            f"{format_timestamp(o.modified)} | {format_timestamp(o.created)} |"
        )

        # Duplicates
        for j, dup in enumerate(group.duplicates, 2):
            if moved:
                status = "🗑️ **Removed**"
            elif dry_run:
                status = "🔍 Would remove"
            else:
                status = "🗑️ Duplicate"
            lines.append(
                f"| {j} | {status} | `{dup.path.name}` | `{dup.extension}` | "
                f"`{dup.path.parent}` | {human_size(dup.size)} | {dup.category} | "
                f"{format_timestamp(dup.modified)} | {format_timestamp(dup.created)} |"
            )

        lines.append("")

    # ── Moved files summary ─────────────────────────────────
    if moved:
        lines.append("---")
        lines.append("")
        lines.append("## 🗑️ Removed Files — Full Specifications")
        lines.append("")
        lines.append("| # | File Name | Type | Extension | Size | Match | Original Location | Moved To | Original Kept |")
        lines.append("|---|-----------|------|-----------|------|-------|-------------------|----------|---------------|")
        for idx, m in enumerate(moved, 1):
            match_label = "Exact" if m.get('match_type') == 'exact' else "Content"
            lines.append(
                f"| {idx} | `{m['file_name']}` | {m['type']} | "
                f"`{m['extension']}` | {m['size_human']} | {match_label} | "
                f"`{m['source'].parent}` | `{m['destination']}` | "
                f"`{m['original_kept']}` |"
            )
        lines.append("")

    # ── Summary ─────────────────────────────────────────────
    lines.append("---")
    lines.append("")
    lines.append("## 📊 Summary")
    lines.append("")
    if moved and not dry_run:
        lines.append(f"- ✅ **{plural(len(moved), 'duplicate file')}** removed")
        lines.append(f"- 💾 **{human_size(dedup.total_wasted)}** of disk space recovered")
        lines.append(f"- 📂 Duplicates moved to: `{get_trash_dir()}`")
        lines.append(f"- ⚠️ No system files were touched")
    elif dry_run:
        lines.append(f"- 🔍 **Dry run** — no files were moved")
        lines.append(f"- 💾 **{human_size(dedup.total_wasted)}** could be recovered")
    else:
        lines.append(f"- 🔎 **{plural(dedup.duplicate_count, 'duplicate file')}** identified")
        lines.append(f"- 💾 **{human_size(dedup.total_wasted)}** reclaimable")

    lines.append("")
    lines.append("### Detection Methods Used")
    lines.append("")
    lines.append("| Method | What it catches |")
    lines.append("|--------|----------------|")
    lines.append("| 🔵 Exact Match | Files with identical bytes but different names/locations |")
    lines.append("| 🟣 Content Match | Text files with same readable content but different encoding, line endings, or whitespace |")
    lines.append("")

    return "\n".join(lines)


def save_report(report: str, save_dir: Path | None = None) -> Path:
    """Write the report to disk and return the path."""
    if save_dir is None:
        save_dir = Path.home()
    save_dir.mkdir(parents=True, exist_ok=True)
    report_path = save_dir / REPORT_FILENAME
    report_path.write_text(report, encoding="utf-8")
    return report_path
