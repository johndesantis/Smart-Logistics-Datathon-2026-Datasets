#!/usr/bin/env python3
import os, csv, glob, json, re, subprocess, math, statistics
from datetime import datetime, timedelta
import calendar

OUT = "/home/haha/Downloads/analysis_output"
os.makedirs(OUT, exist_ok=True)

CAPTS_DIRS = {
    2024: "/home/haha/Downloads/3-2. AIS Data/2024 Data/captain info/2024",
    2025: "/home/haha/Downloads/3-2. AIS Data/2025 Data/captain info 2025",
}
POS_DIRS = {
    2024: "/home/haha/Downloads/3-2. AIS Data/2024 Data/position info/2024",
    2025: "/home/haha/Downloads/3-2. AIS Data/2025 Data/position info 2025",
}

TS_FMT = "%Y-%m-%d %H:%M:%S"
VOYAGE_COLS = ['voyage_id','mmsi','ship_id','vessel_name','destination','voyage_start','t_last_update','eta','dt_hours','bottleneck_pct','n_records','snapshot_files']
POS_HEADER_CACHE = {}

def parse_ts(s):
    if s is None:
        return None
    s = s.strip()
    if s.startswith("[BAD]"):
        return None
    if s == "" or s == "0000-00-00 00:00:00":
        return None
    try:
        return datetime.strptime(s, TS_FMT)
    except ValueError:
        return None

def to_epoch(dt):
    return calendar.timegm(dt.timetuple()) if dt else None

def epoch_to_str(ep):
    if ep is None:
        return ""
    return datetime.utcfromtimestamp(ep).strftime(TS_FMT)

def daily_last_index(directory, prefix):
    by_date = {}
    for f in glob.glob(os.path.join(directory, prefix)):
        b = os.path.basename(f)
        m = re.match(r".*-(\d{8})T(\d{6})Z\.csv$", b)
        if not m:
            continue
        date_str = m.group(1)
        sec = int(m.group(2))
        if date_str not in by_date or sec > by_date[date_str][0]:
            by_date[date_str] = (sec, f)
    return {d: v[1] for d, v in by_date.items()}

def build_daily_sample(year):
    idx = daily_last_index(CAPTS_DIRS[year], "capts-*.csv")
    records = []
    unparseable_eta = 0
    unparseable_ts = 0
    n_read = 0
    for date_str in sorted(idx):
        f = idx[date_str]
        snap_epoch = calendar.timegm(datetime.strptime(date_str, "%Y%m%d").timetuple())
        with open(f, newline='', encoding='utf-8', errors='replace') as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                n_read += 1
                mmsi = (row.get('ais_capts_mmsi') or '').strip()
                if not mmsi:
                    continue
                eta_dt = parse_ts(row.get('ais_capts_eta'))
                if eta_dt is None:
                    unparseable_eta += 1
                eta_ep = to_epoch(eta_dt)
                cl_dt = parse_ts(row.get('ais_capts_last'))
                if cl_dt is None:
                    unparseable_ts += 1
                    continue
                cl_ep = to_epoch(cl_dt)
                dest = (row.get('ais_capts_destination') or '').strip()
                records.append((
                    mmsi,
                    (row.get('ais_ship_id') or '').strip(),
                    (row.get('ais_capts_name') or '').strip(),
                    dest.lower(),
                    dest,
                    eta_ep,
                    cl_ep,
                    snap_epoch,
                    os.path.basename(f),
                ))
    return records, unparseable_eta, unparseable_ts, n_read, idx

def make_voyage(mmsi, n, recs):
    recs = sorted(recs, key=lambda r: r[6])
    last = recs[-1]
    first = recs[0]
    cl_ep = last[6]
    eta_ep = last[5]
    dt = None
    if eta_ep is not None:
        dt = (eta_ep - cl_ep) / 3600.0
    bottleneck = None
    if dt is not None:
        bottleneck = max(0.0, min(100.0, (max(dt, 0.0) / 72.0) * 100.0))
    return {
        'voyage_id': f"{mmsi}_V{n}",
        'mmsi': mmsi,
        'ship_id': last[1],
        'vessel_name': last[2],
        'destination': last[4],
        'voyage_start': first[6],
        't_last_update': cl_ep,
        'eta': eta_ep,
        'dt_hours': dt,
        'bottleneck_pct': bottleneck,
        'n_records': len(recs),
        'snapshot_files': ';'.join(sorted(set(r[8] for r in recs))),
    }

