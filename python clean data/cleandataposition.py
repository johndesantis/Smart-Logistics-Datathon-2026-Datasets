#!/usr/bin/env python3
"""Clean AIS position info datasets in place.

Flags (marks) disrespectancies without removing any data.
Flagged cells are prefixed with [BAD].

Position info rules:
  - latitude outside [-90, 90] -> flag
  - longitude outside [-180, 180] -> flag
  - speed < 0 and speed != -1 -> flag (-1 = unknown)
  - course < 0 or course > 360, and course != -1 -> flag (-1 = unknown)
  - latitude == 0 AND longitude == 0 -> flag both (except only latitude = 0 is acceptable)

Position info acceptable (NOT flagged):
  - speed == 0 (stopped vessel)
  - course == 0 (valid heading north)
  - speed > 0.5, course > 0 within valid ranges

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

# Additional position directories (if they exist)
ADDITIONAL_POSITION_DIRS = [
    '/home/haha/Downloads/3-2. AIS Data/2024 Data/position info/2024',
    '/home/haha/Downloads/3-2. AIS Data/2025 Data/position info 2025',
]
for d in ADDITIONAL_POSITION_DIRS:
    if os.path.exists(d) and d not in POSITION_DIRS:
        POSITION_DIRS.append(d)

# Backwards-compatible single-directory constants (first match)
POSITION_DIR = POSITION_DIRS[0] if POSITION_DIRS else os.path.join(APP_ROOT, 'AIS 2025', 'position info')


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


def clean_position_file(filepath, fieldnames, report_writer, report_file):
    """Clean a single position info CSV file in place.

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

        # Rule: latitude outside [-90, 90]
        lat = safe_float(row.get('ais_position_latitude'))
        if lat is not None and (lat < -90 or lat > 90):
            if 'ais_position_latitude' in row:
                raw_lat = strip_mark(row.get('ais_position_latitude'))
                if not is_marked(row.get('ais_position_latitude')):
                    row['ais_position_latitude'] = mark(row['ais_position_latitude'])
                row_flagged_columns.add('ais_position_latitude')
                row_reasons['ais_position_latitude'] = 'latitude outside [-90, 90]'
                flagged_cells += 1

        # Rule: longitude outside [-180, 180]
        lon = safe_float(row.get('ais_position_longitude'))
        if lon is not None and (lon < -180 or lon > 180):
            if 'ais_position_longitude' in row:
                raw_lon = strip_mark(row.get('ais_position_longitude'))
                if not is_marked(row.get('ais_position_longitude')):
                    row['ais_position_longitude'] = mark(row['ais_position_longitude'])
                row_flagged_columns.add('ais_position_longitude')
                row_reasons['ais_position_longitude'] = 'longitude outside [-180, 180]'
                flagged_cells += 1

        # Rule: speed < 0 and != -1 (-1 = unknown)
        speed = safe_float(row.get('ais_position_speed'))
        if speed is not None and speed < 0 and speed != -1:
            if 'ais_position_speed' in row:
                raw_speed = strip_mark(row.get('ais_position_speed'))
                if not is_marked(row.get('ais_position_speed')):
                    row['ais_position_speed'] = mark(row['ais_position_speed'])
                row_flagged_columns.add('ais_position_speed')
                row_reasons['ais_position_speed'] = 'speed < 0 and != -1'
                flagged_cells += 1

        # Rule: course < 0 or course > 360, and != -1 (-1 = unknown)
        course = safe_float(row.get('ais_position_course'))
        if course is not None and course != -1 and (course < 0 or course > 360):
            if 'ais_position_course' in row:
                raw_course = strip_mark(row.get('ais_position_course'))
                if not is_marked(row.get('ais_position_course')):
                    row['ais_position_course'] = mark(row['ais_position_course'])
                row_flagged_columns.add('ais_position_course')
                row_reasons['ais_position_course'] = 'course < 0 or course > 360 and != -1'
                flagged_cells += 1

        # Rule: latitude == 0 AND longitude == 0 -> flag both
        lat = safe_float(row.get('ais_position_latitude'))
        lon = safe_float(row.get('ais_position_longitude'))
        if lat is not None and lon is not None and lat == 0 and lon == 0:
            if 'ais_position_latitude' in row:
                raw_lat = strip_mark(row.get('ais_position_latitude'))
                if not is_marked(row.get('ais_position_latitude')):
                    row['ais_position_latitude'] = mark(row['ais_position_latitude'])
                row_flagged_columns.add('ais_position_latitude')
                row_reasons['ais_position_latitude'] = 'latitude == 0 AND longitude == 0'
                flagged_cells += 1
            if 'ais_position_longitude' in row:
                raw_lon = strip_mark(row.get('ais_position_longitude'))
                if not is_marked(row.get('ais_position_longitude')):
                    row['ais_position_longitude'] = mark(row['ais_position_longitude'])
                row_flagged_columns.add('ais_position_longitude')
                row_reasons['ais_position_longitude'] = 'latitude == 0 AND longitude == 0'
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

    # Collect all CSV files from all resolved position directories
    position_files = sorted(
        glob.glob(os.path.join(d, '*.csv')) for d in POSITION_DIRS
    )
    position_files = [f for sublist in position_files for f in sublist]

    # Collect all unique fieldnames across all files for the report
    all_fieldnames = _collect_all_fieldnames(position_files)

    # Open report file for real-time writing
    report_path = os.path.join(APP_ROOT, 'flaggedpositioncells.csv')
    report_file = open(report_path, 'w', newline='', encoding='utf-8')
    report_writer = csv.writer(report_file)
    report_writer.writerow([
        'file', 'filepath', 'row_index', 'flagged_column_count', 'flagged_columns',
        'flagged_reasons',
    ] + all_fieldnames)
    report_file.flush()
    print(f'Writing flagged rows report in real-time to: {report_path}')
    print()

    # Position info (skip non-CSV files like 'haha')
    for filepath in position_files:
        rows, flagged = clean_position_file(filepath, all_fieldnames, report_writer, report_file)
        total_files += 1
        total_rows += rows
        total_flagged += flagged
        print(f'[POSITION] {os.path.basename(filepath)}: {rows} rows, {flagged} cells flagged')

    print(f'\nTotal: {total_files} files, {total_rows} rows, {total_flagged} cells flagged')

    row_count = sum(1 for _ in open(report_path))
    report_file.close()
    print(f'\nFlagged rows report completed: {report_path} ({row_count - 1} rows flagged, {total_flagged} total cells flagged)')


if __name__ == '__main__':
    main()