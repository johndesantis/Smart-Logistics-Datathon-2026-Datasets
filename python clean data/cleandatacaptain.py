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
  - Supports both AIS 2024 and AIS 2025 directory naming.
  - Skips non-CSV files.
  - Filters out None fieldnames to prevent ValueError.
  - Uses DictWriter with extrasaction='ignore' to preserve file structure.
"""
import csv
import os
import re
import glob

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
APP_ROOT = os.path.dirname(SCRIPT_DIR)

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

# Additional captain directories (if they exist)
ADDITIONAL_CAPTAIN_DIRS = [
    '/home/haha/Downloads/3-2. AIS Data/2024 Data/captain info/2024',
    '/home/haha/Downloads/3-2. AIS Data/2025 Data/captain info 2025',
]
for d in ADDITIONAL_CAPTAIN_DIRS:
    if os.path.exists(d) and d not in CAPTAIN_DIRS:
        CAPTAIN_DIRS.append(d)

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


def clean_captain_file(filepath, flagged_report_list):
    """Clean a single captain info CSV file in place.

    Flagged cells are prefixed with [BAD].
    All original data is preserved; only flagged values are modified.
    Already-marked cells are recognized and included in the flagged report.
    """
    with open(filepath, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        if fieldnames is None:
            return 0, 0
        # Filter out None fieldnames
        fieldnames = [fn for fn in fieldnames if fn is not None]
        rows = list(reader)

    flagged_cells = 0
    for row_idx, row in enumerate(rows):
        original_row = dict(row)
        # Remove None keys if any
        row = {k: v for k, v in row.items() if k is not None}
        # Rule: length == 0 AND width == 0 -> flag both
        length = safe_float(row.get('ais_capts_length'))
        width = safe_float(row.get('ais_capts_width'))
        if length is not None and width is not None and length == 0 and width == 0:
            if 'ais_capts_length' in row:
                raw_val = strip_mark(row['ais_capts_length'])
                if not is_marked(row['ais_capts_length']):
                    row['ais_capts_length'] = mark(row['ais_capts_length'])
                flagged_report_list.append({
                    'file': os.path.basename(filepath),
                    'filepath': filepath,
                    'row_index': row_idx + 1,
                    'column': 'ais_capts_length',
                    'original_value': raw_val,
                    'flagged_value': row['ais_capts_length'],
                    'reason': 'ais_capts_length == 0 AND ais_capts_width == 0'
                })
                flagged_cells += 1
            if 'ais_capts_width' in row:
                raw_val = strip_mark(row['ais_capts_width'])
                if not is_marked(row['ais_capts_width']):
                    row['ais_capts_width'] = mark(row['ais_capts_width'])
                flagged_report_list.append({
                    'file': os.path.basename(filepath),
                    'filepath': filepath,
                    'row_index': row_idx + 1,
                    'column': 'ais_capts_width',
                    'original_value': raw_val,
                    'flagged_value': row['ais_capts_width'],
                    'reason': 'ais_capts_length == 0 AND ais_capts_width == 0'
                })
                flagged_cells += 1

        # Rule: callsign purely numeric (no letters)
        callsign_raw = row.get('ais_capts_callsign') or ''
        callsign_val = strip_mark(callsign_raw)
        if callsign_val and CALLSIGN_NUMERIC_RE.match(callsign_val):
            if not is_marked(row.get('ais_capts_callsign')):
                row['ais_capts_callsign'] = mark(row['ais_capts_callsign'])
            flagged_report_list.append({
                'file': os.path.basename(filepath),
                'filepath': filepath,
                'row_index': row_idx + 1,
                'column': 'ais_capts_callsign',
                'original_value': callsign_val,
                'flagged_value': row['ais_capts_callsign'],
                'reason': 'ais_capts_callsign purely numeric (no letters)'
            })
            flagged_cells += 1

        # Rule: imo == 0 -> unacceptable
        imo = safe_float(row.get('ais_capts_imo'))
        if imo is not None and imo == 0:
            raw_imo = strip_mark(row.get('ais_capts_imo'))
            if not is_marked(row.get('ais_capts_imo')):
                row['ais_capts_imo'] = mark(row['ais_capts_imo'])
            flagged_report_list.append({
                'file': os.path.basename(filepath),
                'filepath': filepath,
                'row_index': row_idx + 1,
                'column': 'ais_capts_imo',
                'original_value': raw_imo,
                'flagged_value': row['ais_capts_imo'],
                'reason': 'ais_capts_imo == 0'
            })
            flagged_cells += 1

        # Rule: draft <= 0 -> unacceptable
        draft = safe_float(row.get('ais_capts_draft'))
        if draft is not None and draft <= 0:
            raw_draft = strip_mark(row.get('ais_capts_draft'))
            if not is_marked(row.get('ais_capts_draft')):
                row['ais_capts_draft'] = mark(row['ais_capts_draft'])
            flagged_report_list.append({
                'file': os.path.basename(filepath),
                'filepath': filepath,
                'row_index': row_idx + 1,
                'column': 'ais_capts_draft',
                'original_value': raw_draft,
                'flagged_value': row['ais_capts_draft'],
                'reason': 'ais_capts_draft <= 0'
            })
            flagged_cells += 1

        # Update row in place
        for k in original_row:
            if k is None:
                continue
            if k in row:
                original_row[k] = row[k]
        rows[row_idx] = original_row

    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator='\n', extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)

    return len(rows), flagged_cells


def main():
    total_files = 0
    total_rows = 0
    total_flagged = 0
    flagged_report_list = []

    # Collect all CSV files from all resolved captain directories
    captain_files = sorted(
        glob.glob(os.path.join(d, '*.csv')) for d in CAPTAIN_DIRS
    )
    # Flatten the list of lists
    captain_files = [f for sublist in captain_files for f in sublist]

    # Captain info (all resolved directories)
    for filepath in captain_files:
        rows, flagged = clean_captain_file(filepath, flagged_report_list)
        total_files += 1
        total_rows += rows
        total_flagged += flagged
        print(f'[CAPTAIN] {os.path.basename(filepath)}: {rows} rows, {flagged} cells flagged')

    print(f'\nTotal: {total_files} files, {total_rows} rows, {total_flagged} cells flagged')

    # Aggregate flagged report by row: count unique rows and list flagged columns
    row_map = {}  # key: (file, filepath, row_index) -> {columns: set, original_values: dict, flagged_values: dict, reasons: dict}
    for entry in flagged_report_list:
        key = (entry['file'], entry['filepath'], entry['row_index'])
        if key not in row_map:
            row_map[key] = {
                'file': entry['file'],
                'filepath': entry['filepath'],
                'row_index': entry['row_index'],
                'flagged_columns': set(),
                'original_values': {},
                'flagged_values': {},
                'reasons': {},
            }
        row_map[key]['flagged_columns'].add(entry['column'])
        row_map[key]['original_values'][entry['column']] = entry['original_value']
        row_map[key]['flagged_values'][entry['column']] = entry['flagged_value']
        row_map[key]['reasons'][entry['column']] = entry['reason']

    # Write flagged rows report
    report_path = os.path.join(APP_ROOT, 'flaggedcaptaincells.csv')
    with open(report_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['file', 'filepath', 'row_index', 'flagged_row_count', 'flagged_columns', 'original_values', 'flagged_values', 'reasons'])
        for key in sorted(row_map.keys()):
            info = row_map[key]
            writer.writerow([
                info['file'],
                info['filepath'],
                info['row_index'],
                len(info['flagged_columns']),
                ';'.join(sorted(info['flagged_columns'])),
                ';'.join(f'{col}={info["original_values"][col]}' for col in sorted(info['flagged_columns'])),
                ';'.join(f'{col}={info["flagged_values"][col]}' for col in sorted(info['flagged_columns'])),
                ';'.join(f'{col}={info["reasons"][col]}' for col in sorted(info['flagged_columns'])),
            ])
    print(f'\nFlagged rows report written to: {report_path} ({len(row_map)} rows flagged, {total_flagged} total cells flagged)')


if __name__ == '__main__':
    main()