def segment(records):
    by_mmsi = {}
    for r in records:
        by_mmsi.setdefault(r[0], []).append(r)
    voyages = []
    for mmsi in sorted(by_mmsi):
        recs = sorted(by_mmsi[mmsi], key=lambda r: r[6])
        cur = []
        prev_t = None
        prev_dest = None
        n = 0
        for r in recs:
            t = r[6]
            dest = r[3]
            new = False
            if prev_t is not None:
                if t - prev_t > 72*3600:
                    new = True
                elif dest != "" and prev_dest is not None and dest != prev_dest:
                    new = True
            if new:
                n += 1
                voyages.append(make_voyage(mmsi, n, cur))
                cur = []
            cur.append(r)
            prev_t = t
            if dest != "":
                prev_dest = dest
        if cur:
            n += 1
            voyages.append(make_voyage(mmsi, n, cur))
    return voyages

def pct(sorted_vals, p):
    if not sorted_vals:
        return None
    n = len(sorted_vals)
    k = (p/100.0)*(n-1)
    f = int(math.floor(k)); c = int(math.ceil(k))
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f]*(c-k) + sorted_vals[c]*(k-f)

def compute_summary(year, voyages, unparseable_eta, unparseable_ts, n_records_total):
    valid = [v for v in voyages if v['dt_hours'] is not None]
    dts = sorted(v['dt_hours'] for v in valid)
    botts = sorted(v['bottleneck_pct'] for v in valid)
    overdue = sum(1 for v in valid if v['dt_hours'] < 0)
    total = len(voyages)
    cov = (len(valid)/total*100.0) if total else 0.0
    vessels = len(set(v['mmsi'] for v in voyages))
    mean_rec = statistics.mean([v['n_records'] for v in voyages]) if voyages else 0.0
    return {
        'year': year,
        'total_voyages': total,
        'valid_pairs': len(valid),
        'coverage_pct': round(cov, 4),
        'distinct_vessels': vessels,
        'unparseable_eta_count': unparseable_eta,
        'unparseable_timestamp_count': unparseable_ts,
        'total_daily_records': n_records_total,
        'mean_records_per_voyage': round(mean_rec, 4),
        'dt_stats': {
            'mean': round(statistics.mean(dts), 4) if dts else None,
            'median': round(statistics.median(dts), 4) if dts else None,
            'min': round(dts[0], 4) if dts else None,
            'max': round(dts[-1], 4) if dts else None,
            'p10': round(pct(dts, 10), 4) if dts else None,
            'p90': round(pct(dts, 90), 4) if dts else None,
        },
        'overdue_pct': round(overdue/len(valid)*100.0, 4) if valid else 0.0,
        'bottleneck_stats': {
            'mean': round(statistics.mean(botts), 4) if botts else None,
            'median': round(statistics.median(botts), 4) if botts else None,
            'max': round(botts[-1], 4) if botts else None,
            'p90': round(pct(botts, 90), 4) if botts else None,
            'pct_ge_50': round(sum(1 for b in botts if b>=50)/len(botts)*100.0, 4) if botts else 0.0,
            'pct_ge_80': round(sum(1 for b in botts if b>=80)/len(botts)*100.0, 4) if botts else 0.0,
            'pct_eq_100': round(sum(1 for b in botts if b==100.0)/len(botts)*100.0, 4) if botts else 0.0,
        },
    }

