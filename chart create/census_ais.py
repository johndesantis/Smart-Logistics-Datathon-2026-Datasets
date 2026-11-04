#!/usr/bin/env python3
"""
Deterministic raw-data census on AIS datasets.
Performs tasks 1-8 as specified.
"""
import os
import re
import csv
import json
import time
import glob
import subprocess
import multiprocessing as mp
from datetime import datetime
from collections import defaultdict
from functools import partial

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DATA_DIRS = {
    "captain_2024": "/home/haha/Downloads/3-2. AIS Data/2024 Data/captain info/2024/",
    "position_2024": "/home/haha/Downloads/3-2. AIS Data/2024 Data/position info/2024/",
    "captain_2025": "/home/haha/Downloads/3-2. AIS Data/2025 Data/captain info 2025/",
    "position_2025": "/home/haha/Downloads/3-2. AIS Data/2025 Data/position info 2025/",
}

OUTPUT_DIR = "/home/haha/Downloads/analysis_output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Regex patterns
CAPTAIN_FILE_RE = re.compile(r"capts-(\d{8})T(\d{6})Z\.csv$")
POSITION_FILE_RE = re.compile(r"positions-(\d{8})T(\d{6})Z\.csv$")

ISO_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
US_TS_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{2} \d{1,2}:\d{2}(:\d{2})?$")

# Column indices (0-based) for position files
POS_MMSI_COL = 2       # ais_position_mmsi
POS_TS_COL = 3          # ais_position_timestamp
POS_LAT_COL = 4         # ais_position_latitude
POS_LON_COL = 5         # ais_position_longitude

# Column indices for captain files
CAPT_MMSI_COL = 3   # ais_capts_mmsi
CAPT_SHIP_ID_COL = 1 # ais_ship_id
CAPT_ETA_COL = 12    # ais_capts_eta


def count_files_and_lines(data_dir, prefix_pattern):
    """Count CSV files (excluding .~lock) and total data rows using wc -l."""
    # Get all csv files
    all_files = glob.glob(os.path.join(data_dir, prefix_pattern))
    # Exclude .~lock files
    csv_files = [f for f in all_files if not os.path.basename(f).startswith(".~lock")]
    file_count = len(csv_files)

    if file_count == 0:
        return {"files": 0, "total_lines": 0, "data_rows": 0}

    # Use wc -l for speed via subprocess with xargs parallel
    result = subprocess.run(
        ["bash", "-c", f"find '{data_dir}' -name '{prefix_pattern}' ! -name '.~lock*' -print0 | "
                         f"xargs -0 -P8 wc -l"],
        capture_output=True, text=True
    )
    # Parse wc -l output: total lines = sum of per-file counts, but last line is "total"
    # Actually the "total" line appears when multiple files are passed; but with xargs -P8
    # each invocation of wc gets a batch, so we get multiple "total" lines.
    # Better: just sum up individual file line counts
    total_lines = 0
    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        # Each line is: count filename  OR  "total filename1 filename2 ..."
        parts = line.split(None, 1)
        if len(parts) == 2:
            try:
                count = int(parts[0])
                fname = parts[1]
                if fname == "total":
                    # This is a total line from multi-file wc; the count is already part of individual lines
                    continue
                # It's an individual file line
                total_lines += count
            except ValueError:
                pass

    data_rows = total_lines - file_count  # subtract header rows
    return {"files": file_count, "total_lines": total_lines, "data_rows": data_rows}


