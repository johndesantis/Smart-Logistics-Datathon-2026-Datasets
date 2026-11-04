#!/usr/bin/env python3
"""Deduplicate flagged captain cells CSVs by entire attribute cells."""
import csv
from pathlib import Path

FILES = [
    Path("/home/haha/Downloads/flaggedcaptaincells2024.csv"),
    Path("/home/haha/Downloads/flaggedcaptaincells2025.csv"),
]


def deduplicate(path):
    original = 0
    kept = 0
    removed = 0
    seen = set()

    with open(path, "r", encoding="utf-8", newline="") as infile:
        reader = csv.reader(infile)
        header = next(reader)
        rows = list(reader)

    out_rows = []
    for row in rows:
        original += 1
        key = tuple(row[6:]) if len(row) >= 7 else tuple(row)
        if key in seen:
            removed += 1
            continue
        seen.add(key)
        out_rows.append(row)
        kept += 1

    with open(path, "w", encoding="utf-8", newline="") as outfile:
        writer = csv.writer(outfile)
        writer.writerow(header)
        writer.writerows(out_rows)

    return original, kept, removed


for f in FILES:
    o, k, r = deduplicate(f)
    print(f"{f.name}: original {o}, kept {k}, removed {r}")
