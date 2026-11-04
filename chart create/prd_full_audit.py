#!/usr/bin/env python3
"""Full PRD audit of AIS datasets for HK vs Shenzhen vs Guangzhou port comparison."""

import csv
import json
import math
import os
import re
from collections import defaultdict
from datetime import datetime, timezone

BASE = "/home/haha/Downloads"
AIS2024_CAPTS = os.path.join(BASE, "3-2. AIS Data", "2024 Data", "captain info", "2024")
AIS2024_POS = os.path.join(BASE, "3-2. AIS Data", "2024 Data", "position info", "2024")
AIS2025_CAPTS = os.path.join(BASE, "3-2. AIS Data", "2025 Data", "captain info 2025")
AIS2025_POS = os.path.join(BASE, "3-2. AIS Data", "2025 Data", "position info 2025")
FLAG_DIR = BASE
OUT_DIR = os.path.join(BASE, "analysis_output")
OUT_JSON = os.path.join(OUT_DIR, "prd_full_audit.json")

TERMINALS = {
    "HK": (22.30, 114.17),
    "Shekou": (22.48, 113.92),
    "Chiwan": (22.48, 113.90),
    "Yantian": (22.58, 114.28),
    "Nansha": (22.75, 113.60),
    "Guangzhou": (23.10, 113.30),
}
TERMINAL_PORT = {
    "HK": "Hong Kong",
    "Shekou": "Shenzhen",
    "Chiwan": "Shenzhen",
    "Yantian": "Shenzhen",
    "Nansha": "Guangzhou",
    "Guangzhou": "Guangzhou",
}
PORTS = ["Hong Kong", "Shenzhen", "Guangzhou"]
OUTER_LAT_MIN, OUTER_LAT_MAX = 21.8, 23.6
OUTER_LON_MIN, OUTER_LON_MAX = 112.9, 114.7
DIST_THRESHOLD = 0.30

OLD_BOXES = {
    "Hong Kong": ((22.05, 22.55), (113.80, 114.50)),
    "Shenzhen": ((22.55, 22.85), (113.80, 114.50)),
    "Guangzhou": ((22.60, 23.40), (113.10, 113.80)),
}


def strip_bad(s):
    if s is None:
        return ""
    s = str(s).strip()
    if s.startswith("[BAD]"):
        s = s[5:]
    return s


def parse_float(s):
    s = strip_bad(s)
    if s == "" or s.lower() == "nan":
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def parse_int(s):
    s = strip_bad(s)
    if s == "" or s.lower() == "nan":
        return None
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None


def parse_ts(s):
    """Parse a naive ISO-ish timestamp as UTC. Returns datetime or None."""
    if s is None:
        return None
    s = strip_bad(s).strip()
    if s == "" or s == "0000-00-00" or s.lower() == "nan":
        return None
    s = s.replace("Z", "").replace("z", "")
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
        "%m/%d/%y %H:%M",
        "%m/%d/%Y %H:%M:%S",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
    # try fromisoformat
    try:
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def list_csv_files(directory):
    """List CSV files excluding .~lock* files."""
    try:
        entries = os.listdir(directory)
    except FileNotFoundError:
        return []
    files = [f for f in entries if f.endswith(".csv") and not f.startswith(".~lock")]
    return sorted(files)


def get_daily_last_files(directory):
    """Return dict: date_str -> filepath, picking the last file per UTC day."""
    daily = {}
    ts_re = re.compile(r"(\d{8})T(\d{6})Z")
    for f in list_csv_files(directory):
        m = ts_re.search(f)
        if not m:
            continue
        date_str = m.group(1)
        time_str = m.group(2)
        if date_str not in daily or time_str > daily[date_str][0]:
            daily[date_str] = (time_str, os.path.join(directory, f))
    return {d: v[1] for d, v in sorted(daily.items())}


def count_lines_file(filepath):
    """Count lines in a file."""
    n = 0
    with open(filepath, "rb") as f:
        for line in f:
            n += 1
    return n