def scan_position_coords_worker(args):
    """Worker to scan a single position file for coordinate validity."""
    filepath, = args
    valid = 0
    invalid = 0
    zero_zero = 0
    error = None
    try:
        with open(filepath, 'r', newline='', errors='replace') as f:
            reader = csv.reader(f)
            header = next(reader, None)
            for row in reader:
                lat_raw = row[POS_LAT_COL] if len(row) > POS_LAT_COL else ""
                lon_raw = row[POS_LON_COL] if len(row) > POS_LON_COL else ""

                # Strip [BAD] prefix
                lat_str = lat_raw.replace("[BAD]", "").strip()
                lon_str = lon_raw.replace("[BAD]", "").strip()

                lat_valid = False
                lon_valid = False
                try:
                    lat = float(lat_str)
                    lat_valid = -90 <= lat <= 90
                except (ValueError, TypeError):
                    pass
                try:
                    lon = float(lon_str)
                    lon_valid = -180 <= lon <= 180
                except (ValueError, TypeError):
                    pass

                if lat_valid and lon_valid:
                    valid += 1
                    # Check lat==0 AND lon==0
                    if lat == 0.0 and lon == 0.0:
                        zero_zero += 1
                else:
                    invalid += 1
    except Exception as e:
        error = str(e)

    filesize = os.path.getsize(filepath)
    return {"valid": valid, "invalid": invalid, "zero_zero": zero_zero, "bytes": filesize, "error": error}


def scan_position_coords_all(data_dir):
    """Full scan of ALL position files for coordinate validity."""
    all_files = glob.glob(os.path.join(data_dir, "positions-*.csv"))
    csv_files = [f for f in all_files if not os.path.basename(f).startswith(".~lock")]

    num_procs = min(8, os.cpu_count() or 4)
    start_time = time.time()

    with mp.Pool(processes=num_procs) as pool:
        results = pool.map(scan_position_coords_worker, [(f,) for f in csv_files])

    elapsed = time.time() - start_time

    total_valid = sum(r["valid"] for r in results)
    total_invalid = sum(r["invalid"] for r in results)
    total_zero_zero = sum(r["zero_zero"] for r in results)
    total_bytes = sum(r["bytes"] for r in results)
    errors = [r["error"] for r in results if r["error"]]

    return {
        "files_scanned": len(csv_files),
        "valid_coordinate_rows": total_valid,
        "invalid_unparsable_rows": total_invalid,
        "zero_zero_rows": total_zero_zero,
        "total_bytes_scanned": total_bytes,
        "elapsed_seconds": round(elapsed, 2),
        "errors": errors,
    }


def get_daily_last_files(data_dir, file_re, prefix):
    """For each UTC day (YYYYMMDD), find the last snapshot file of that day."""
    all_files = glob.glob(os.path.join(data_dir, prefix))
    csv_files = [f for f in all_files if not os.path.basename(f).startswith(".~lock")]

    day_to_files = defaultdict(list)
    for fpath in csv_files:
        fname = os.path.basename(fpath)
        m = file_re.search(fname)
        if m:
            date_str = m.group(1)
            time_str = m.group(2)
            day_to_files[date_str].append((time_str, fpath))

    daily_last = []
    for date_str in sorted(day_to_files.keys()):
        files = sorted(day_to_files[date_str], key=lambda x: x[0])
        daily_last.append(files[-1][1])  # last file by time

    return daily_last, len(daily_last)


def read_mmsi_from_file(filepath, col_idx):
    """Read MMSI values from a CSV file (column col_idx, 0-based)."""
    mmsis = set()
    try:
        with open(filepath, 'r', newline='', errors='replace') as f:
            reader = csv.reader(f)
            next(reader, None)  # skip header
            for row in reader:
                if len(row) > col_idx:
                    val = row[col_idx].strip()
                    # Strip [BAD] prefix
                    val = val.replace("[BAD]", "").strip()
                    if val:
                        mmsis.add(val)
    except Exception:
        pass
    return mmsis


def compute_jaccard(set_a, set_b):
    """Compute Jaccard similarity between two sets."""
    if not set_a and not set_b:
        return 1.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    if union == 0:
        return 1.0
    return intersection / union


