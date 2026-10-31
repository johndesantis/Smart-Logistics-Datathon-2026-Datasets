#!/usr/bin/env python3
"""Clean AIS 2024 and 2025 datasets in place.

Flags (marks) disrespectancies without removing any data.
Flagged cells are prefixed with [BAD].

Captain info rules:
  - ais_capts_length == 0 AND ais_capts_width == 0 -> flag both
  - ais_capts_callsign purely numeric (no letters) -> flag
  - ais_capts_imo == 0 -> flag
  - ais_capts_draft <= 0 -> flag

Captain info acceptable (NOT flagged):
  - ais_capts_trans_x == 0 AND ais_capts_trans_y == 0

Position info rules:
  - latitude outside [-90, 90] -> flag
  - longitude outside [-180, 180] -> flag
  - speed < 0 and speed != -1 -> flag (-1 = unknown)
  - course < 0 or course > 360, and course != -1 -> flag (-1 = unknown)

Position info acceptable (NOT flagged):
  - speed == 0 (stopped vessel)
  - course == 0 (valid heading north)
  - speed > 0.5, course > 0 within valid ranges
"""

import csv
import os
import re
import glob
import itertools

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
APP_ROOT = os.path.dirname(SCRIPT_DIR)

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

CAPTAIN_DIRS = []
POSITION_DIRS = []

# Add directories from /home/haha/Downloads if they exist
ADDITIONAL_PATHS = [
    # 2024
    ("/home/haha/Downloads/3-2. AIS Data/2024 Data/captain info/2024", 
     "/home/haha/Downloads/3-2. AIS Data/2024 Data/position info/2024"),
    # 2025
    ("/home/haha/Downloads/3-2. AIS Data/2025 Data/captain info 2025", 
     "/home/haha/Downloads/3-2. AIS Data/2025 Data/position info 2025"),
]

for cd, pd in ADDITIONAL_PATHS:
    if os.path.exists(cd):
        CAPTAIN_DIRS.append(cd)
    if os.path.exists(pd):
        POSITION_DIRS.append(pd)

for year in ('2024', '2025'):
    cd, pd = _resolve_data_dirs(year)
    if cd and os.path.exists(cd):
        CAPTAIN_DIRS.append(cd)
    if pd and os.path.exists(pd):
        POSITION_DIRS.append(pd)

# Backwards-compatible single-directory constants (first match)
CAPTAIN_DIR = CAPTAIN_DIRS[0] if CAPTAIN_DIRS else os.path.join(APP_ROOT, 'AIS 2025', 'captain info')
POSITION_DIR = POSITION_DIRS[0] if POSITION_DIRS else os.path.join(APP_ROOT, 'AIS 2025', 'position info')

CALLSIGN_NUMERIC_RE = re.compile(r'^[0-9]+$')

def is_marked(value):
    return value is not None and str(value).startswith('[BAD]')

def mark(value):
    if value is None:
        return value
    s = str(value)
    if s.startswith('[BAD]'):
        return s
    return '[BAD]' + s

def safe_float(value):
    if value is None or value == '':
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None

def clean_captain_file(filepath):
    with open(filepath, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        if fieldnames is None:
            return 0, 0
        # Filter out None fieldnames
        fieldnames = [fn for fn in fieldnames if fn is not None]
        rows = list(reader)

    flagged_cells = 0
    for row in rows:
        # Remove None keys if any
        row = {k: v for k, v in row.items() if k is not None}
        # Rule: length == 0 AND width == 0
        length = safe_float(row.get('ais_capts_length'))
        width = safe_float(row.get('ais_capts_width'))
        if length is not None and width is not None and length == 0 and width == 0:
            if 'ais_capts_length' in row and not is_marked(row['ais_capts_length']):
                row['ais_capts_length'] = mark(row['ais_capts_length'])
                flagged_cells += 1
            if 'ais_capts_width' in row and not is_marked(row['ais_capts_width']):
                row['ais_capts_width'] = mark(row['ais_capts_width'])
                flagged_cells += 1

        # Rule: callsign purely numeric
        callsign = row.get('ais_capts_callsign') or ''
        if callsign and CALLSIGN_NUMERIC_RE.match(callsign) and not is_marked(row.get('ais_capts_callsign')):
            row['ais_capts_callsign'] = mark(row['ais_capts_callsign'])
            flagged_cells += 1

        # Rule: imo == 0
        imo = safe_float(row.get('ais_capts_imo'))
        if imo is not None and imo == 0 and not is_marked(row.get('ais_capts_imo')):
            row['ais_capts_imo'] = mark(row['ais_capts_imo'])
            flagged_cells += 1

        # Rule: draft <= 0 -> unacceptable
        draft = safe_float(row.get('ais_capts_draft'))
        if draft is not None and draft <= 0 and not is_marked(row.get('ais_capts_draft')):
            row['ais_capts_draft'] = mark(row['ais_capts_draft'])
            flagged_cells += 1

    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator='\n', extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)

    return len(rows), flagged_cells

