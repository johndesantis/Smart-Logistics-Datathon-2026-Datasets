#!/usr/bin/env python3
"""
PRD zone audit — diagnose why the HK/Shenzhen/Guangzhou dashboard ranking
(HK largest, Shenzhen smallest) conflicts with real-world throughput
(Shenzhen > Guangzhou > HK).

Tests, per year (2024, 2025), using daily-last snapshots:
  A. Destination-based arrivals: distinct vessels whose reported
     ais_capts_destination matches each port's keywords. This measures
     vessels heading TO a port (closer to "trade influence") rather than
     mere presence in a box.
  B. Zone-box presence (recomputed): distinct vessels + position points in
     the current dashboard bounding boxes.
  C. Boundary mis-assignment: points/vessels in the Shekou/Chiwan sub-box
     (currently counted as Hong Kong) and the Yantian sub-box.
  D. HK transit vs dwell split: position points in the HK box by speed
     (transit = speed > 3 kn; dwell = speed <= 3 or invalid/0), to show how
     much of HK's high count is through-traffic/anchorage vs port calls.

Read-only on all sources. Writes analysis_output/prd_zone_audit.json and
prints a report. Run: python3 prd_zone_audit.py
"""
import csv
import json
import os
import re
import glob
from collections import defaultdict
from datetime import datetime, timezone

BASE = "/home/haha/Downloads"
OUT = os.path.join(BASE, "analysis_output")
os.makedirs(OUT, exist_ok=True)

POS_DIRS = {
    2024: "/home/haha/Downloads/3-2. AIS Data/2024 Data/position info/2024",
    2025: "/home/haha/Downloads/3-2. AIS Data/2025 Data/position info 2025",
}
CAP_DIRS = {
    2024: "/home/haha/Downloads/3-2. AIS Data/2024 Data/captain info/2024",
    2025: "/home/haha/Downloads/3-2. AIS Data/2025 Data/captain info 2025",
}

# Current dashboard boxes (lat_min, lat_max, lon_min, lon_max)
ZONES = {
    "Hong Kong": (22.05, 22.55, 113.80, 114.50),
    "Shenzhen":  (22.55, 22.85, 113.80, 114.50),
    "Guangzhou": (22.60, 23.40, 113.10, 113.80),
}
# Sub-boxes to test boundary mis-assignment
SHEKOU_CHIWAN = (22.40, 22.55, 113.85, 114.05)   # Shenzhen terminals, S of 22.55
YANTIAN = (22.55, 22.68, 114.18, 114.38)        # Shenzhen container terminal
OUTER = (21.8, 23.6, 112.9, 114.7)

PORT_KEYWORDS = {
    "Hong Kong": ["HONG KONG", "HONGKONG", "HKG"],
    "Shenzhen": ["SHENZHEN", "YANTIAN", "SHEKOU", "CHIWAN"],
    "Guangzhou": ["GUANGZHOU", "NANSHA", "CANTON"],
}


def clean(v):
    return (v or "").replace("[BAD]", "").strip()


def daily_last_index(directory, prefix):
    by_date = {}
    for f in glob.glob(os.path.join(directory, prefix)):
        b = os.path.basename(f)
        if b.startswith(".~lock"):
            continue
        m = re.match(r".*-(\d{8})T(\d{6})Z\.csv$", b)
        if not m:
            continue
        d, s = m.group(1), int(m.group(2))
        if d not in by_date or s > by_date[d][0]:
            by_date[d] = (s, f)
    return {d: v[1] for d, v in by_date.items()}


def in_box(lat, lon, box):
    la0, la1, lo0, lo1 = box
    return la0 <= lat <= la1 and lo0 <= lon <= lo1


def dest_port(dest):
    d = dest.upper()
    for port, kws in PORT_KEYWORDS.items():
        for kw in kws:
            if kw in d:
                return port
    return None


