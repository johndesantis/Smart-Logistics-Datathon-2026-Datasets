#!/usr/bin/env python3
"""
Flagged anomaly analysis (read-only on sources).
Reads the four flagged CSVs and writes artifacts to analysis_output/.
Deterministic, stdlib only. Does NOT modify any source file.
"""
import csv
import json
import os
from collections import Counter, defaultdict
from datetime import datetime

BASE = "/home/haha/Downloads"
OUT = os.path.join(BASE, "analysis_output")
os.makedirs(OUT, exist_ok=True)

POS_FILES = {
    2024: os.path.join(BASE, "flaggedpositioncells2024.csv"),
    2025: os.path.join(BASE, "flaggedpositioncells2025.csv"),
}
CAPT_FILES = {
    2024: os.path.join(BASE, "flaggedcaptaincells2024.csv"),
    2025: os.path.join(BASE, "flaggedcaptaincells2025.csv"),
}

ISO_FMT = "%Y-%m-%d %H:%M:%S"


def clean(v):
    return (v or "").replace("[BAD]", "").strip()


def parse_iso(v):
    v = clean(v)
    if not v or v == "0000-00-00 00:00:00":
        return None
    try:
        return datetime.strptime(v, ISO_FMT)
    except ValueError:
        return None


def classify_basin(lat, lon):
    """lat/lon floats or None. Returns basin string. First match wins."""
    if lat is None or lon is None or (lat == 0.0 and lon == 0.0):
        return "Unattributable"
    if 15 <= lat <= 45 and 105 <= lon <= 130:
        return "East Asia/China Coastal"
    if 0 <= lat < 15 and 105 <= lon <= 122:
        return "South China Sea/Tropical"
    if 30 <= lat <= 45 and -10 <= lon <= 40:
        return "Mediterranean"
    if -70 <= lon <= 20:
        return "Atlantic Ocean"
    if -60 <= lat <= 25 and 20 <= lon <= 120:
        return "Indian Ocean"
    return "Pacific Ocean"


def read_csv(path):
    with open(path, newline="", encoding="utf-8", errors="replace") as fh:
        return list(csv.DictReader(fh))