def clean_position_file(filepath):
    with open(filepath, 'r', newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        if fieldnames is None:
            return 0, 0
        fieldnames = [fn for fn in fieldnames if fn is not None]
        rows = list(reader)

    flagged_cells = 0
    for row in rows:
        row = {k: v for k, v in row.items() if k is not None}
        # Rule: latitude outside [-90, 90]
        lat = safe_float(row.get('ais_position_latitude'))
        if lat is not None and (lat < -90 or lat > 90):
            if 'ais_position_latitude' in row and not is_marked(row['ais_position_latitude']):
                row['ais_position_latitude'] = mark(row['ais_position_latitude'])
                flagged_cells += 1

        # Rule: longitude outside [-180, 180]
        lon = safe_float(row.get('ais_position_longitude'))
        if lon is not None and (lon < -180 or lon > 180):
            if 'ais_position_longitude' in row and not is_marked(row['ais_position_longitude']):
                row['ais_position_longitude'] = mark(row['ais_position_longitude'])
                flagged_cells += 1

        # Rule: speed < 0 and != -1 (-1 = unknown)
        speed = safe_float(row.get('ais_position_speed'))
        if speed is not None and speed < 0 and speed != -1:
            if 'ais_position_speed' in row and not is_marked(row['ais_position_speed']):
                row['ais_position_speed'] = mark(row['ais_position_speed'])
                flagged_cells += 1

        # Rule: course < 0 or course > 360, and != -1 (-1 = unknown)
        course = safe_float(row.get('ais_position_course'))
        if course is not None and course != -1 and (course < 0 or course > 360):
            if 'ais_position_course' in row and not is_marked(row['ais_position_course']):
                row['ais_position_course'] = mark(row['ais_position_course'])
                flagged_cells += 1

    with open(filepath, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator='\n', extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)

    return len(rows), flagged_cells

def main():
    total_files = 0
    total_rows = 0
    total_flagged = 0

    # Collect all CSV files from all resolved captain directories
    captain_files = sorted(itertools.chain.from_iterable(
        glob.glob(os.path.join(d, '*.csv')) for d in CAPTAIN_DIRS
    ))

    # Captain info (all resolved directories)
    for filepath in captain_files:
        rows, flagged = clean_captain_file(filepath)
        total_files += 1
        total_rows += rows
        total_flagged += flagged
        print(f'[CAPTAIN] {os.path.basename(filepath)}: {rows} rows, {flagged} cells flagged')

    # Collect all CSV files from all resolved position directories
    position_files = sorted(itertools.chain.from_iterable(
        glob.glob(os.path.join(d, '*.csv')) for d in POSITION_DIRS
    ))

    # Position info (skip non-CSV files like 'haha')
    for filepath in position_files:
        rows, flagged = clean_position_file(filepath)
        total_files += 1
        total_rows += rows
        total_flagged += flagged
        print(f'[POSITION] {os.path.basename(filepath)}: {rows} rows, {flagged} cells flagged')

    print(f'\nTotal: {total_files} files, {total_rows} rows, {total_flagged} cells flagged')

if __name__ == '__main__':
    main()