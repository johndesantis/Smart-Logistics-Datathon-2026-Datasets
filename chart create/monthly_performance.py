#!/usr/bin/env python3
import os, csv
from collections import defaultdict

OUT = "/home/haha/Downloads/analysis_output"
CAPTS_DIRS = {
    2024: "/home/haha/Downloads/3-2. AIS Data/2024 Data/captain info/2024",
    2025: "/home/haha/Downloads/3-2. AIS Data/2025 Data/captain info 2025",
}

def main():
    rows_out = []
    for year in (2024, 2025):
        idx_path = os.path.join(OUT, f"daily_last_captain_{year}.txt")
        index = {}
        with open(idx_path, encoding='utf-8') as fh:
            for line in fh:
                line = line.rstrip('\n')
                if not line:
                    continue
                date_str, fname = line.split('\t')
                index[date_str] = fname
        month_stats = defaultdict(lambda: {'snapshots': 0, 'mmsis': set(), 'records': 0, 'unparseable_eta': 0})
        for date_str in sorted(index):
            fpath = os.path.join(CAPTS_DIRS[year], index[date_str])
            year_m = int(date_str[:4]); month_m = int(date_str[4:6])
            ms = month_stats[(year_m, month_m)]
            ms['snapshots'] += 1
            with open(fpath, newline='', encoding='utf-8', errors='replace') as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    ms['records'] += 1
                    mmsi = (row.get('ais_capts_mmsi') or '').strip()
                    if mmsi:
                        ms['mmsis'].add(mmsi)
                    eta = (row.get('ais_capts_eta') or '').strip()
                    if eta.startswith("[BAD]") or eta == "" or eta == "0000-00-00 00:00:00":
                        ms['unparseable_eta'] += 1
        for (y, m), ms in sorted(month_stats.items()):
            rows_out.append({
                'year': y, 'month': m,
                'snapshots': ms['snapshots'],
                'distinct_vessels': len(ms['mmsis']),
                'records': ms['records'],
                'unparseable_eta': ms['unparseable_eta'],
            })

    with open(os.path.join(OUT, 'monthly_performance.csv'), 'w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh)
        w.writerow(['year', 'month', 'snapshots', 'distinct_vessels', 'records', 'unparseable_eta'])
        for r in rows_out:
            w.writerow([r['year'], r['month'], r['snapshots'], r['distinct_vessels'], r['records'], r['unparseable_eta']])

    print("=== Monthly Performance ===")
    for r in rows_out:
        print(f"  {r['year']}-{r['month']:02d}: snapshots={r['snapshots']}, vessels={r['distinct_vessels']}, records={r['records']}, unparseable_eta={r['unparseable_eta']}")
    if rows_out:
        first = rows_out[0]; last = rows_out[-1]
        peak = max(rows_out, key=lambda r: r['distinct_vessels'])
        print(f"  First: {first['year']}-{first['month']:02d}; Last: {last['year']}-{last['month']:02d}; Peak vessels: {peak['year']}-{peak['month']:02d} ({peak['distinct_vessels']})")

if __name__ == '__main__':
    main()