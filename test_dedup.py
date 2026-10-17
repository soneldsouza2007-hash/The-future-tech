"""
AIPFO — Test Harness
Creates a temporary directory with known duplicate files, runs the agent,
and validates results.
"""

import os
import shutil
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent))

from scanner import scan_directory
from dedup import find_duplicates, move_duplicates_to_trash
from reporter import generate_report, save_report
from utils import header, success, error, info, plural


TEST_DIR = Path(__file__).parent / "_test_sandbox"


def setup_test_files() -> Path:
    """Create a test directory with known duplicates."""
    # Clean slate
    if TEST_DIR.exists():
        shutil.rmtree(TEST_DIR)

    TEST_DIR.mkdir(parents=True)

    # ── Group A: 3 identical text files ─────────────────────
    content_a = b"This is a sample document about AI agents.\n" * 100
    (TEST_DIR / "docs").mkdir()
    (TEST_DIR / "docs" / "report.txt").write_bytes(content_a)
    (TEST_DIR / "docs" / "report_copy.txt").write_bytes(content_a)
    (TEST_DIR / "backup").mkdir()
    (TEST_DIR / "backup" / "report_old.txt").write_bytes(content_a)

    # ── Group B: 2 identical images (simulated binary) ──────
    content_b = bytes(range(256)) * 500  # 128 KB pseudo-binary
    (TEST_DIR / "images").mkdir()
    (TEST_DIR / "images" / "photo.bin").write_bytes(content_b)
    (TEST_DIR / "images" / "photo (2).bin").write_bytes(content_b)

    # ── Unique files (should NOT be flagged) ────────────────
    (TEST_DIR / "unique_file.txt").write_text("I am unique!", encoding="utf-8")
    (TEST_DIR / "docs" / "notes.md").write_text("# Notes\nNo duplicates here.", encoding="utf-8")

    # ── Same size but different content (should NOT match) ──
    (TEST_DIR / "same_size_a.dat").write_bytes(b"A" * 1024)
    (TEST_DIR / "same_size_b.dat").write_bytes(b"B" * 1024)

    return TEST_DIR


def run_tests() -> bool:
    """Run all assertions and return True if everything passes."""
    header("AIPFO Test Suite")
    passed = 0
    failed = 0

    # ── Setup ───────────────────────────────────────────────
    test_dir = setup_test_files()
    info(f"Test directory created at: {test_dir}")

    # ── Test 1: Scanner finds correct file count ────────────
    scan = scan_directory(test_dir, show_progress=False)
    expected_files = 7  # 3(A) + 2(B) + 1(unique) + 1(notes) - but we have same_size files too
    # Actually: report.txt, report_copy.txt, report_old.txt, photo.bin, photo (2).bin,
    #           unique_file.txt, notes.md, same_size_a.dat, same_size_b.dat = 9
    expected_files = 9
    if len(scan.files) == expected_files:
        success(f"Test 1 PASSED: Scanner found {expected_files} files")
        passed += 1
    else:
        error(f"Test 1 FAILED: Expected {expected_files} files, got {len(scan.files)}")
        for f in scan.files:
            print(f"  - {f.path}")
        failed += 1

    # ── Test 2: Dedup finds exactly 2 groups ────────────────
    dedup = find_duplicates(scan, show_progress=False)
    if len(dedup.groups) == 2:
        success(f"Test 2 PASSED: Found 2 duplicate groups")
        passed += 1
    else:
        error(f"Test 2 FAILED: Expected 2 groups, got {len(dedup.groups)}")
        failed += 1

    # ── Test 3: Group A has 2 duplicates, Group B has 1 ─────
    group_sizes = sorted([len(g.duplicates) for g in dedup.groups])
    if group_sizes == [1, 2]:
        success(f"Test 3 PASSED: Correct duplicate counts per group (1, 2)")
        passed += 1
    else:
        error(f"Test 3 FAILED: Expected [1, 2] duplicates, got {group_sizes}")
        failed += 1

    # ── Test 4: same_size files are NOT flagged ─────────────
    all_dup_paths = set()
    for g in dedup.groups:
        all_dup_paths.add(g.original.path)
        for d in g.duplicates:
            all_dup_paths.add(d.path)

    same_size_a = (test_dir / "same_size_a.dat").resolve()
    same_size_b = (test_dir / "same_size_b.dat").resolve()
    if same_size_a not in all_dup_paths and same_size_b not in all_dup_paths:
        success("Test 4 PASSED: Same-size-different-content files not flagged")
        passed += 1
    else:
        error("Test 4 FAILED: Same-size files incorrectly flagged as duplicates")
        failed += 1

    # ── Test 5: Original selection heuristic ────────────────
    # For group A, the original should be "docs/report.txt" (shortest path)
    for g in dedup.groups:
        if "report" in g.original.path.name.lower():
            if g.original.path.name == "report.txt":
                success("Test 5 PASSED: Correct original selected (shortest path)")
                passed += 1
            else:
                error(f"Test 5 FAILED: Expected report.txt as original, got {g.original.path.name}")
                failed += 1
            break

    # ── Test 6: Dry-run doesn't actually move files ─────────
    moved = move_duplicates_to_trash(dedup, test_dir, dry_run=True)
    all_exist = all(m["source"].exists() for m in moved)
    if all_exist and len(moved) == dedup.duplicate_count:
        success(f"Test 6 PASSED: Dry run — {len(moved)} files listed, none moved")
        passed += 1
    else:
        error(f"Test 6 FAILED: Dry run altered files on disk")
        failed += 1

    # ── Test 7: Actual move works ───────────────────────────
    moved = move_duplicates_to_trash(dedup, test_dir, dry_run=False)
    sources_gone = all(not m["source"].exists() for m in moved)
    dests_exist = all(m["destination"].exists() for m in moved)
    if sources_gone and dests_exist:
        success(f"Test 7 PASSED: {len(moved)} duplicates moved to trash")
        passed += 1
    else:
        error("Test 7 FAILED: Move operation did not work correctly")
        failed += 1

    # ── Test 8: Report generation ───────────────────────────
    report = generate_report(dedup, scan_roots=[test_dir], moved=moved)
    report_path = save_report(report, test_dir)
    if report_path.exists() and "Duplicate File Report" in report:
        success("Test 8 PASSED: Report generated and saved")
        passed += 1
    else:
        error("Test 8 FAILED: Report generation issue")
        failed += 1

    # ── Summary ─────────────────────────────────────────────
    header("Test Results")
    total = passed + failed
    if failed == 0:
        success(f"All {total} tests passed! ✅")
    else:
        error(f"{failed}/{total} tests failed ❌")

    # Cleanup
    if TEST_DIR.exists():
        shutil.rmtree(TEST_DIR)
        info("Test sandbox cleaned up.")

    return failed == 0


if __name__ == "__main__":
    ok = run_tests()
    sys.exit(0 if ok else 1)
