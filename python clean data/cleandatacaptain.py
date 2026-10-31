#!/usr/bin/env python3
"""Clean AIS captain info datasets in place.

Flags (marks) disrespectancies without removing any data.
Flagged cells are prefixed with [BAD].

Captain info rules:
  - ais_capts_length == 0 AND ais_capts_width == 0 -> flag both
  - ais_capts_callsign purely numeric (no letters) -> flag
  - ais_capts_imo == 0 -> flag
  - ais_capts_draft <= 0 -> flag

Captain info acceptable (NOT flagged):
  - ais_capts_trans_x == 0 AND ais_capts_trans_y == 0

Data handling:
  - Supports AIS 2024 and AIS 2025 directory naming.
  - Supports /home/haha/Downloads/3-2. AIS Data paths.
  - Skips non-CSV files.
  - Filters out None fieldnames to prevent ValueError.
  - Uses DictWriter with extrasaction='ignore' to preserve file structure.
  - Reports written in real time as flags are found.
  - Terminal output uses ANSI colors to highlight flagged columns.
"""
import csv
import os
import re
import glob

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
APP_ROOT = os.path.dirname(SCRIPT_DIR)

# ANSI color codes for terminal output (yellow highlight on flagged cells)
COLOR_YELLOW = '\033[93m'
COLOR_RESET = '\033[0m'
COLOR_BOLD = '\033[1m'


# Resolve directories for a given year
def _resolve_data_dirs(year):
    """Resolve captain/position directories for a given year."""
    base = os.path.join(APP_ROOT, f'AIS {year}')
    if os.path.exists(base):
        return (os.path.join(base, 'captain info'),
                os.path.join(base, 'position info'))
    base = os.path.join(APP_ROOT, f'{year} Data')
    if os.path.exists(base):
        return (os.path.join(base, 'captain info'),
                os.path.join(base, 'position info'))
    return None, None


# Collect directories for 2024 and 2025
CAPTAIN_DIRS = []
POSITION_DIRS = []
for year in ('2024', '2025'):
    cd, pd = _resolve_data_dirs(year)
    if cd and os.path.exists(cd):
        CAPTAIN_DIRS.append(cd)
    if pd and os.path.exists(pd):
        POSITION_DIRS.append(pd)

# Additional captain directories (if they exist - commented out /home/haha paths
# that may not exist in all environments; use AIS year directories instead)
# ADDITIONAL_CAPTAIN_DIRS = [
#     '/home/haha/Downloads/3-2. AIS Data/2024 Data/captain info/2024',
#     '/home/haha/Downloads/3-2. AIS Data/2025 Data/captain info 2025',
# ]
# for d in ADDITIONAL_CAPTAIN_DIRS:
#     if os.path.exists(d) and d not in CAPTAIN_DIRS:
#         CAPTAIN_DIRS.append(d)

# Backwards-compatible single-directory constants (first match)
CAPTAIN_DIR = CAPTAIN_DIRS[0] if CAPTAIN_DIRS else os.path.join(APP_ROOT, 'AIS 2025', 'captain info')

CALLSIGN_NUMERIC_RE = re.compile(r'^[0-9]+$')


def is_marked(value):
    """Check if a value already has [BAD] prefix."""
    return value is not None and str(value).startswith('[BAD]')


def mark(value):
    """Prefix a value with [BAD] if not already marked."""
    if value is None:
        return value
    s = str(value)
    if s.startswith('[BAD]'):
        return s
    return '[BAD]' + s


def safe_float(value):
    """Safely convert a value to float, returning None for empty/None.
    Strips [BAD] prefix if present."""
    if value is None or value == '':
        return None
    s = str(value)
    if s.startswith('[BAD]'):
        s = s[5:]
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def strip_mark(value):
    """Remove [BAD] prefix if present, returning the underlying value."""
    if value is None:
        return value
    s = str(value)
    if s.startswith('[BAD]'):
        return s[5:]
    return s


