# 🗂️ AIPFO — AI Personal File Organizer

An AI-powered file management agent built **one feature at a time**.

## ✅ Feature 1 — Duplicate File Detection & Removal (Content-First & System-Wide)

Scans your files, inspects the **entire inner content** of every file, and safely removes duplicates — **even when files have completely different names, different extensions, or are in different folders**.

### How It Works — 4-Stage Content Engine

```
Stage 1: Size Filter             → Groups files by byte size
Stage 2: Quick Hash (4 KB)       → Hashes initial bytes to rule out non-matches cheaply
Stage 3: Full SHA-256 Hash       → Hashes entire file content (exact binary matches across different names)
Stage 4: Content-Aware Analysis  → Normalizes text encoding/line endings/whitespace for semantic text matches
```

### 🛡️ System File Protection (Safety First)
The agent strictly protects all operating system and application files:
- **Never touches:** `C:\Windows`, `C:\Program Files`, `C:\ProgramData`, `C:\Boot`, `C:\Recovery`, `AppData`
- **Never touches system extensions:** `.dll`, `.exe`, `.sys`, `.drv`, `.manifest`, `.mui`, etc.
- Focuses purely on user-owned personal files and documents across all drives.
- **Safe by default:** Duplicates are moved to `_duplicates_trash/` with directory structure preserved (not permanently deleted).

### 🔍 Matches Across Different Names & Locations

The agent **does not care what files are named**. It only looks inside:

| Group | Files Found | Inner Content | Result |
|-------|-------------|---------------|--------|
| Group 1 | `backup/random_temp_notes.md`<br>`documents/Financial_Report_2026.txt`<br>`projects/zebra_archive_alpha.log` | Identical revenue target text | **Duplicate Caught & Cleaned** ✅ |
| Group 2 | `photos/Sunset_At_Beach_HD.dat`<br>`documents/unnamed_attachment_9942.bin` | Identical 8 KB binary bytes | **Duplicate Caught & Cleaned** ✅ |
| Group 3 | `projects/draft_backup_archive.rst`<br>`documents/Project_Charter_Signed.txt` | Identical text (CRLF vs LF) | **Duplicate Caught & Cleaned** ✅ |

### 🚀 Usage

```powershell
cd C:\Users\sonel\Downloads\AIPFO

# 1. Scan a specific folder (fast preview)
python agent.py scan --target C:\Users\sonel\Downloads\AIPFO\test_folder

# 2. Scan your entire system (auto-detects all drives & user folders)
python agent.py scan

# 3. Interactive clean (reviews each group, displays content preview & specs)
python agent.py clean --target C:\Users\sonel\Downloads\AIPFO\test_folder

# 4. Auto clean (moves duplicates directly to trash)
python agent.py clean --target C:\Users\sonel\Downloads\AIPFO\test_folder --auto

# 5. Dry-run clean (simulates what would be deleted without touching files)
python agent.py clean --target C:\Users\sonel\Downloads\AIPFO\test_folder --auto --dry-run
```

### 📋 Full Specifications Displayed for Every File
Before and after deleting, the agent displays:
- **Content Preview:** Snippet of the actual content inside the file
- **File Name & Path:** Source location and trash destination
- **File Size:** Human-readable bytes / KB / MB / GB
- **File Type & Extension:** E.g., `📝 Markdown (.md)`, `📄 Document (.pdf)`
- **Creation & Modification Timestamps**
- **Match Type Badge:** `EXACT MATCH` vs `CONTENT MATCH`
- **Notice if filenames are completely different**

### 🧪 Automated Tests

```powershell
python test_dedup.py
```
Runs 8 automated end-to-end tests verifying hashing, size filtering, heuristic selection, dry-run safety, move operations, and report generation.