def write_voyages(year, voyages, path):
    with open(path, 'w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh)
        w.writerow(VOYAGE_COLS)
        for v in voyages:
            w.writerow([
                v['voyage_id'], v['mmsi'], v['ship_id'], v['vessel_name'], v['destination'],
                epoch_to_str(v['voyage_start']), epoch_to_str(v['t_last_update']),
                epoch_to_str(v['eta']),
                '' if v['dt_hours'] is None else round(v['dt_hours'], 6),
                '' if v['bottleneck_pct'] is None else round(v['bottleneck_pct'], 6),
                v['n_records'], v['snapshot_files'],
            ])

def top_voyages(voyages, k=15):
    valid = [v for v in voyages if v['bottleneck_pct'] is not None]
    valid.sort(key=lambda v: (-v['bottleneck_pct'], -(v['dt_hours'] if v['dt_hours'] else 0)))
    return valid[:k]

def get_pos_header(year, fpath):
    if year not in POS_HEADER_CACHE:
        with open(fpath, newline='', encoding='utf-8', errors='replace') as fh:
            POS_HEADER_CACHE[year] = fh.readline().strip().split(',')
    return POS_HEADER_CACHE[year]

def parse_pos_line(line, header):
    parts = line.split(',')
    if len(parts) != len(header):
        return None
    return dict(zip(header, parts))

def find_last_position(year, mmsi, t_last_ep):
    t_last_dt = datetime.utcfromtimestamp(t_last_ep)
    dates = [(t_last_dt + timedelta(days=off)).strftime('%Y%m%d') for off in (-1, 0, 1)]
    pos_dir = POS_DIRS[year]
    files = []
    for d in dates:
        files.extend(glob.glob(os.path.join(pos_dir, f"positions-{d}T*.csv")))
    if not files:
        return None
    header = get_pos_header(year, files[0])
    cmd = ['grep', '-H', '-F', mmsi] + files
    res = subprocess.run(cmd, capture_output=True, text=True)
    best = None
    best_diff = None
    for line in res.stdout.splitlines():
        idxc = line.find(':')
        if idxc < 0:
            continue
        fpath = line[:idxc]
        content = line[idxc+1:]
        row = parse_pos_line(content, header)
        if row is None:
            continue
        if (row.get('ais_position_mmsi') or '').strip() != mmsi:
            continue
        pt = parse_ts(row.get('ais_position_timestamp'))
        if pt is None:
            continue
        diff = abs(calendar.timegm(pt.timetuple()) - t_last_ep)
        if best_diff is None or diff < best_diff:
            best_diff = diff
            best = {
                'position_latitude': (row.get('ais_position_latitude') or '').strip(),
                'position_longitude': (row.get('ais_position_longitude') or '').strip(),
                'position_speed': (row.get('ais_position_speed') or '').strip(),
                'position_course': (row.get('ais_position_course') or '').strip(),
                'position_heading': (row.get('ais_position_heading') or '').strip(),
                'position_nav_status_desc': (row.get('nav_status_desc') or '').strip(),
                'position_timestamp': (row.get('ais_position_timestamp') or '').strip(),
                'position_source_file': os.path.basename(fpath),
                'position_time_offset_hours': round(diff/3600.0, 6),
            }
    return best

def write_top_voyages(year, tops, path):
    pos_cols = ['position_latitude','position_longitude','position_speed','position_course','position_heading','position_nav_status_desc','position_timestamp','position_source_file','position_time_offset_hours']
    cols = VOYAGE_COLS + pos_cols
    with open(path, 'w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for v in tops:
            pos = v.get('position')
            row = [v[c] for c in VOYAGE_COLS]
            row += [pos[c] if pos else '' for c in pos_cols]
            w.writerow(row)

def get_vessel_track(year, mmsi, start_ep, end_ep):
    idx = daily_last_index(POS_DIRS[year], 'positions-*.csv')
    rows = []
    cur_dt = datetime.utcfromtimestamp(start_ep)
    end_dt = datetime.utcfromtimestamp(end_ep)
    while cur_dt <= end_dt:
        date_str = cur_dt.strftime('%Y%m%d')
        if date_str in idx:
            f = idx[date_str]
            with open(f, newline='', encoding='utf-8', errors='replace') as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    if (row.get('ais_position_mmsi') or '').strip() == mmsi:
                        rows.append((date_str, row))
        cur_dt += timedelta(days=1)
    return rows

def track_stats(rows):
    speeds = []
    headings = []
    nav_changes = 0
    prev_nav = None
    for date_str, row in rows:
        sp = None
        try:
            sp = float(row.get('ais_position_speed') or '')
        except ValueError:
            sp = None
        if sp is not None:
            speeds.append(sp)
        hd = None
        try:
            hd = float(row.get('ais_position_heading') or '')
        except ValueError:
            hd = None
        if hd is not None and hd >= 0:
            headings.append(hd)
        nav = (row.get('nav_status_desc') or '').strip()
        if prev_nav is not None and nav != prev_nav:
            nav_changes += 1
        prev_nav = nav
    return {
        'mean_speed': round(statistics.mean(speeds), 4) if speeds else None,
        'min_speed': round(min(speeds), 4) if speeds else None,
        'max_speed': round(max(speeds), 4) if speeds else None,
        'nav_status_changes': nav_changes,
        'heading_range': round(max(headings)-min(headings), 4) if headings else None,
        'n_pos_rows': len(rows),
    }

def write_track_csv(year, mmsi, rows, path):
    with open(path, 'w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh)
        w.writerow(['date','latitude','longitude','speed','course','nav_status_desc'])
        for date_str, row in rows:
            w.writerow([
                date_str,
                (row.get('ais_position_latitude') or '').strip(),
                (row.get('ais_position_longitude') or '').strip(),
                (row.get('ais_position_speed') or '').strip(),
                (row.get('ais_position_course') or '').strip(),
                (row.get('nav_status_desc') or '').strip(),
            ])

def flagged_matches(top_mmsis, year):
    files = {
        2024: ["/home/haha/Downloads/flaggedcaptaincells2024.csv", "/home/haha/Downloads/flaggedpositioncells2024.csv"],
        2025: ["/home/haha/Downloads/flaggedcaptaincells2025.csv", "/home/haha/Downloads/flaggedpositioncells2025.csv"],
    }[year]
    matches = []
    for fp in files:
        if not os.path.exists(fp):
            continue
        mmsi_col = 'ais_capts_mmsi' if 'captain' in os.path.basename(fp) else 'ais_position_mmsi'
        with open(fp, newline='', encoding='utf-8', errors='replace') as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                m = (row.get(mmsi_col) or '').strip()
                if m in top_mmsis:
                    matches.append({
                        'source_file': os.path.basename(fp),
                        'mmsi': m,
                        'flagged_column_count': row.get('flagged_column_count',''),
                        'flagged_columns': row.get('flagged_columns',''),
                        'flagged_reasons': row.get('flagged_reasons',''),
                    })
    return matches

def main():
    all_summaries = {}
    all_tops = {}
    for year in (2024, 2025):
        print(f"=== Processing {year} ===")
        records, unparseable_eta, unparseable_ts, n_read, idx = build_daily_sample(year)
        print(f"  daily snapshots: {len(idx)}, records read: {n_read}, records kept: {len(records)}")
        print(f"  unparseable eta: {unparseable_eta}, unparseable timestamp: {unparseable_ts}")
        with open(os.path.join(OUT, f"daily_last_captain_{year}.txt"), 'w', encoding='utf-8') as fh:
            for d in sorted(idx):
                fh.write(f"{d}\t{os.path.basename(idx[d])}\n")
        voyages = segment(records)
        print(f"  voyages: {len(voyages)}, distinct vessels: {len(set(v['mmsi'] for v in voyages))}")
        summary = compute_summary(year, voyages, unparseable_eta, unparseable_ts, n_read)
        all_summaries[year] = summary
        write_voyages(year, voyages, os.path.join(OUT, f"voyages_{year}.csv"))
        tops = top_voyages(voyages, 15)
        all_tops[year] = tops
        print(f"  top {len(tops)} selected")
        for v in tops:
            pos = find_last_position(year, v['mmsi'], v['t_last_update'])
            v['position'] = pos
            print(f"    {v['voyage_id']} mmsi={v['mmsi']} bn={v['bottleneck_pct']} dt={v['dt_hours']} pos_found={pos is not None}")
        write_top_voyages(year, tops, os.path.join(OUT, f"top_voyages_{year}.csv"))

    # Task 3: top 5 tracks
    top5_stats = {}
    for year in (2024, 2025):
        tops5 = all_tops[year][:5]
        stats_list = []
        for v in tops5:
            rows = get_vessel_track(year, v['mmsi'], v['voyage_start'], v['t_last_update'])
            st = track_stats(rows)
            stats_list.append({
                'voyage_id': v['voyage_id'],
                'mmsi': v['mmsi'],
                'vessel_name': v['vessel_name'],
                'destination': v['destination'],
                'voyage_start': epoch_to_str(v['voyage_start']),
                't_last_update': epoch_to_str(v['t_last_update']),
                **st,
            })
            write_track_csv(year, v['mmsi'], rows, os.path.join(OUT, f"voyage_tracks_top5_{year}_{v['mmsi']}.csv"))
        top5_stats[year] = stats_list
        print(f"  {year} top5 tracks done")

    # Task 4: flagged cross-ref
    flagged_results = {}
    for year in (2024, 2025):
        tops_mmsis = set(v['mmsi'] for v in all_tops[year])
        matches = flagged_matches(tops_mmsis, year)
        # attach voyage ids
        for m in matches:
            m['voyage_ids'] = sorted(set(v['voyage_id'] for v in all_tops[year] if v['mmsi'] == m['mmsi']))
        flagged_results[year] = matches
        print(f"  {year} flagged matches: {len(matches)}")

    # Write summary JSON
    summary_out = {
        'methodology': 'ETA-based arrival timing inefficiency and bottleneck metrics from AIS captain data',
        'assumptions': 'Timestamps naive treated as UTC; daily sample = last captain snapshot per UTC day; T_expected=72.0h constant; bottleneck = clamp(max(dt,0)/72*100,0,100)',
    }
    summary_out['years'] = {}
    for year in (2024, 2025):
        summary_out['years'][str(year)] = {
            **all_summaries[year],
            'top15': [
                {
                    'voyage_id': v['voyage_id'], 'mmsi': v['mmsi'], 'vessel_name': v['vessel_name'],
                    'destination': v['destination'], 'dt_hours': round(v['dt_hours'],6) if v['dt_hours'] is not None else None,
                    'bottleneck_pct': round(v['bottleneck_pct'],6) if v['bottleneck_pct'] is not None else None,
                    'position': v.get('position'),
                }
                for v in all_tops[year]
            ],
            'top5_track_stats': top5_stats[year],
            'flagged_crossref': flagged_results[year],
        }
    with open(os.path.join(OUT, 'eta_summary.json'), 'w', encoding='utf-8') as fh:
        json.dump(summary_out, fh, indent=2)

    # Methodology txt
    with open(os.path.join(OUT, 'eta_methodology.txt'), 'w', encoding='utf-8') as fh:
        fh.write("ETA-Based Arrival Timing Inefficiency and Bottleneck Metrics\n")
        fh.write("============================================================\n\n")
        fh.write("SAMPLING (daily-last)\n")
        fh.write("---------------------\n")
        fh.write("For each UTC day and each year (2024, 2025), the LAST captain snapshot of the day is selected:\n")
        fh.write("the file capts-YYYYMMDDTHHMMSSZ.csv with the maximum HHMMSS (timestamp) in the filename.\n")
        fh.write("One record per vessel per day is extracted: mmsi, ship_id, name, destination, eta, capts_last, snapshot_date.\n")
        fh.write("The daily-last index is written to daily_last_captain_YYYY.txt (date\\tfilename).\n\n")
        fh.write("FIELD EXTRACTION & PARSING\n")
        fh.write("--------------------------\n")
        fh.write("ais_capts_eta and ais_capts_last are parsed as naive UTC timestamps (%Y-%m-%d %H:%M:%S).\n")
        fh.write("Values with a '[BAD]' prefix, the string '0000-00-00 00:00:00', or empty strings are unparseable.\n")
        fh.write("If capts_last is unparseable, the record is dropped and counted (unparseable_timestamp_count).\n")
        fh.write("If eta is unparseable, the record is kept (for segmentation) but eta=None and counted (unparseable_eta_count).\n\n")
        fh.write("VOYAGE SEGMENTATION (per vessel by mmsi)\n")
        fh.write("----------------------------------------\n")
        fh.write("Records for a vessel are sorted by capts_last (ascending). A new voyage starts when:\n")
        fh.write("  (a) gap between consecutive capts_last > 72 hours, OR\n")
        fh.write("  (b) destination changes (case-insensitive comparison, only when destination is non-empty).\n")
        fh.write("voyage_id = f\"{mmsi}_V{n\"\"}\" assigned sequentially per vessel.\n\n")
        fh.write("PER VOYAGE COMPUTATION\n")
        fh.write("----------------------\n")
        fh.write("t_last_captain_update = max(capts_last) in voyage.\n")
        fh.write("ETA = eta value on the record with max capts_last (latest record).\n")
        fh.write("destination = destination of that record.\n")
        fh.write("voyage_start = min(capts_last) in voyage.\n")
        fh.write("n_records = number of daily records in voyage.\n\n")
        fh.write("DELTA T AND BOTTLENECK\n")
        fh.write("----------------------\n")
        fh.write("dt_hours = (ETA_utc - t_last_update_utc) in hours, signed.\n")
        fh.write("  negative = update after ETA (overdue); positive = time remaining.\n")
        fh.write("T_expected_hours = 72.0 (conservative default approach window; no port-call data exists to derive per-voyage approach windows).\n")
        fh.write("bottleneck_pct = clamp( (max(dt_hours, 0) / 72.0) * 100, 0, 100 ).\n")
        fh.write("Never divide by zero (72.0 is constant).\n\n")
        fh.write("COVERAGE\n")
        fh.write("--------\n")
        fh.write("coverage %% = (voyages with BOTH valid ETA and valid final update) / (all segmented voyages) * 100, per year.\n")
        fh.write("distinct vessels covered = count of distinct mmsi in voyages.\n\n")
        fh.write("TOP VOYAGES & POSITIONS\n")
        fh.write("-----------------------\n")
        fh.write("Top 15 voyages per year by bottleneck_pct (ties broken by larger dt_hours).\n")
        fh.write("For each, the vessel's last known position at or nearest to t_last_update is found by grepping the MMSI\n")
        fh.write("across position snapshot files positions-YYYYMMDDT*.csv for the UTC date of t_last_update and the day before/after,\n")
        fh.write("verifying the mmsi column matches exactly, and selecting the position row with timestamp closest to t_last_update.\n")
        fh.write("Position columns: latitude, longitude, speed, course, heading, nav_status_desc, position_timestamp, source_file,\n")
        fh.write("time_offset_hours (vs t_last_update). Empty if MMSI not found near t_last_update.\n\n")
        fh.write("SPEED / BEHAVIOR EVIDENCE (top 5 per year)\n")
        fh.write("------------------------------------------\n")
        fh.write("From daily-last position snapshots (one per UTC day), the vessel's rows are extracted across its voyage window\n")
        fh.write("[voyage_start, t_last_update]. Computed per voyage: mean speed, min speed, max speed, count of nav_status changes,\n")
        fh.write("heading change range (max - min over headings >= 0).\n\n")
        fh.write("FLAGGED CROSS-REFERENCE\n")
        fh.write("-----------------------\n")
        fh.write("Top-15 voyage vessels (by mmsi) are grepped in flaggedcaptaincellsYYYY.csv and flaggedpositioncellsYYYY.csv.\n")
        fh.write("Matches are reported with flagged reasons.\n\n")
        fh.write("ASSUMPTIONS AND LIMITATIONS\n")
        fh.write("---------------------------\n")
        fh.write("- All timestamps are naive; treated as UTC (documented assumption).\n")
        fh.write("- Daily sampling granularity is 1 day; intra-day movements between snapshots are not captured.\n")
        fh.write("- ETA staleness: eta may not be refreshed between daily snapshots; dt reflects time from last captain update to stored ETA.\n")
        fh.write("- No port-call ground truth exists, so T_expected is a fixed 72-hour conservative default.\n")
        fh.write("- Position lookup uses the nearest position snapshot to t_last_update; may be hours off if no snapshot exists near that time.\n")
        fh.write("- [BAD]-prefixed values are treated as unparseable for eta/timestamps.\n")
        fh.write("- Source data is not modified; all outputs are deterministic.\n")

    print("\n=== DONE ===")
    for year in (2024, 2025):
        s = all_summaries[year]
        print(f"{year}: voyages={s['total_voyages']} valid={s['valid_pairs']} coverage={s['coverage_pct']}% vessels={s['distinct_vessels']}")
        print(f"   dt mean={s['dt_stats']['mean']} median={s['dt_stats']['median']} min={s['dt_stats']['min']} max={s['dt_stats']['max']} p10={s['dt_stats']['p10']} p90={s['dt_stats']['p90']}")
        print(f"   overdue={s['overdue_pct']}% bottleneck mean={s['bottleneck_stats']['mean']} median={s['bottleneck_stats']['median']} max={s['bottleneck_stats']['max']} p90={s['bottleneck_stats']['p90']}")
        print(f"   >=50={s['bottleneck_stats']['pct_ge_50']}% >=80={s['bottleneck_stats']['pct_ge_80']}% ==100={s['bottleneck_stats']['pct_eq_100']}%")

if __name__ == '__main__':
    main()