def audit_year(year):
    pos_idx = daily_last_index(POS_DIRS[year], "positions-*.csv")
    cap_idx = daily_last_index(CAP_DIRS[year], "capts-*.csv")

    zone_vessels = defaultdict(set)
    zone_points = defaultdict(int)
    hk_transit = 0
    hk_dwell = 0
    shekou_pts = 0
    shekou_vessels = set()
    yantian_pts = 0
    yantian_vessels = set()

    for ds in sorted(pos_idx):
        with open(pos_idx[ds], newline="", encoding="utf-8",
                  errors="replace") as fh:
            for r in csv.DictReader(fh):
                try:
                    lat = float(clean(r.get("ais_position_latitude")))
                    lon = float(clean(r.get("ais_position_longitude")))
                except (TypeError, ValueError):
                    continue
                if not (OUTER[0] <= lat <= OUTER[1] and OUTER[2] <= lon <= OUTER[3]):
                    continue
                if lat == 0.0 and lon == 0.0:
                    continue
                m = clean(r.get("ais_position_mmsi"))
                for z, box in ZONES.items():
                    if in_box(lat, lon, box):
                        zone_points[z] += 1
                        if m:
                            zone_vessels[z].add(m)
                # HK transit vs dwell
                if in_box(lat, lon, ZONES["Hong Kong"]):
                    sp_raw = clean(r.get("ais_position_speed"))
                    try:
                        sp = float(sp_raw)
                        if sp > 3.0:
                            hk_transit += 1
                        else:
                            hk_dwell += 1
                    except (TypeError, ValueError):
                        hk_dwell += 1  # invalid/0 speed treated as dwell/anchored
                if in_box(lat, lon, SHEKOU_CHIWAN):
                    shekou_pts += 1
                    if m:
                        shekou_vessels.add(m)
                if in_box(lat, lon, YANTIAN):
                    yantian_pts += 1
                    if m:
                        yantian_vessels.add(m)

    # Destination-based arrivals
    dest_vessels = defaultdict(set)
    dest_rows = defaultdict(int)
    for ds in sorted(cap_idx):
        with open(cap_idx[ds], newline="", encoding="utf-8",
                  errors="replace") as fh:
            for r in csv.DictReader(fh):
                m = clean(r.get("ais_capts_mmsi"))
                d = clean(r.get("ais_capts_destination"))
                if not m or not d or d == "0000-00-00 00:00:00":
                    continue
                p = dest_port(d)
                if p:
                    dest_vessels[p].add(m)
                    dest_rows[p] += 1

    return {
        "zone_vessels": {z: len(zone_vessels[z]) for z in ZONES},
        "zone_points": dict(zone_points),
        "dest_vessels": {p: len(dest_vessels[p]) for p in PORT_KEYWORDS},
        "dest_rows": dict(dest_rows),
        "hk_transit_points": hk_transit,
        "hk_dwell_points": hk_dwell,
        "shekou_chiwAN_points": shekou_pts,
        "shekou_chiwAN_vessels": len(shekou_vessels),
        "yantian_points": yantian_pts,
        "yantian_vessels": len(yantian_vessels),
    }


def main():
    results = {}
    for year in (2024, 2025):
        print(f"auditing {year} ...")
        results[year] = audit_year(year)

    with open(os.path.join(OUT, "prd_zone_audit.json"), "w",
              encoding="utf-8") as fh:
        json.dump({"generated_utc": datetime.now(timezone.utc).isoformat(),
                   "zones": {k: list(v) for k, v in ZONES.items()},
                   "sub_boxes": {"shekou_chiwan": list(SHEKOU_CHIWAN),
                                 "yantian": list(YANTIAN)},
                   "results": results}, fh, indent=2)

    for year in (2024, 2025):
        r = results[year]
        print(f"\n=== {year} ===")
        print("A. Destination-based distinct vessels (heading TO port):")
        for p in PORT_KEYWORDS:
            print(f"   {p:10s} vessels={r['dest_vessels'][p]:6d}  "
                  f"dest_rows={r['dest_rows'][p]:7d}")
        print("B. Zone-box presence (current dashboard boxes):")
        for z in ZONES:
            print(f"   {z:10s} vessels={r['zone_vessels'][z]:6d}  "
                  f"points={r['zone_points'][z]:7d}")
        hk_tot = r["hk_transit_points"] + r["hk_dwell_points"]
        print(f"D. HK box speed split: transit(>3kn)={r['hk_transit_points']} "
              f"({r['hk_transit_points']/hk_tot*100:.1f}%), "
              f"dwell(<=3/invalid)={r['hk_dwell_points']} "
              f"({r['hk_dwell_points']/hk_tot*100:.1f}%) of {hk_tot}")
        print(f"C. Boundary sub-boxes:")
        print(f"   Shekou/Chiwan (in HK box): points={r['shekou_chiwAN_points']} "
              f"vessels={r['shekou_chiwAN_vessels']}")
        print(f"   Yantian (in SZ box):       points={r['yantian_points']} "
              f"vessels={r['yantian_vessels']}")

    print("\nwrote", os.path.join(OUT, "prd_zone_audit.json"))


if __name__ == "__main__":
    main()