def _collect_all_fieldnames(file_paths):
    """Collect the union of all fieldnames across all files (sorted)."""
    all_names = set()
    for fp in file_paths:
        try:
            with open(fp, 'r', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                if reader.fieldnames:
                    for fn in reader.fieldnames:
                        if fn is not None:
                            all_names.add(fn)
        except Exception:
            pass
    return sorted(all_names)


def clean_captain_file(filepath, fieldnames, report_writer, report_file):
    """Clean a single captain info CSV file in place.

    Flagged cells are prefixed with [BAD].
    All original data is preserved; only flagged values are modified.
    Reports are written in real time as flags are found.
    Flagged rows are printed to terminal with ANSI color highlighting.
    """
    with open(filepath, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        file_fieldnames = reader.fieldnames
        if file_fieldnames is None:
            return 0, 0
        file_fieldnames = [fn for fn in file_fieldnames if fn is not None]
        rows = list(reader)

    flagged_cells = 0

    for row_idx, row in enumerate(rows):
        original_row = dict(row)
        row = {k: v for k, v in row.items() if k is not None}
        row_flagged_columns = set()
        row_reasons = {}

        # Rule: length == 0 AND width == 0 -> flag both
        length = safe_float(row.get('ais_capts_length'))
        width = safe_float(row.get('ais_capts_width'))
        if length is not None and width is not None and length == 0 and width == 0:
            for col in ('ais_capts_length', 'ais_capts_width'):
                if col in row:
                    raw_val = strip_mark(row[col])
                    if not is_marked(row[col]):
                        row[col] = mark(row[col])
                    row_flagged_columns.add(col)
                    row_reasons[col] = 'ais_capts_length == 0 AND ais_capts_width == 0'
                    flagged_cells += 1

        # Rule: callsign purely numeric (no letters)
        callsign_raw = row.get('ais_capts_callsign') or ''
        callsign_val = strip_mark(callsign_raw)
        if callsign_val and CALLSIGN_NUMERIC_RE.match(callsign_val):
            if 'ais_capts_callsign' in row:
                if not is_marked(row['ais_capts_callsign']):
                    row['ais_capts_callsign'] = mark(row['ais_capts_callsign'])
                row_flagged_columns.add('ais_capts_callsign')
                row_reasons['ais_capts_callsign'] = 'ais_capts_callsign purely numeric (no letters)'
                flagged_cells += 1

        # Rule: imo == 0 -> unacceptable
        imo = safe_float(row.get('ais_capts_imo'))
        if imo is not None and imo == 0:
            if 'ais_capts_imo' in row:
                raw_imo = strip_mark(row.get('ais_capts_imo'))
                if not is_marked(row.get('ais_capts_imo')):
                    row['ais_capts_imo'] = mark(row['ais_capts_imo'])
                row_flagged_columns.add('ais_capts_imo')
                row_reasons['ais_capts_imo'] = 'ais_capts_imo == 0'
                flagged_cells += 1

        # Rule: draft <= 0 -> unacceptable
        draft = safe_float(row.get('ais_capts_draft'))
        if draft is not None and draft <= 0:
            if 'ais_capts_draft' in row:
                raw_draft = strip_mark(row.get('ais_capts_draft'))
                if not is_marked(row.get('ais_capts_draft')):
                    row['ais_capts_draft'] = mark(row['ais_capts_draft'])
                row_flagged_columns.add('ais_capts_draft')
                row_reasons['ais_capts_draft'] = 'ais_capts_draft <= 0'
                flagged_cells += 1

        # Update row in place
        for k in original_row:
            if k is None:
                continue
            if k in row:
                original_row[k] = row[k]
        rows[row_idx] = original_row

        # Write to report and print to terminal in real time if this row has flags
        if row_flagged_columns:
            # --- Terminal output with ANSI colors on flagged columns ---
            colored_cells = []
            for col in fieldnames:
                val = row.get(col, '')
                if col in row_flagged_columns:
                    colored_cells.append(
                        f'{COLOR_YELLOW}[BAD]{strip_mark(val)}{COLOR_RESET}'
                    )
                else:
                    colored_cells.append(str(val))

            print(f'{COLOR_BOLD}[FLAGGED] {os.path.basename(filepath)} row {row_idx + 1}{COLOR_RESET}')
            print('  ' + ' | '.join(
                f'{col}={val}' for col, val in zip(fieldnames, colored_cells)
            ))
            print(f'  Flagged columns: {", ".join(sorted(row_flagged_columns))}')
            print(f'  Reasons: {"; ".join(f"{col}={row_reasons[col]}" for col in sorted(row_flagged_columns))}')
            print()

            # --- CSV report row with all columns ---
            report_writer.writerow([
                os.path.basename(filepath),
                filepath,
                row_idx + 1,
                len(row_flagged_columns),
                ';'.join(sorted(row_flagged_columns)),
                ';'.join(f'{col}={row_reasons[col]}' for col in sorted(row_flagged_columns)),
            ] + [
                row.get(col, '') for col in fieldnames
            ])
            report_file.flush()

    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=file_fieldnames, lineterminator='\n', extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)

    return len(rows), flagged_cells


def main():
    total_files = 0
    total_rows = 0
    total_flagged = 0

    # Collect all CSV files from all resolved captain directories
    captain_files = sorted(
        glob.glob(os.path.join(d, '*.csv')) for d in CAPTAIN_DIRS
    )
    captain_files = [f for sublist in captain_files for f in sublist]

    # Collect all unique fieldnames across all files for the report
    all_fieldnames = _collect_all_fieldnames(captain_files)

    # Open report file for real-time writing
    report_path = os.path.join(APP_ROOT, 'flaggedcaptaincells.csv')
    report_file = open(report_path, 'w', newline='', encoding='utf-8')
    report_writer = csv.writer(report_file)
    report_writer.writerow([
        'file', 'filepath', 'row_index', 'flagged_column_count', 'flagged_columns',
        'flagged_reasons',
    ] + all_fieldnames)
    report_file.flush()
    print(f'Writing flagged rows report in real-time to: {report_path}')
    print()

    # Captain info (all resolved directories)
    for filepath in captain_files:
        rows, flagged = clean_captain_file(filepath, all_fieldnames, report_writer, report_file)
        total_files += 1
        total_rows += rows
        total_flagged += flagged
        print(f'[CAPTAIN] {os.path.basename(filepath)}: {rows} rows, {flagged} cells flagged')

    print(f'\nTotal: {total_files} files, {total_rows} rows, {total_flagged} cells flagged')

    row_count = sum(1 for _ in open(report_path))
    report_file.close()
    print(f'\nFlagged rows report completed: {report_path} ({row_count - 1} rows flagged, {total_flagged} total cells flagged)')


if __name__ == '__main__':
    main()