def get_consecutive_pairs(daily_files, file_re, minutes_apart=15):
    """Find 3 pairs of consecutive snapshots that are ~15 min apart."""
    # Parse all files with timestamps
    parsed = []
    for fpath in daily_files:
        fname = os.path.basename(fpath)
        m = file_re.search(fname)
        if m:
            date_str = m.group(1)
            time_str = m.group(2)
            dt_str = date_str + time_str
            dt = datetime.strptime(dt_str, "%Y%m%d%H%M%S")
            parsed.append((dt, fpath))

    parsed.sort(key=lambda x: x[0])

    # Find pairs close to 15 min apart
    pairs = []
    for i in range(len(parsed) - 1):
        dt1, f1 = parsed[i]
        dt2, f2 = parsed[i + 1]
        diff_minutes = (dt2 - dt1).total_seconds() / 60.0
        if abs(diff_minutes - minutes_apart) < 1.0:
            pairs.append((f1, f2))
            if len(pairs) >= 3:
                break
    return pairs


def scan_timestamp_format_worker(args):
    """Worker to count timestamp formats in a position file."""
    filepath, = args
    iso_count = 0
    us_count = 0
    other_count = 0
    try:
        with open(filepath, 'r', newline='', errors='replace') as f:
            reader = csv.reader(f)
            next(reader, None)
            for row in reader:
                ts_raw = row[POS_TS_COL] if len(row) > POS_TS_COL else ""
                ts = ts_raw.strip()
                if ISO_TS_RE.match(ts):
                    iso_count += 1
                elif US_TS_RE.match(ts):
                    us_count += 1
                else:
                    other_count += 1
    except Exception:
        pass
    return {"iso": iso_count, "us": us_count, "other": other_count}


def scan_timestamp_formats_daily_last(daily_files):
    """Census timestamp formats from daily-last position files."""
    num_procs = min(8, os.cpu_count() or 4)
    with mp.Pool(processes=num_procs) as pool:
        results = pool.map(scan_timestamp_format_worker, [(f,) for f in daily_files])

    total_iso = sum(r["iso"] for r in results)
    total_us = sum(r["us"] for r in results)
    total_other = sum(r["other"] for r in results)
    return {"iso": total_iso, "us": total_us, "other": total_other}


def scan_captain_eta_daily_last(daily_files):
    """Count unparseable ais_capts_eta values in daily-last captain files."""
    total_unparseable = 0
    total_rows = 0
    for fpath in daily_files:
        try:
            with open(fpath, 'r', newline='', errors='replace') as f:
                reader = csv.reader(f)
                next(reader, None)
                for row in reader:
                    total_rows += 1
                    eta_raw = row[CAPT_ETA_COL] if len(row) > CAPT_ETA_COL else ""
                    eta = eta_raw.strip()
                    # Unparseable: "0000-00-00 00:00:00" or empty
                    if eta == "" or eta == "0000-00-00 00:00:00" or not ISO_TS_RE.match(eta):
                        total_unparseable += 1
        except Exception:
            pass
    return {"total_rows": total_rows, "unparseable_eta": total_unparseable}


def extract_base_layer(daily_files, output_file):
    """Extract all rows with valid coordinates into base_layer_sample.csv."""
    row_count = 0
    total_bytes_scanned = 0
    with open(output_file, 'w', newline='') as out_f:
        writer = csv.writer(out_f)
        writer.writerow(["year", "latitude", "longitude"])
        for fpath in daily_files:
            year = "2024" if "2024" in fpath else "2025"
            total_bytes_scanned += os.path.getsize(fpath)
            try:
                with open(fpath, 'r', newline='', errors='replace') as f:
                    reader = csv.reader(f)
                    next(reader, None)
                    for row in reader:
                        lat_raw = row[POS_LAT_COL] if len(row) > POS_LAT_COL else ""
                        lon_raw = row[POS_LON_COL] if len(row) > POS_LON_COL else ""
                        lat_str = lat_raw.replace("[BAD]", "").strip()
                        lon_str = lon_raw.replace("[BAD]", "").strip()
                        try:
                            lat = float(lat_str)
                            lon = float(lon_str)
                            if -90 <= lat <= 90 and -180 <= lon <= 180:
                                writer.writerow([year, f"{lat}", f"{lon}"])
                                row_count += 1
                        except (ValueError, TypeError):
                            pass
            except Exception:
                pass
    return {"rows": row_count, "bytes_scanned": total_bytes_scanned}


