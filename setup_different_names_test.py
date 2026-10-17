"""
Setup test files where duplicate files have COMPLETELY DIFFERENT names,
different extensions, and different directory locations.
"""

import shutil
from pathlib import Path

root = Path(r"C:\Users\sonel\Downloads\AIPFO\test_folder")
if root.exists():
    shutil.rmtree(root)

docs = root / "documents"
backup = root / "backup"
photos = root / "photos"
projects = root / "projects"

for d in [docs, backup, photos, projects]:
    d.mkdir(parents=True, exist_ok=True)

# ── Group 1: Exact bytes, COMPLETELY DIFFERENT names & extensions ──
content1 = "CONFIDENTIAL REVENUE TARGETS: Q1: $4.2M, Q2: $5.1M, Q3: $6.0M. Approved by Board.\n" * 5
(docs / "Financial_Report_2026.txt").write_text(content1, encoding="utf-8")
(backup / "random_temp_notes.md").write_text(content1, encoding="utf-8")
(projects / "zebra_archive_alpha.log").write_text(content1, encoding="utf-8")

# ── Group 2: Binary data, COMPLETELY DIFFERENT names & extensions ──
content2 = bytes(range(256)) * 32
(photos / "Sunset_At_Beach_HD.dat").write_bytes(content2)
(docs / "unnamed_attachment_9942.bin").write_bytes(content2)

# ── Group 3: Text content match, DIFFERENT names, DIFFERENT line endings & whitespace ──
text3_crlf = "Project Charter: Build the next-generation AI file management assistant.\r\nPhase 1: Deduplication.\r\n"
text3_lf = "Project Charter: Build the next-generation AI file management assistant.\nPhase 1: Deduplication.   \n"
(docs / "Project_Charter_Signed.txt").write_bytes(text3_crlf.encode("utf-8"))
(projects / "draft_backup_archive.rst").write_bytes(text3_lf.encode("utf-8"))

# ── Unique files (must NOT be flagged) ──
(docs / "My_Private_Diary.txt").write_text("Today was a great day exploring AI agents.", encoding="utf-8")
(projects / "source_code.py").write_text("print('Hello world')", encoding="utf-8")

print("All test files successfully populated with completely different names!")