def main():
    results = {"generated_utc": datetime.utcnow().isoformat(), "basins": {}, "files": {}}

    # ---- 1. row counts + dedup check (no write-back) --------------------
    for year in (2024, 2025):
        for kind, path in (("position", POS_FILES[year]), ("captain", CAPT_FILES[year])):
            rows = read_csv(path)
            if kind == "position":
                key = lambda r: (clean(r.get("ais_position_mmsi")),
                                 clean(r.get("ais_position_timestamp")),
                                 r.get("file"))
            else:
                key = lambda r: (clean(r.get("ais_capts_mmsi")),
                                 clean(r.get("ais_capts_last")),
                                 r.get("file"))
            keys = [key(r) for r in rows]
            dupes = len(keys) - len(set(keys))
            results["files"][f"{kind}_{year}"] = {
                "path": path,
                "data_rows": len(rows),
                "duplicates_removed_by_key": dupes,
                "rows_after_dedup": len(set(keys)),
            }

    # ---- 2-5. position rows: basins, attribution, vessels, shift --------
    pos_rows = {y: read_csv(POS_FILES[y]) for y in (2024, 2025)}
    basin_counts = {y: Counter() for y in (2024, 2025)}
    row_records = {y: [] for y in (2024, 2025)}

    for year in (2024, 2025):
        for r in pos_rows[year]:
            try:
                lat = float(clean(r.get("ais_position_latitude")))
            except (TypeError, ValueError):
                lat = None
            try:
                lon = float(clean(r.get("ais_position_longitude")))
            except (TypeError, ValueError):
                lon = None
            basin = classify_basin(lat, lon)
            basin_counts[year][basin] += 1
            row_records[year].append({
                "source_file": r.get("file", ""),
                "row_index": r.get("row_index", ""),
                "mmsi": clean(r.get("ais_position_mmsi")),
                "ship_id": clean(r.get("ais_ship_id")),
                "latitude": clean(r.get("ais_position_latitude")),
                "longitude": clean(r.get("ais_position_longitude")),
                "course": clean(r.get("ais_position_course")),
                "heading": clean(r.get("ais_position_heading")),
                "speed": clean(r.get("ais_position_speed")),
                "nav_status_desc": clean(r.get("nav_status_desc")),
                "position_timestamp": clean(r.get("ais_position_timestamp")),
                "basin": basin,
                "flagged_columns": r.get("flagged_columns", ""),
                "flagged_reasons": r.get("flagged_reasons", ""),
            })

    for year in (2024, 2025):
        cols = ["source_file", "row_index", "mmsi", "ship_id", "latitude", "longitude",
                "course", "heading", "speed", "nav_status_desc", "position_timestamp",
                "basin", "flagged_columns", "flagged_reasons"]
        with open(os.path.join(OUT, f"flagged_position_{year}_rows.csv"), "w",
                  newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            for rec in row_records[year]:
                w.writerow(rec)

    # 2024 attribution
    tot24 = len(pos_rows[2024])
    china24 = basin_counts[2024]["East Asia/China Coastal"]
    unattr24 = basin_counts[2024]["Unattributable"]
    results["attribution_2024"] = {
        "total_rows": tot24,
        "china_coastal_count": china24,
        "china_coastal_pct": round(china24 / tot24 * 100, 4) if tot24 else None,
        "unattributable_count": unattr24,
        "traceable_rows": tot24 - unattr24,
        "claim_12_of_15_supported": china24 == 12,
        "claim_discrepancy_rows": 12 - china24,
        "claim_discrepancy_pp": round((12 - china24) / tot24 * 100, 4) if tot24 else None,
    }

    # 2025 satellite-error vessels
    capt25 = read_csv(CAPT_FILES[2025])
    capt25_by_mmsi = defaultdict(list)
    for r in capt25:
        capt25_by_mmsi[clean(r.get("ais_capts_mmsi"))].append(r)
    capt24_mmsis = {clean(r.get("ais_capts_mmsi")) for r in read_csv(CAPT_FILES[2024])}
    pos24_mmsis = {clean(r.get("ais_position_mmsi")) for r in pos_rows[2024]}

    vessels = []
    by_mmsi = defaultdict(list)
    for r in pos_rows[2025]:
        by_mmsi[clean(r.get("ais_position_mmsi"))].append(r)
    for mmsi in sorted(by_mmsi):
        rs = by_mmsi[mmsi]
        ts = [parse_iso(r.get("ais_position_timestamp")) for r in rs]
        ts = [t for t in ts if t]
        lat0 = all(clean(r.get("ais_position_latitude")) == "0.00000"
                   and clean(r.get("ais_position_longitude")) == "0.00000" for r in rs)
        course_bad = any("course" in (r.get("flagged_columns") or "") for r in rs)
        cap = capt25_by_mmsi.get(mmsi, [])
        name = clean(cap[0].get("ais_capts_name")) if cap else ""
        vessels.append({
            "mmsi": mmsi,
            "ship_id": clean(rs[0].get("ais_ship_id")),
            "vessel_name": name,
            "error_time_start": min(ts).isoformat() if ts else "",
            "error_time_end": max(ts).isoformat() if ts else "",
            "files_affected": ";".join(sorted({r.get("file", "") for r in rs})),
            "flagged_reasons": ";".join(sorted({r.get("flagged_reasons", "") for r in rs})),
            "row_count": len(rs),
            "fault_type": ("null island (0,0)" if lat0 else "") +
                          ("; " if lat0 and course_bad else "") +
                          ("course out of range" if course_bad else ""),
            "also_in_flagged_captain_2025": bool(cap),
            "captain_flagged_reasons_2025": ";".join(sorted({r.get("flagged_reasons", "") for r in cap}))[:300],
            "repeat_offender_2024_2025": mmsi in pos24_mmsis,
        })
    with open(os.path.join(OUT, "satellite_error_vessels_2025.csv"), "w",
              newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(vessels[0].keys()) if vessels else ["mmsi"])
        w.writeheader()
        for v in vessels:
            w.writerow(v)
    results["satellite_error_vessels_2025"] = {
        "distinct_vessels": len(vessels),
        "speculation_was_approx_5": True,
        "vessels": vessels,
    }

    # regional shift table
    basins = ["East Asia/China Coastal", "South China Sea/Tropical", "Atlantic Ocean",
              "Mediterranean", "Indian Ocean", "Pacific Ocean", "Unattributable"]
    tot = {y: len(pos_rows[y]) for y in (2024, 2025)}
    shift_rows = []
    for b in basins:
        c24, c25 = basin_counts[2024][b], basin_counts[2025][b]
        p24 = round(c24 / tot[2024] * 100, 4) if tot[2024] else 0.0
        p25 = round(c25 / tot[2025] * 100, 4) if tot[2025] else 0.0
        shift_rows.append({"basin": b, "count_2024": c24, "pct_2024": p24,
                           "count_2025": c25, "pct_2025": p25, "delta_pp": round(p25 - p24, 4)})
    with open(os.path.join(OUT, "regional_shift_table.csv"), "w",
              newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["basin", "count_2024", "pct_2024",
                                           "count_2025", "pct_2025", "delta_pp"])
        w.writeheader()
        for r in shift_rows:
            w.writerow(r)
    geo25 = tot[2025] - basin_counts[2025]["Unattributable"]
    results["regional_shift"] = {
        "table": shift_rows,
        "china_vs_atlantic": {
            "china_2024_pct": next(r["pct_2024"] for r in shift_rows if r["basin"] == "East Asia/China Coastal"),
            "china_2025_pct": next(r["pct_2025"] for r in shift_rows if r["basin"] == "East Asia/China Coastal"),
            "atlantic_2024_pct": next(r["pct_2024"] for r in shift_rows if r["basin"] == "Atlantic Ocean"),
            "atlantic_2025_pct": next(r["pct_2025"] for r in shift_rows if r["basin"] == "Atlantic Ocean"),
            "geolocatable_2025_rows": geo25,
            "atlantic_share_of_geolocatable_2025_pct":
                round(basin_counts[2025]["Atlantic Ocean"] / geo25 * 100, 4) if geo25 else None,
        },
    }

    # ---- 6. captain flag profile ----------------------------------------
    profile_rows = []
    profile = {}
    for year in (2024, 2025):
        rows = read_csv(CAPT_FILES[year])
        mmsis = {clean(r.get("ais_capts_mmsi")) for r in rows}
        bad_eta = sum(1 for r in rows if parse_iso(r.get("ais_capts_eta")) is None)
        reasons = Counter()
        for r in rows:
            for item in (r.get("flagged_reasons") or "").split(";"):
                item = item.strip()
                if not item:
                    continue
                reasons[item.split("=", 1)[1] if "=" in item else item] += 1
        n = len(rows)
        profile[year] = {"rows": n, "distinct_vessels": len(mmsis),
                         "unparseable_eta": bad_eta,
                         "reasons": dict(reasons.most_common())}
        profile_rows.append({"year": year, "metric_or_reason": "total_rows",
                             "count": n, "pct_of_year_rows": 100.0})
        profile_rows.append({"year": year, "metric_or_reason": "distinct_vessels",
                             "count": len(mmsis), "pct_of_year_rows": ""})
        profile_rows.append({"year": year, "metric_or_reason": "unparseable_eta",
                             "count": bad_eta,
                             "pct_of_year_rows": round(bad_eta / n * 100, 4) if n else ""})
        for reason, c in reasons.most_common():
            profile_rows.append({"year": year, "metric_or_reason": reason, "count": c,
                                 "pct_of_year_rows": round(c / n * 100, 4) if n else ""})
    with open(os.path.join(OUT, "captain_flag_profile.csv"), "w",
              newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["year", "metric_or_reason",
                                           "count", "pct_of_year_rows"])
        w.writeheader()
        for r in profile_rows:
            w.writerow(r)
    results["captain_flag_profile"] = profile

    # ---- 7. cross-year deltas -------------------------------------------
    def delta(a, b):
        return {"abs": b - a, "pct_change": round((b - a) / a * 100, 4) if a else None}
    results["cross_year_deltas"] = {
        "flagged_position_rows": delta(len(pos_rows[2024]), len(pos_rows[2025])),
        "flagged_captain_rows": delta(results["files"]["captain_2024"]["data_rows"],
                                      results["files"]["captain_2025"]["data_rows"]),
        "flagged_total_rows": delta(
            len(pos_rows[2024]) + results["files"]["captain_2024"]["data_rows"],
            len(pos_rows[2025]) + results["files"]["captain_2025"]["data_rows"]),
        "distinct_flagged_captain_vessels": delta(profile[2024]["distinct_vessels"],
                                                  profile[2025]["distinct_vessels"]),
    }

    with open(os.path.join(OUT, "flagged_analysis.json"), "w", encoding="utf-8") as fh:
        json.dump(results, fh, indent=2)

    with open(os.path.join(OUT, "flagged_methodology.txt"), "w", encoding="utf-8") as fh:
        fh.write("""FLAGGED ANOMALY ANALYSIS - METHODOLOGY
======================================
Sources (READ-ONLY, never modified):
  flaggedpositioncells2024.csv, flaggedpositioncells2025.csv,
  flaggedcaptaincells2024.csv, flaggedcaptaincells2025.csv

Dedup key (check only; no write-back to sources):
  position: (ais_position_mmsi, ais_position_timestamp, file)
  captain:   (ais_capts_mmsi, ais_capts_last, file)

[BAD] handling: literal '[BAD]' prefix stripped before numeric/timestamp
parsing; raw values preserved in output CSVs.

Basin classification (first match wins; Unattributable if lat/lon missing,
unparseable, or exactly (0,0)):
  East Asia/China Coastal : 15 <= lat <= 45 and 105 <= lon <= 130
  South China Sea/Tropical: 0 <= lat < 15 and 105 <= lon <= 122
  Mediterranean           : 30 <= lat <= 45 and -10 <= lon <= 40
  Atlantic Ocean          : -70 <= lon <= 20
  Indian Ocean            : -60 <= lat <= 25 and 20 <= lon <= 120
  Pacific Ocean           : else (valid coordinates)

Timestamps: ISO '%Y-%m-%d %H:%M:%S'; unparseable = empty,
'0000-00-00 00:00:00', '[BAD]'-prefixed, or non-matching format.
Naive timestamps treated as UTC (documented assumption).

Exclusions: rows with invalid coordinates are retained in tables as
'Unattributable' (they ARE the flagged discrepancy); no other exclusions.
""")

    print(json.dumps({k: v for k, v in results.items()
                      if k in ("files", "attribution_2024", "regional_shift",
                               "cross_year_deltas")}, indent=2))
    print("satellite vessels:", len(vessels))
    for v in vessels:
        print(" ", v["mmsi"], v["vessel_name"], v["fault_type"])
    print("captain profile:", {y: (profile[y]["rows"], profile[y]["distinct_vessels"])
                               for y in (2024, 2025)})


if __name__ == "__main__":
    main()
