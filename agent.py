#!/usr/bin/env python3
"""
AIPFO — AI Personal File Organizer
===================================
Feature 1 : Duplicate File Detection & Removal (System-Wide)

Usage
-----
  # Scan the ENTIRE system (auto-detects all user directories)
  python agent.py scan

  # Scan a specific folder only
  python agent.py scan --target C:\\Users\\you\\Documents

  # Full system clean — interactively review each group
  python agent.py clean

  # Full system auto-clean (non-interactive)
  python agent.py clean --auto

  # Dry-run — see what would happen without moving anything
  python agent.py clean --auto --dry-run

  # Clean a specific folder only
  python agent.py clean --target C:\\Users\\you\\Downloads --auto
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from scanner import scan_directory, scan_full_system, ScanResult
from dedup import (
    find_duplicates, move_duplicates_to_trash,
    display_duplicate_details, DedupResult, DuplicateGroup,
)
from hasher import get_file_content_preview
from reporter import generate_report, save_report
from config import get_trash_dir, PROTECTED_DIRS
from utils import header, subheader, info, success, warn, error, human_size, plural, C


# ─── Scan helper ────────────────────────────────────────────

def _do_scan(target: Path | None) -> ScanResult:
    """Run either a full system scan or a targeted folder scan."""
    if target:
        info(f"Targeted scan: {target}")
        return scan_directory(target)
    else:
        header("🌐 Full System Scan (Safe Local Mode)")
        info("Auto-detecting safe personal directories on local drives...")
        info("PROTECTED & EXCLUDED: System files, mobile devices (CrossDevice/Phone Link), and cloud on-demand sync.")
        print()
        return scan_full_system()


# ─── Interactive review ─────────────────────────────────────

def _interactive_review(dedup: DedupResult) -> DedupResult:
    """Let the user confirm or skip each duplicate group."""
    approved_groups: list[DuplicateGroup] = []

    subheader(f"Interactive Review — {plural(len(dedup.groups), 'group')} to review")

    for i, group in enumerate(dedup.groups, 1):
        total = 1 + len(group.duplicates)
        diff_names = any(d.path.name.lower() != group.original.path.name.lower() for d in group.duplicates)
        preview = get_file_content_preview(group.original.path)

        print(f"\n{C.BOLD}╔══ Group {i}/{len(dedup.groups)} "
              f"({total} identical files) ══╗{C.RESET}")
        print(f"  Match Type: {group.match_type.upper()}")
        if diff_names:
            print(f"  {C.MAGENTA}⚡ Notice    : Files have DIFFERENT NAMES but IDENTICAL inner data!{C.RESET}")
        print(f"  Content   : {C.CYAN}{preview}{C.RESET}")
        print(f"  File Type : {group.original.category}")
        print(f"  File Size : {human_size(group.original.size)}")
        print(f"  Wasted    : {C.RED}{human_size(group.wasted_bytes)}{C.RESET}")
        print(f"  Hash      : {group.content_hash[:16]}…")
        print()
        print(f"  {C.GREEN}✅ Keep  :{C.RESET} {group.original.path.name}  ({group.original.path})")
        for j, dup in enumerate(group.duplicates, 1):
            name_tag = f" {C.MAGENTA}(Different Name){C.RESET}" if dup.path.name.lower() != group.original.path.name.lower() else ""
            print(f"  {C.RED}🗑️ #{j}    :{C.RESET} {dup.path.name}{name_tag}  ({dup.path})")

        while True:
            choice = input(
                f"\n  Move {plural(len(group.duplicates), 'duplicate')} to trash? "
                f"[{C.GREEN}y{C.RESET}es / {C.RED}n{C.RESET}o / "
                f"{C.YELLOW}a{C.RESET}ll / {C.CYAN}q{C.RESET}uit] ▸ "
            ).strip().lower()

            if choice in ("y", "yes"):
                approved_groups.append(group)
                success("Marked for removal.")
                break
            elif choice in ("n", "no"):
                info("Skipped.")
                break
            elif choice in ("a", "all"):
                # Approve this and all remaining groups
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
        else:
            continue
        if choice in ("q", "quit") or choice in ("a", "all"):
            break

    filtered = DedupResult(
        groups=approved_groups,
        total_wasted=sum(g.wasted_bytes for g in approved_groups),
        files_scanned=dedup.files_scanned,
    )
    return filtered


# ─── CLI commands ────────────────────────────────────────────

def cmd_scan(args: argparse.Namespace) -> None:
    """Scan and show report — no files moved."""
    header("AIPFO — Duplicate File Scanner")

    target = args.target.resolve() if args.target else None

    t0 = time.perf_counter()
    scan = _do_scan(target)

    if not scan.files:
        warn("No user files found to scan.")
        return

    dedup = find_duplicates(scan)
    dedup.time_taken = time.perf_counter() - t0

    # Show detailed duplicate info
    display_duplicate_details(dedup)

    # Generate and save report
    report = generate_report(dedup, scan_roots=scan.roots)
    save_dir = target if target else Path.home()
    report_path = save_report(report, save_dir)

    success(f"Report saved to {report_path}")
    info(f"Scan completed in {dedup.time_taken:.1f}s")


def cmd_clean(args: argparse.Namespace) -> None:
    """Detect, display, and remove duplicate files."""
    header("AIPFO — Duplicate File Cleaner")

    target = args.target.resolve() if args.target else None

    if not target:
        warn("⚠️  FULL SYSTEM CLEAN MODE")
        info("This will scan all your personal files across every drive.")
        info("System files are ALWAYS protected and will NEVER be touched.")
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

    # Always show detailed file specifications
    display_duplicate_details(dedup)

    # Interactive review unless --auto
    if not args.auto:
        dedup = _interactive_review(dedup)
        if not dedup.groups:
            info("No groups approved — exiting.")
            return

    # Move (or dry-run)
    if not args.dry_run:
        subheader("Removing Duplicates")
        info(f"Moving duplicates to: {get_trash_dir()}")
        print()

    moved = move_duplicates_to_trash(dedup, dry_run=args.dry_run)

    # Generate and save report
    report = generate_report(
        dedup,
        scan_roots=scan.roots,
        moved=moved,
        dry_run=args.dry_run,
    )
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
        info(f"⚠️  No system files were touched.")

    success(f"📋 Report saved to: {report_path}")
    info(f"⏱️  Completed in {dedup.time_taken:.1f}s")


# ─── Argument parser ────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aipfo",
        description="AI Personal File Organizer — System-Wide Duplicate Removal",
        epilog="By default, scans the ENTIRE system (all user directories). "
               "Use --target to scan a specific folder only.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # scan
    p_scan = sub.add_parser(
        "scan",
        help="Detect duplicates and generate a detailed report (read-only)"
    )
    p_scan.add_argument(
        "--target", "-t", type=Path, default=None,
        help="Specific directory to scan (default: entire system)"
    )

    # clean
    p_clean = sub.add_parser(
        "clean",
        help="Detect and remove duplicate files"
    )
    p_clean.add_argument(
        "--target", "-t", type=Path, default=None,
        help="Specific directory to scan (default: entire system)"
    )
    p_clean.add_argument(
        "--auto", action="store_true",
        help="Skip interactive review; remove all duplicates automatically"
    )
    p_clean.add_argument(
        "--dry-run", action="store_true",
        help="Show what would happen without actually moving files"
    )

    return parser


# ─── Entry point ─────────────────────────────────────────────

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