def downsample_csv(input_file, output_file, step=10):
    """Keep every nth row from a CSV file (skipping header in count)."""
    row_count = 0
    with open(input_file, 'r', newline='') as in_f:
        reader = csv.reader(in_f)
        header = next(reader)
        with open(output_file, 'w', newline='') as out_f:
            writer = csv.writer(out_f)
            writer.writerow(header)
            for i, row in enumerate(reader):
                if i % step == 0:
                    writer.writerow(row)
                    row_count += 1
    return row_count


def get_bytes_dir(data_dir):
    """Get total bytes in a directory using du."""
    result = subprocess.run(
        ["du", "-sb", data_dir],
        capture_output=True, text=True
    )
    parts = result.stdout.strip().split()
    if parts:
        return int(parts[0])
    return 0


def main():
    methodology_lines = []

    def log_method(msg):
        methodology_lines.append(msg)
        print(msg)

    log_method(f"Census started at {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")

    all_results = {}

    # -----------------------------------------------------------------------
    # TASK 1 & 2: File counts and total row counts
    # -----------------------------------------------------------------------
    log_method("=== TASK 1 & 2: File counts and row counts ===")

    for name, dirpath in DATA_DIRS.items():
        prefix = "capts-*.csv" if "captain" in name else "positions-*.csv"
        # Use parallel wc -l
        all_files = glob.glob(os.path.join(dirpath, prefix))
        csv_files = [f for f in all_files if not os.path.basename(f).startswith(".~lock")]
        file_count = len(csv_files)

        # Get directory size
        dir_bytes = get_bytes_dir(dirpath)

        result = {
            "files": file_count,
            "directory_bytes": dir_bytes,
        }

        # Get byte sizes and line counts
        start = time.time()
        line_result = count_files_and_lines(dirpath, prefix)
        elapsed_lines = time.time() - start

        result["total_lines"] = line_result["total_lines"]
        result["data_rows"] = line_result["data_rows"]
        result["line_count_elapsed_seconds"] = round(elapsed_lines, 2)

        all_results[name] = result
        log_method(f"{name}: files={file_count}, total_lines={line_result['total_lines']}, "
                    f"data_rows={line_result['data_rows']}, dir_bytes={dir_bytes}")

    # -----------------------------------------------------------------------
    # TASK 3: Invalid coordinate scan (full scan of ALL position files)
    # -----------------------------------------------------------------------
    log_method("\n=== TASK 3: Invalid coordinate scan (full scan, all position files) ===")

    pos_2024_results = scan_position_coords_all(DATA_DIRS["position_2024"])
    pos_2025_results = scan_position_coords_all(DATA_DIRS["position_2025"])

    all_results["position_2024_coords"] = pos_2024_results
    all_results["position_2025_coords"] = pos_2025_results

    log_method(f"2024 positions: valid={pos_2024_results['valid_coordinate_rows']}, "
                f"invalid={pos_2024_results['invalid_unparsable_rows']}, "
                f"zero_zero={pos_2024_results['zero_zero_rows']}, "
                f"bytes={pos_2024_results['total_bytes_scanned']}, "
                f"time={pos_2024_results['elapsed_seconds']}s")
    log_method(f"2025 positions: valid={pos_2025_results['valid_coordinate_rows']}, "
                f"invalid={pos_2025_results['invalid_unparsable_rows']}, "
                f"zero_zero={pos_2025_results['zero_zero_rows']}, "
                f"bytes={pos_2025_results['total_bytes_scanned']}, "
                f"time={pos_2025_results['elapsed_seconds']}s")

    # -----------------------------------------------------------------------
    # TASK 6: Daily-last snapshot index
    # -----------------------------------------------------------------------
    log_method("\n=== TASK 6: Daily-last snapshot index ===")

    daily_captain_2024, days_2024_cap = get_daily_last_files(
        DATA_DIRS["captain_2024"], CAPTAIN_FILE_RE, "capts-*.csv")
    daily_captain_2025, days_2025_cap = get_daily_last_files(
        DATA_DIRS["captain_2025"], CAPTAIN_FILE_RE, "capts-*.csv")
    daily_position_2024, days_2024_pos = get_daily_last_files(
        DATA_DIRS["position_2024"], POSITION_FILE_RE, "positions-*.csv")
    daily_position_2025, days_2025_pos = get_daily_last_files(
        DATA_DIRS["position_2025"], POSITION_FILE_RE, "positions-*.csv")

    # Write index files
    with open(os.path.join(OUTPUT_DIR, "daily_last_captain_2024.txt"), 'w') as f:
        for fp in daily_captain_2024:
            f.write(fp + "\n")
    with open(os.path.join(OUTPUT_DIR, "daily_last_captain_2025.txt"), 'w') as f:
        for fp in daily_captain_2025:
            f.write(fp + "\n")
    with open(os.path.join(OUTPUT_DIR, "daily_last_position_2024.txt"), 'w') as f:
        for fp in daily_position_2024:
            f.write(fp + "\n")
    with open(os.path.join(OUTPUT_DIR, "daily_last_position_2025.txt"), 'w') as f:
        for fp in daily_position_2025:
            f.write(fp + "\n")

    # Determine min/max dates
    def get_min_max(daily_files, file_re):
        dates = []
        for fpath in daily_files:
            fname = os.path.basename(fpath)
            m = file_re.search(fname)
            if m:
                dates.append(m.group(1))
        if dates:
            return min(dates), max(dates)
        return None, None

    min_d_cap24, max_d_cap24 = get_min_max(daily_captain_2024, CAPTAIN_FILE_RE)
    min_d_cap25, max_d_cap25 = get_min_max(daily_captain_2025, CAPTAIN_FILE_RE)
    min_d_pos24, max_d_pos24 = get_min_max(daily_position_2024, POSITION_FILE_RE)
    min_d_pos25, max_d_pos25 = get_min_max(daily_position_2025, POSITION_FILE_RE)

    all_results["daily_last_index"] = {
        "captain_2024": {"days": days_2024_cap, "min_date": min_d_cap24, "max_date": max_d_cap24},
        "captain_2025": {"days": days_2025_cap, "min_date": min_d_cap25, "max_date": max_d_cap25},
        "position_2024": {"days": days_2024_pos, "min_date": min_d_pos24, "max_date": max_d_pos24},
        "position_2025": {"days": days_2025_pos, "min_date": min_d_pos25, "max_date": max_d_pos25},
    }

    log_method(f"Captain 2024: {days_2024_cap} days, {min_d_cap24} to {max_d_cap24}")
    log_method(f"Captain 2025: {days_2025_cap} days, {min_d_cap25} to {max_d_cap25}")
    log_method(f"Position 2024: {days_2024_pos} days, {min_d_pos24} to {max_d_pos24}")
    log_method(f"Position 2025: {days_2025_pos} days, {min_d_pos25} to {max_d_pos25}")

    # -----------------------------------------------------------------------
    # TASK 4: Distinct vessels from daily-last captain snapshots
    # -----------------------------------------------------------------------
    log_method("\n=== TASK 4: Distinct vessels (daily-last captain sample) ===")

    def distinct_vessels(daily_files, year):
        mmsi_set = set()
        ship_id_set = set()
        for fpath in daily_files:
            try:
                with open(fpath, 'r', newline='', errors='replace') as f:
                    reader = csv.reader(f)
                    next(reader, None)
                    for row in reader:
                        if len(row) > CAPT_MMSI_COL:
                            mmsi = row[CAPT_MMSI_COL].replace("[BAD]", "").strip()
                            if mmsi:
                                mmsi_set.add(mmsi)
                        if len(row) > CAPT_SHIP_ID_COL:
                            sid = row[CAPT_SHIP_ID_COL].replace("[BAD]", "").strip()
                            if sid:
                                ship_id_set.add(sid)
            except Exception:
                pass
        union_set = mmsi_set | ship_id_set
        return {
            "distinct_mmsi": len(mmsi_set),
            "distinct_ship_id": len(ship_id_set),
            "union": len(union_set),
            "year": year,
        }

    cap_2024_vessels = distinct_vessels(daily_captain_2024, 2024)
    cap_2025_vessels = distinct_vessels(daily_captain_2025, 2025)

    all_results["distinct_vessels"] = {
        "captain_2024": cap_2024_vessels,
        "captain_2025": cap_2025_vessels,
        "note": "Fleet-census sample: union of distinct ais_capts_mmsi AND distinct ais_ship_id across daily-last captain snapshots."
    }

    log_method(f"2024: distinct MMSI={cap_2024_vessels['distinct_mmsi']}, "
                f"distinct ship_id={cap_2024_vessels['distinct_ship_id']}, "
                f"union={cap_2024_vessels['union']}")
    log_method(f"2025: distinct MMSI={cap_2025_vessels['distinct_mmsi']}, "
                f"distinct ship_id={cap_2025_vessels['distinct_ship_id']}, "
                f"union={cap_2025_vessels['union']}")

    # -----------------------------------------------------------------------
    # TASK 5: Fleet completeness verification (Jaccard similarity)
    # -----------------------------------------------------------------------
    log_method("\n=== TASK 5: Fleet completeness verification (Jaccard similarity) ===")

    def fleet_completeness_check(daily_captain_files, file_re, year):
        # Parse timestamps and find 15-min consecutive pairs
        parsed = []
        for fpath in daily_captain_files:
            fname = os.path.basename(fpath)
            m = file_re.search(fname)
            if m:
                date_str = m.group(1)
                time_str = m.group(2)
                dt = datetime.strptime(date_str + time_str, "%Y%m%d%H%M%S")
                parsed.append((dt, fpath))
        parsed.sort(key=lambda x: x[0])

        pairs = []
        for i in range(len(parsed) - 1):
            dt1, f1 = parsed[i]
            dt2, f2 = parsed[i + 1]
            diff_min = (dt2 - dt1).total_seconds() / 60.0
            if abs(diff_min - 15) < 1.0:
                pairs.append((f1, f2))
                if len(pairs) >= 3:
                    break

        jacciards = []
        pair_details = []
        for f1, f2 in pairs:
            mmsi1 = read_mmsi_from_file(f1, CAPT_MMSI_COL)
            mmsi2 = read_mmsi_from_file(f2, CAPT_MMSI_COL)
            jac = compute_jaccard(mmsi1, mmsi2)
            jacciards.append(jac)
            pair_details.append({
                "file1": f1, "file2": f2,
                "mmsi1_count": len(mmsi1), "mmsi2_count": len(mmsi2),
                "jaccard": jac,
            })
        return {"jaccard_similarities": jacciards, "pair_details": pair_details}

    fc_2024 = fleet_completeness_check(daily_captain_2024, CAPTAIN_FILE_RE, 2024)
    fc_2025 = fleet_completeness_check(daily_captain_2025, CAPTAIN_FILE_RE, 2025)

    all_results["fleet_completeness"] = {
        "captain_2024": fc_2024,
        "captain_2025": fc_2025,
        "threshold": 0.95,
    }

    log_method(f"2024 Jaccard similarities: {[round(j, 4) for j in fc_2024['jaccard_similarities']]}")
    log_method(f"2025 Jaccard similarities: {[round(j, 4) for j in fc_2025['jaccard_similarities']]}")

    # -----------------------------------------------------------------------
    # TASK 7: Base layer sample
    # -----------------------------------------------------------------------
    log_method("\n=== TASK 7: Base layer sample ===")

    base_layer_file = os.path.join(OUTPUT_DIR, "base_layer_sample.csv")
    downsampled_file = os.path.join(OUTPUT_DIR, "base_layer_sample_downsampled.csv")

    all_daily_pos = daily_position_2024 + daily_position_2025

    start_extract = time.time()
    extract_result = extract_base_layer(all_daily_pos, base_layer_file)
    elapsed_extract = time.time() - start_extract

    log_method(f"Base layer extracted: {extract_result['rows']} rows in {elapsed_extract:.1f}s")

    start_downsample = time.time()
    downsample_count = downsample_csv(base_layer_file, downsampled_file, step=10)
    elapsed_downsample = time.time() - start_downsample

    log_method(f"Downsampled (every 10th): {downsample_count} rows in {elapsed_downsample:.1f}s")

    all_results["base_layer_sample"] = {
        "input_files": len(all_daily_pos),
        "full_row_count": extract_result["rows"],
        "full_output_file": base_layer_file,
        "downsample_interval": 10,
        "downsampled_row_count": downsample_count,
        "downsampled_output_file": downsampled_file,
        "extract_elapsed_seconds": round(elapsed_extract, 2),
        "downsample_elapsed_seconds": round(elapsed_downsample, 2),
    }

    # -----------------------------------------------------------------------
    # TASK 8: Timestamp format census
    # -----------------------------------------------------------------------
    log_method("\n=== TASK 8: Timestamp format census ===")

    ts_2024 = scan_timestamp_formats_daily_last(daily_position_2024)
    ts_2025 = scan_timestamp_formats_daily_last(daily_position_2025)

    log_method(f"2024 positions (daily-last): ISO={ts_2024['iso']}, US={ts_2024['us']}, other={ts_2024['other']}")
    log_method(f"2025 positions (daily-last): ISO={ts_2025['iso']}, US={ts_2025['us']}, other={ts_2025['other']}")

    eta_2024 = scan_captain_eta_daily_last(daily_captain_2024)
    eta_2025 = scan_captain_eta_daily_last(daily_captain_2025)

    log_method(f"2024 captains ETA (daily-last): total={eta_2024['total_rows']}, unparseable={eta_2024['unparseable_eta']}")
    log_method(f"2025 captains ETA (daily-last): total={eta_2025['total_rows']}, unparseable={eta_2025['unparseable_eta']}")

    all_results["timestamp_census"] = {
        "position_2024": ts_2024,
        "position_2025": ts_2025,
        "captain_2024_eta": eta_2024,
        "captain_2025_eta": eta_2025,
    }

    # -----------------------------------------------------------------------
    # Write outputs
    # -----------------------------------------------------------------------
    log_method("\n=== Writing outputs ===")

    with open(os.path.join(OUTPUT_DIR, "raw_census.json"), 'w') as f:
        json.dump(all_results, f, indent=2, default=str)

    with open(os.path.join(OUTPUT_DIR, "raw_census_methodology.txt"), 'w') as f:
        f.write("RAW-CENSUS METHODOLOGY & ASSUMPTIONS\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"Run started: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n\n")
        f.write("DATA PATHS:\n")
        for name, path in DATA_DIRS.items():
            f.write(f"  {name}: {path}\n")
        f.write("\n")
        f.write("TASK 1 & 2: File counts and row counts\n")
        f.write("  - File count: glob for prefix pattern, exclude .~lock* files\n")
        f.write("  - Line count: find ... -print0 | xargs -0 -P8 wc -l (parallel)\n")
        f.write("  - Data rows = total_lines - file_count (one header per file)\n")
        f.write("  - Directory bytes: du -sb\n")
        f.write("\n")
        f.write("TASK 3: Invalid coordinate scan\n")
        f.write("  - Full scan of ALL position files (not a sample)\n")
        f.write("  - Strip [BAD] prefix from lat/lon fields\n")
        f.write("  - lat valid: float parseable AND -90 <= lat <= 90\n")
        f.write("  - lon valid: float parseable AND -180 <= lon <= 180\n")
        f.write("  - zero_zero: lat == 0.0 AND lon == 0.0 exactly\n")
        f.write("  - Parallelized with Python multiprocessing Pool (8 procs)\n")
        f.write("\n")
        f.write("TASK 4: Distinct vessels\n")
        f.write("  - Source: daily-last captain snapshots (see task 6)\n")
        f.write("  - Distinct ais_capts_mmsi (col 4, 0-indexed 3)\n")
        f.write("  - Distinct ais_ship_id (col 2, 0-indexed 1)\n")
        f.write("  - Union of both sets reported\n")
        f.write("  - NOTE: This is a fleet-census sample, not a full scan of all files.\n")
        f.write("\n")
        f.write("TASK 5: Fleet completeness\n")
        f.write("  - Picks 3 pairs of consecutive ~15-min snapshots from daily set\n")
        f.write("  - Jaccard similarity of MMSI sets within each pair\n")
        f.write("  - Threshold: > 0.95 supports near-full-fleet coverage\n")
        f.write("\n")
        f.write("TASK 6: Daily-last snapshot index\n")
        f.write("  - Filenames: capts-YYYYMMDDTHHMMSSZ.csv / positions-YYYYMMDDTHHMMSSZ.csv\n")
        f.write("  - For each YYYYMMDD, pick file with max time string\n")
        f.write("  - Output files: daily_last_captain_2024.txt, daily_last_captain_2025.txt,\n")
        f.write("    daily_last_position_2024.txt, daily_last_position_2025.txt\n")
        f.write("  - Min/max dates computed from filenames\n")
        f.write("\n")
        f.write("TASK 7: Base layer sample\n")
        f.write("  - Source: daily-last POSITION snapshots from both years\n")
        f.write("  - Extract all rows with valid coords (after stripping [BAD])\n")
        f.write("  - Columns: year, latitude, longitude\n")
        f.write("  - Downsample: every 10th row into base_layer_sample_downsampled.csv\n")
        f.write("\n")
        f.write("TASK 8: Timestamp format census\n")
        f.write("  - ISO format: matches ^YYYY-MM-DD HH:MM:SS\n")
        f.write("  - US format: matches ^M/D/YY H:MM or M/D/YY H:MM:SS\n")
        f.write("  - other/unparseable: anything else\n")
        f.write("  - ETA: unparseable if empty or '0000-00-00 00:00:00' or non-ISO\n")
        f.write("\n")
        f.write("ASSUMPTIONS:\n")
        f.write("  - Naive timestamps treated as UTC (documented assumption)\n")
        f.write("  - [BAD] prefix stripped before numeric parsing in all tasks\n")
        f.write("  - Header row is exactly 1 line per file (verified in samples)\n")
        f.write("  - .~lock* files excluded as they are LibreOffice lock files\n")
        f.write("\n")
        f.write("ELAPSED TIMES:\n")
        f.write(f"  Task 3 (coord scan, 2024): {pos_2024_results['elapsed_seconds']}s\n")
        f.write(f"  Task 3 (coord scan, 2025): {pos_2025_results['elapsed_seconds']}s\n")
        f.write(f"  Task 7 (base layer extract): {elapsed_extract:.2f}s\n")
        f.write(f"  Task 7 (downsample): {elapsed_downsample:.2f}s\n")
        f.write("\n" + "=" * 60 + "\n")
        f.write("Full structured results in raw_census.json\n")

        f.write("\n\n")
        f.write("\n".join(methodology_lines))

    print(f"\nAll outputs written to {OUTPUT_DIR}/")
    return all_results


if __name__ == "__main__":
    mp.set_start_method("fork", force=True)
    results = main()
