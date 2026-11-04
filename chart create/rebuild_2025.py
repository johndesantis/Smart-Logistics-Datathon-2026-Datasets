import os
import glob
import sys

# Suppress per-row terminal output from the imported cleaner to keep runtime reasonable.
import builtins
builtins.print = lambda *args, **kwargs: None

sys.path.insert(0, "/home/haha/Downloads/3-2. AIS Data")
import cleandataposition as c

APP_ROOT = "/home/haha/Downloads"
POSITION_DIR = "/home/haha/Downloads/3-2. AIS Data/2025 Data/position info 2025"
POSITION_DIRS = [POSITION_DIR] if os.path.exists(POSITION_DIR) else []
REPORT_PATH = os.path.join(APP_ROOT, "flaggedpositioncells2025.csv")

position_files = []
seen_basenames = set()
for d in POSITION_DIRS:
    for f in sorted(glob.glob(os.path.join(d, "*.csv"))):
        basename = os.path.basename(f)
        if basename not in seen_basenames:
            seen_basenames.add(basename)
            position_files.append(f)
position_files = sorted(position_files)

all_fieldnames = c._collect_all_fieldnames(position_files)

report_file = open(REPORT_PATH, "w", newline="", encoding="utf-8")
report_writer = __import__("csv").writer(report_file)
report_writer.writerow([
    "file", "filepath", "row_index", "flagged_column_count", "flagged_columns",
    "flagged_reasons",
] + all_fieldnames)
report_file.flush()

total_files = 0
total_rows = 0
total_flagged = 0
for filepath in position_files:
    rows, flagged = c.clean_position_file(filepath, all_fieldnames, report_writer, report_file)
    total_files += 1
    total_rows += rows
    total_flagged += flagged

report_file.close()
row_count = sum(1 for _ in open(REPORT_PATH, encoding="utf-8"))
print(f"Rebuilt {REPORT_PATH}: {total_files} files, {total_rows} rows, {total_flagged} cells flagged, {row_count - 1} report rows")