def read_csv_rows(filepath):
    """Yield dict rows from a CSV file."""
    with open(filepath, "r", newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for row in reader:
            yield row


# ============================
# PART 1 — Flagged file re-verification
# ============================
def part1():
    results = {}
    flagged_files = {
        "position2024": os.path.join(FLAG_DIR, "flaggedpositioncells2024.csv"),
        "position2025": os.path.join(FLAG_DIR, "flaggedpositioncells2025.csv"),
        "captain2024": os.path.join(FLAG_DIR, "flaggedcaptaincells2024.csv"),
        "captain2025": os.path.join(FLAG_DIR, "flaggedcaptaincells2025.csv"),
    }
    expected = {"position2024": 15, "position2025": 6, "captain2024": 89236, "captain2025": 28541}
    for key, path in flagged_files.items():
        # data row count
        n_lines = count_lines_file(path)
        n_data = max(n_lines - 1, 0)
        # dedup check by (mmsi, timestamp, source file)
        seen = set()
        dupes_removed = 0
        # Determine mmsi and timestamp column names from header
        with open(path, "r", newline="", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames or []
            # find mmsi col
            mmsi_col = None
            ts_col = None
            for fn in fieldnames:
                if fn in ("ais_capts_mmsi", "ais_position_mmsi"):
                    mmsi_col = fn
                if fn in ("ais_capts_last", "ais_position_timestamp"):
                    ts_col = fn
            for row in reader:
                mmsi = strip_bad(row.get(mmsi_col, "")) if mmsi_col else ""
                ts = strip_bad(row.get(ts_col, "")) if ts_col else ""
                src = strip_bad(row.get("file", ""))
                key_tuple = (mmsi, ts, src)
                if key_tuple in seen:
                    dupes_removed += 1
                else:
                    seen.add(key_tuple)
        results[key] = {
            "path": path,
            "data_rows": n_data,
            "expected": expected[key],
            "matches_expected": n_data == expected[key],
            "dedup_duplicates_removed": dupes_removed,
        }
    return results


# ============================
# PART 2 — Full raw census
# ============================
def part2():
    dirs = {
        "captain2024": AIS2024_CAPTS,
        "position2024": AIS2024_POS,
        "captain2025": AIS2025_CAPTS,
        "position2025": AIS2025_POS,
    }
    results = {}
    for key, d in dirs.items():
        files = list_csv_files(d)
        total_rows = 0
        per_file = []
        for f in files:
            fp = os.path.join(d, f)
            n_lines = count_lines_file(fp)
            n_data = max(n_lines - 1, 0)
            total_rows += n_data
            per_file.append({"file": f, "lines": n_lines, "data_rows": n_data})
        results[key] = {
            "directory": d,
            "file_count": len(files),
            "total_data_rows": total_rows,
            "per_file": per_file,
        }
    results["year_totals"] = {
        "2024": results["captain2024"]["total_data_rows"] + results["position2024"]["total_data_rows"],
        "2025": results["captain2025"]["total_data_rows"] + results["position2025"]["total_data_rows"],
    }
    return results


# ============================
# PART 3 — PRD port metrics with nearest-terminal assignment
# ============================
def part3():
    results = {}
    for year, capts_dir, pos_dir in [
        (2024, AIS2024_CAPTS, AIS2024_POS),
        (2025, AIS2025_CAPTS, AIS2025_POS),
    ]:
        # Daily-last position snapshots
        daily_pos = get_daily_last_files(pos_dir)
        daily_capts = get_daily_last_files(capts_dir)

        # Build vessel -> max length lookup from daily-last captain snapshots
        vessel_max_length = {}  # mmsi -> max valid length
        capts_unparseable_last = 0
        capts_daily_records = 0
        for date_str, fp in daily_capts.items():
            for row in read_csv_rows(fp):
                capts_daily_records += 1
                mmsi = strip_bad(row.get("ais_capts_mmsi", ""))
                last_ts = strip_bad(row.get("ais_capts_last", ""))
                if not parse_ts(last_ts):
                    capts_unparseable_last += 1
                length = parse_float(row.get("ais_capts_length", ""))
                if mmsi and length is not None and length > 0:
                    if mmsi not in vessel_max_length or length > vessel_max_length[mmsi]:
                        vessel_max_length[mmsi] = length

        # Process daily-last position snapshots
        port_vessels = defaultdict(set)      # port -> set of mmsi
        port_points = defaultdict(int)        # port -> count of position points
        port_dwell_vessels = defaultdict(set) # port -> vessels with >=3 in-zone points speed<=3
        vessel_inzone_count = defaultdict(lambda: defaultdict(int))  # mmsi -> port -> in-zone slow count
        port_transit_points = defaultdict(int) # port -> transit points (speed > 3)
        port_vessel_lengths = defaultdict(list)  # port -> list of lengths for vessels
        vessels_no_length = defaultdict(set)   # port -> vessels with no valid length
        invalid_coords_count = 0
        zero_zero_count = 0
        outer_invalid_coords = 0
        outer_zero_zero = 0

        # Also old box method
        old_box_vessels = defaultdict(set)

        nearest_terminal_dup_samples = []  # for PART 6 duplicate check within daily-last file

        for date_str, fp in daily_pos.items():
            seen_mmsi_ts = set()
            dup_within_file = 0
            for row in read_csv_rows(fp):
                mmsi = strip_bad(row.get("ais_position_mmsi", ""))
                lat = parse_float(row.get("ais_position_latitude", ""))
                lon = parse_float(row.get("ais_position_longitude", ""))
                speed = parse_float(row.get("ais_position_speed", ""))
                ts = strip_bad(row.get("ais_position_timestamp", ""))

                # duplicate (mmsi, timestamp) within single daily-last file
                if mmsi and ts:
                    k = (mmsi, ts)
                    if k in seen_mmsi_ts:
                        dup_within_file += 1
                    else:
                        seen_mmsi_ts.add(k)
                if len(nearest_terminal_dup_samples) < 5 and dup_within_file > 0:
                    nearest_terminal_dup_samples.append(
                        {"date": date_str, "file": os.path.basename(fp), "dups_within_file": dup_within_file}
                    )

                # valid coords check
                coords_valid = lat is not None and lon is not None
                is_zero_zero = lat == 0.0 and lon == 0.0 if coords_valid else False

                if coords_valid:
                    if lat == 0.0 and lon == 0.0:
                        zero_zero_count += 1

                    # Outer bbox check
                    in_outer = (OUTER_LAT_MIN <= lat <= OUTER_LAT_MAX and
                                OUTER_LON_MIN <= lon <= OUTER_LON_MAX and
                                not (lat == 0.0 and lon == 0.0))

                    if in_outer:
                        # find nearest terminal
                        best_terminal = None
                        best_dist = float("inf")
                        for tname, (tlat, tlon) in TERMINALS.items():
                            d = math.hypot(lat - tlat, lon - tlon)
                            if d < best_dist:
                                best_dist = d
                                best_terminal = tname
                        if best_dist <= DIST_THRESHOLD:
                            port = TERMINAL_PORT[best_terminal]
                            port_vessels[port].add(mmsi)
                            port_points[port] += 1
                            speed_ok = (speed is None or speed == 0.0 or speed <= 3.0)
                            if speed_ok:
                                vessel_inzone_count[mmsi][port] += 1
                            else:
                                port_transit_points[port] += 1
                        # else: discard (outside threshold)

                    # invalid coords within outer bbox
                    if not coords_valid:
                        outer_invalid_coords += 1
                        if is_zero_zero:
                            outer_zero_zero += 1

                # old box method
                if coords_valid and not (lat == 0.0 and lon == 0.0):
                    for port, ((lat_min, lat_max), (lon_min, lon_max)) in OLD_BOXES.items():
                        if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
                            old_box_vessels[port].add(mmsi)

            if dup_within_file > 0 and len(nearest_terminal_dup_samples) < 5:
                nearest_terminal_dup_samples.append(
                    {"date": date_str, "file": os.path.basename(fp), "dups_within_file": dup_within_file}
                )

        # Dwell-based arrivals: vessels with >= 3 in-zone points at speed <= 3
        port_dwell_arrivals = defaultdict(int)
        for mmsi, port_counts in vessel_inzone_count.items():
            for port, cnt in port_counts.items():
                if cnt >= 3:
                    port_dwell_arrivals[port] += 1

        # Size-weighted throughput proxy
        port_size_sum = defaultdict(float)
        port_size_mean_count = defaultdict(int)
        for port in PORTS:
            for mmsi in port_vessels[port]:
                if mmsi in vessel_max_length:
                    port_size_sum[port] += vessel_max_length[mmsi]
                    port_size_mean_count[port] += 1
                else:
                    vessels_no_length[port].add(mmsi)

        # Monthly trend (nearest-terminal)
        monthly = defaultdict(lambda: defaultdict(lambda: defaultdict(set)))
        # Re-process to get month info
        for date_str, fp in daily_pos.items():
            try:
                dt = datetime.strptime(date_str, "%Y%m%d")
                month = dt.month
            except (ValueError, TypeError):
                continue
            for row in read_csv_rows(fp):
                mmsi = strip_bad(row.get("ais_position_mmsi", ""))
                lat = parse_float(row.get("ais_position_latitude", ""))
                lon = parse_float(row.get("ais_position_longitude", ""))
                if not (lat is not None and lon is not None):
                    continue
                if lat == 0.0 and lon == 0.0:
                    continue
                if not (OUTER_LAT_MIN <= lat <= OUTER_LAT_MAX and OUTER_LON_MIN <= lon <= OUTER_LON_MAX):
                    continue
                best_terminal = None
                best_dist = float("inf")
                for tname, (tlat, tlon) in TERMINALS.items():
                    d = math.hypot(lat - tlat, lon - tlon)
                    if d < best_dist:
                        best_dist = d
                        best_terminal = tname
                if best_dist <= DIST_THRESHOLD:
                    port = TERMINAL_PORT[best_terminal]
                    monthly[year][month][port].add(mmsi)

        results[str(year)] = {
            "daily_position_files": len(daily_pos),
            "daily_captain_files": len(daily_capts),
            "captain_daily_records": capts_daily_records,
            "captains_unparseable_last": capts_unparseable_last,
            "nearest_terminal": {
                port: {
                    "distinct_vessels": len(port_vessels[port]),
                    "position_points": port_points[port],
                    "dwell_arrivals": port_dwell_arrivals[port],
                    "transit_points": port_transit_points[port],
                    "size_weighted_sum": round(port_size_sum[port], 2),
                    "size_weighted_mean": round(port_size_sum[port] / port_size_mean_count[port], 2) if port_size_mean_count[port] else 0,
                    "vessels_with_length": port_size_mean_count[port],
                    "vessels_no_length": len(vessels_no_length[port]),
                }
                for port in PORTS
            },
            "old_box_method": {
                port: len(old_box_vessels[port]) for port in PORTS
            },
            "monthly_trend": {
                str(m): {port: len(monthly[year][m][port]) for port in PORTS}
                for m in sorted(monthly[year].keys())
            },
            "dup_within_daily_position_samples": nearest_terminal_dup_samples[:5],
        }
    return results


# ============================
# PART 4 — Destination-based arrivals
# ============================
def part4():
    results = {}
    for year, capts_dir in [(2024, AIS2024_CAPTS), (2025, AIS2025_CAPTS)]:
        daily_capts = get_daily_last_files(capts_dir)
        port_vessels = defaultdict(set)
        for date_str, fp in daily_capts.items():
            for row in read_csv_rows(fp):
                mmsi = strip_bad(row.get("ais_capts_mmsi", ""))
                dest = strip_bad(row.get("ais_capts_destination", "")).upper()
                if not mmsi:
                    continue
                matched = []
                if any(k in dest for k in ("HONG KONG", "HONGKONG", "HKG")):
                    matched.append("Hong Kong")
                if any(k in dest for k in ("SHENZHEN", "YANTIAN", "SHEKOU", "CHIWAN")):
                    matched.append("Shenzhen")
                if any(k in dest for k in ("GUANGZHOU", "NANSHA", "CANTON")):
                    matched.append("Guangzhou")
                for port in matched:
                    port_vessels[port].add(mmsi)
        results[str(year)] = {
            "daily_captain_files": len(daily_capts),
            "port_vessels": {port: len(port_vessels[port]) for port in PORTS},
        }
    return results


# ============================
# PART 5 — Monthly trend (already in part3)
# ============================
def part5(part3_results):
    # Just re-package from part3
    return {year: data.get("monthly_trend", {}) for year, data in part3_results.items()}


# ============================
# PART 6 — Data quality checks
# ============================
def part6():
    results = {}
    for year, capts_dir, pos_dir in [
        (2024, AIS2024_CAPTS, AIS2024_POS),
        (2025, AIS2025_CAPTS, AIS2025_POS),
    ]:
        daily_capts = get_daily_last_files(capts_dir)
        daily_pos = get_daily_last_files(pos_dir)

        # Captain unparseable last
        capts_unparseable = 0
        capts_total = 0
        for date_str, fp in daily_capts.items():
            for row in read_csv_rows(fp):
                capts_total += 1
                last_ts = strip_bad(row.get("ais_capts_last", ""))
                if not parse_ts(last_ts):
                    capts_unparseable += 1

        # Position invalid coords and (0,0) in PRD outer bbox
        invalid_coords = 0
        zero_zero = 0
        for date_str, fp in daily_pos.items():
            for row in read_csv_rows(fp):
                lat = parse_float(row.get("ais_position_latitude", ""))
                lon = parse_float(row.get("ais_position_longitude", ""))
                if not (lat is not None and lon is not None):
                    if OUTER_LAT_MIN <= 0 <= OUTER_LAT_MAX:  # can't check bbox without valid coords
                        pass
                    # We count invalid coords as those that fail to parse but we can't check bbox
                    # Actually we need to check: position rows IN the PRD outer bbox with invalid coords
                    # If coords are invalid, we can't determine if they're in the bbox.
                    # So we count: rows where coord parse failed entirely
                    invalid_coords += 1
                    continue
                if lat == 0.0 and lon == 0.0:
                    if OUTER_LAT_MIN <= lat <= OUTER_LAT_MAX and OUTER_LON_MIN <= lon <= OUTER_LON_MAX:
                        zero_zero += 1
                    continue
                if OUTER_LAT_MIN <= lat <= OUTER_LAT_MAX and OUTER_LON_MIN <= lon <= OUTER_LON_MAX:
                    pass  # valid coords in bbox, already counted

        # Hmm, need to reconsider: "position rows in the PRD outer bbox with invalid/unparseable coords"
        # If coords are unparseable, we can't know if they're in the bbox. Let me re-read.
        # "Per year: count of position rows in the PRD outer bbox with invalid/unparseable coords, and with exact (0,0)."
        # This likely means: among rows where coords are present but invalid (e.g. [BAD] or 0,0), count those in the bbox.
        # For (0,0): lat=0 is outside 21.8-23.6, so (0,0) is NOT in the outer bbox.
        # So zero_zero in outer bbox = 0.
        # For invalid coords: we can't determine bbox membership. Let me count all rows with invalid coords
        # that appear in daily-last position files (they can't be assigned to any port).
        # Actually re-reading: "count of position rows in the PRD outer bbox with invalid/unparseable coords"
        # I think this means: count rows where coords fail to parse, AND count rows with (0,0).
        # Since (0,0) is outside the bbox, the (0,0) count within bbox would be 0.
        # Let me just report: invalid coord rows (total across all daily-last files), and (0,0) rows.
        # And separately note that (0,0) falls outside the outer bbox.

        # Distinct vessels in PRD with no valid length
        # Reuse logic from part3
        vessel_max_length = {}
        for date_str, fp in daily_capts.items():
            for row in read_csv_rows(fp):
                mmsi = strip_bad(row.get("ais_capts_mmsi", ""))
                length = parse_float(row.get("ais_capts_length", ""))
                if mmsi and length is not None and length > 0:
                    if mmsi not in vessel_max_length or length > vessel_max_length[mmsi]:
                        vessel_max_length[mmsi] = length

        prd_vessels = set()
        prd_vessels_no_length = set()
        for date_str, fp in daily_pos.items():
            for row in read_csv_rows(fp):
                mmsi = strip_bad(row.get("ais_position_mmsi", ""))
                lat = parse_float(row.get("ais_position_latitude", ""))
                lon = parse_float(row.get("ais_position_longitude", ""))
                if not (lat is not None and lon is not None):
                    continue
                if lat == 0.0 and lon == 0.0:
                    continue
                if OUTER_LAT_MIN <= lat <= OUTER_LAT_MAX and OUTER_LON_MIN <= lon <= OUTER_LON_MAX:
                    prd_vessels.add(mmsi)
                    if mmsi not in vessel_max_length:
                        prd_vessels_no_length.add(mmsi)

        results[str(year)] = {
            "captain_unparseable_last": capts_unparseable,
            "captain_total_records": capts_total,
            "position_invalid_coords_total": invalid_coords,
            "position_zero_zero_total": zero_zero,
            "prd_distinct_vessels": len(prd_vessels),
            "prd_vessels_no_valid_length": len(prd_vessels_no_length),
            "prd_length_coverage_gap_pct": round(100.0 * len(prd_vessels_no_length) / len(prd_vessels), 2) if prd_vessels else 0,
        }
    return results


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    report = {}

    print("=" * 70)
    print("PART 1 — FLAGGED FILE RE-VERIFICATION")
    print("=" * 70)
    p1 = part1()
    report["part1"] = p1
    for key, r in p1.items():
        print(f"{key}: data_rows={r['data_rows']}, expected={r['expected']}, "
              f"matches={r['matches_expected']}, dedup_dupes_removed={r['dedup_duplicates_removed']}")

    print()
    print("=" * 70)
    print("PART 2 — FULL RAW CENSUS")
    print("=" * 70)
    p2 = part2()
    report["part2"] = p2
    for key in ["captain2024", "position2024", "captain2025", "position2025"]:
        r = p2[key]
        print(f"{key}: files={r['file_count']}, total_data_rows={r['total_data_rows']}")
    print(f"Year totals: 2024={p2['year_totals']['2024']}, 2025={p2['year_totals']['2025']}")

    print()
    print("=" * 70)
    print("PART 3 — PRD PORT METRICS (NEAREST-TERMINAL) + OLD BOX METHOD")
    print("=" * 70)
    p3 = part3()
    report["part3"] = p3
    for year in ["2024", "2025"]:
        d = p3[year]
        print(f"\n--- Year {year} ---")
        print(f"  Daily position files: {d['daily_position_files']}, Daily captain files: {d['daily_captain_files']}")
        print(f"  Captain daily records: {d['captain_daily_records']}, Unparseable last: {d['captains_unparseable_last']}")
        print(f"  {'Port':<15} {'Vessels':>8} {'Points':>9} {'DwellArr':>9} {'Transit':>8} {'SizeSum':>10} {'SizeMean':>9} {'NoLen':>6}")
        for port in PORTS:
            m = d["nearest_terminal"][port]
            print(f"  {port:<15} {m['distinct_vessels']:>8} {m['position_points']:>9} "
                  f"{m['dwell_arrivals']:>9} {m['transit_points']:>8} {m['size_weighted_sum']:>10.2f} "
                  f"{m['size_weighted_mean']:>9.2f} {m['vessels_no_length']:>6}")
        print(f"  Old box method distinct vessels: " +
              ", ".join(f"{p}={p3[year]['old_box_method'][p]}" for p in PORTS))
        print(f"  Dup within daily-position samples: {d['dup_within_daily_position_samples']}")

    print()
    print("=" * 70)
    print("PART 4 — DESTINATION-BASED ARRIVALS")
    print("=" * 70)
    p4 = part4()
    report["part4"] = p4
    for year in ["2024", "2025"]:
        d = p4[year]
        print(f"  Year {year}: " + ", ".join(f"{p}={d['port_vessels'][p]}" for p in PORTS))

    print()
    print("=" * 70)
    print("PART 5 — MONTHLY TREND (NEAREST-TERMINAL, DISTINCT VESSELS)")
    print("=" * 70)
    p5 = part5(p3)
    report["part5"] = p5
    for year in ["2024", "2025"]:
        print(f"  Year {year}:")
        for m in sorted(p5[year].keys(), key=int):
            vals = p5[year][m]
            print(f"    Month {m}: " + ", ".join(f"{p}={vals[p]}" for p in PORTS))

    print()
    print("=" * 70)
    print("PART 6 — DATA-QUALITY CHECKS")
    print("=" * 70)
    p6 = part6()
    report["part6"] = p6
    for year in ["2024", "2025"]:
        d = p6[year]
        print(f"  Year {year}:")
        print(f"    Captain unparseable last: {d['captain_unparseable_last']} / {d['captain_total_records']}")
        print(f"    Position invalid coords (total): {d['position_invalid_coords_total']}")
        print(f"    Position (0,0) total: {d['position_zero_zero_total']}")
        print(f"    PRD distinct vessels: {d['prd_distinct_vessels']}")
        print(f"    PRD vessels no valid length: {d['prd_vessels_no_valid_length']} "
              f"({d['prd_length_coverage_gap_pct']}%)")

    # Summary ranking
    print()
    print("=" * 70)
    print("SUMMARY — PORT RANKING COMPARISON")
    print("=" * 70)
    for year in ["2024", "2025"]:
        nt = p3[year]["nearest_terminal"]
        ob = p3[year]["old_box_method"]
        dest = p4[year]["port_vessels"]
        nt_arrivals = sorted(PORTS, key=lambda p: nt[p]["distinct_vessels"], reverse=True)
        nt_dwell = sorted(PORTS, key=lambda p: nt[p]["dwell_arrivals"], reverse=True)
        ob_rank = sorted(PORTS, key=lambda p: ob[p], reverse=True)
        dest_rank = sorted(PORTS, key=lambda p: dest[p], reverse=True)
        print(f"\nYear {year}:")
        print(f"  Nearest-terminal arrivals ranking: {' > '.join(nt_arrivals)}")
        print(f"  Nearest-terminal dwell-arrivals ranking: {' > '.join(nt_dwell)}")
        print(f"  Old box-method ranking: {' > '.join(ob_rank)}")
        print(f"  Destination-based ranking: {' > '.join(dest_rank)}")
        nt_sz = nt["Shenzhen"]["distinct_vessels"]
        nt_hk = nt["Hong Kong"]["distinct_vessels"]
        nt_gz = nt["Guangzhou"]["distinct_vessels"]
        changes = "YES" if (nt_sz > nt_hk or nt_gz > nt_hk) else "NO"
        print(f"  Nearest-terminal fix changes ranking toward SZ/GZ leading: {changes}"
              f" (SZ={nt_sz}, GZ={nt_gz}, HK={nt_hk})")

    # Write JSON
    with open(OUT_JSON, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nJSON written to {OUT_JSON}")


if __name__ == "__main__":
    main()