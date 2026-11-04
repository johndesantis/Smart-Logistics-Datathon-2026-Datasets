#!/usr/bin/env python3
"""
Pearl River Delta port comparison: Hong Kong vs Shenzhen vs Guangzhou.

Scans the daily-last position and captain snapshots for 2024 and 2025,
assigns vessels to approximate port zones, and computes per port / per year:
  - vessel arrivals (distinct MMSIs observed in the zone)
  - traffic density (position points in the zone)
  - vessel size mix (from ais_capts_length; no vessel-type field exists)
  - shipping-route connectivity (distinct reported destinations of zone vessels)
  - monthly distinct-vessel trend

Then renders analysis_output/prd_comparison.png and writes
analysis_output/prd_metrics.json + prd_port_summary.csv, and prints a verdict
on whether Hong Kong is losing shipping connections or simply handling fewer
vessels.

NOTE ON ZONES: the three ports sit within ~80 km of each other in the Pearl
River Delta, so zones are approximate, non-overlapping bounding boxes
(documented below). They are proxies, not official port limits.

Run: python3 prd_analysis.py
"""
import csv
import json
import os
import re
import glob
from collections import defaultdict
from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.lines import Line2D

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

# (lat_min, lat_max, lon_min, lon_max) — approximate, non-overlapping proxies
PORTS = {
    "Hong Kong": (22.05, 22.55, 113.80, 114.50),
    "Shenzhen":  (22.55, 22.85, 113.80, 114.50),
    "Guangzhou": (22.60, 23.40, 113.10, 113.80),
}
PORT_COLORS = {"Hong Kong": "#ff5b5b", "Shenzhen": "#3fa7ff", "Guangzhou": "#4ecdc4"}
OUTER = (21.8, 23.6, 112.9, 114.7)  # prefilter bbox
SIZE_ORDER = ["<100 m", "100-200 m", "200-300 m", ">300 m", "Unknown"]
BG, PANEL, GRID, TXT, MUTED = "#0d1b2a", "#10233a", "#4a5b6b", "#c8d3de", "#9fb3c8"


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


def zone_of(lat, lon):
    for name, (la0, la1, lo0, lo1) in PORTS.items():
        if la0 <= lat <= la1 and lo0 <= lon <= lo1:
            return name
    return None


def size_class(L):
    if L is None or L <= 0:
        return "Unknown"
    if L < 100:
        return "<100 m"
    if L < 200:
        return "100-200 m"
    if L < 300:
        return "200-300 m"
    return ">300 m"


def analyze_year(year):
    pos_idx = daily_last_index(POS_DIRS[year], "positions-*.csv")
    cap_idx = daily_last_index(CAP_DIRS[year], "capts-*.csv")
    zone_points = defaultdict(int)
    zone_vessels = defaultdict(set)
    zone_month = defaultdict(set)
    zone_pts = defaultdict(list)

    for ds in sorted(pos_idx):
        month = ds[:6]
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
                z = zone_of(lat, lon)
                if not z:
                    continue
                m = clean(r.get("ais_position_mmsi"))
                zone_points[z] += 1
                if m:
                    zone_vessels[z].add(m)
                    zone_month[(z, month)].add(m)
                if len(zone_pts[z]) < 5000:
                    zone_pts[z].append((lon, lat))

    dest_by_mmsi = defaultdict(set)
    len_by_mmsi = {}
    for ds in sorted(cap_idx):
        with open(cap_idx[ds], newline="", encoding="utf-8",
                  errors="replace") as fh:
            for r in csv.DictReader(fh):
                m = clean(r.get("ais_capts_mmsi"))
                if not m:
                    continue
                d = clean(r.get("ais_capts_destination"))
                if d and d != "0000-00-00 00:00:00":
                    dest_by_mmsi[m].add(d)
                try:
                    L = float(clean(r.get("ais_capts_length")))
                    if L > 0 and (m not in len_by_mmsi or L > len_by_mmsi[m]):
                        len_by_mmsi[m] = L
                except (TypeError, ValueError):
                    pass

    ports = {}
    for z in PORTS:
        vessels = zone_vessels[z]
        dests = set()
        sizes = defaultdict(int)
        for m in vessels:
            dests |= dest_by_mmsi.get(m, set())
            sizes[size_class(len_by_mmsi.get(m))] += 1
        months = sorted({mm for (zz, mm) in zone_month if zz == z})
        ports[z] = {
            "arrivals_distinct_vessels": len(vessels),
            "traffic_density_points": zone_points[z],
            "distinct_destinations": len(dests),
            "top_destinations": sorted(dests)[:15],
            "size_classes": {k: sizes.get(k, 0) for k in SIZE_ORDER},
            "monthly_distinct_vessels": {m: len(zone_month[(z, m)]) for m in months},
        }
    return ports, zone_pts


def pct_change(a, b):
    return round((b - a) / a * 100, 2) if a else None


def main():
    data = {}
    pts = {}
    for year in (2024, 2025):
        print(f"scanning {year} ...")
        data[year], pts[year] = analyze_year(year)

    # ---- summary + deltas ----------------------------------------------
    summary = {}
    for z in PORTS:
        a, b = data[2024][z], data[2025][z]
        summary[z] = {
            "arrivals_2024": a["arrivals_distinct_vessels"],
            "arrivals_2025": b["arrivals_distinct_vessels"],
            "arrivals_pct": pct_change(a["arrivals_distinct_vessels"],
                                       b["arrivals_distinct_vessels"]),
            "density_2024": a["traffic_density_points"],
            "density_2025": b["traffic_density_points"],
            "density_pct": pct_change(a["traffic_density_points"],
                                      b["traffic_density_points"]),
            "destinations_2024": a["distinct_destinations"],
            "destinations_2025": b["distinct_destinations"],
            "destinations_pct": pct_change(a["distinct_destinations"],
                                           b["distinct_destinations"]),
            "size_2024": a["size_classes"],
            "size_2025": b["size_classes"],
            "top_destinations_2025": b["top_destinations"],
        }

    # ---- verdict --------------------------------------------------------
    hk = summary["Hong Kong"]
    sz = summary["Shenzhen"]
    gz = summary["Guangzhou"]
    verdict_lines = []
    verdict_lines.append(
        f"Hong Kong arrivals {hk['arrivals_2024']:,} -> {hk['arrivals_2025']:,} "
        f"({hk['arrivals_pct']:+.1f}%); distinct destinations "
        f"{hk['destinations_2024']:,} -> {hk['destinations_2025']:,} "
        f"({hk['destinations_pct']:+.1f}%).")
    if hk["destinations_pct"] is not None and hk["arrivals_pct"] is not None:
        if hk["destinations_pct"] > hk["arrivals_pct"] + 5:
            verdict = ("CONNECTIVITY HELD: Hong Kong's distinct destination "
                       "portfolio fell far less than its vessel volume, so it is "
                       "handling FEWER vessels rather than losing shipping "
                       "connections.")
        elif hk["destinations_pct"] < hk["arrivals_pct"] - 5:
            verdict = ("LOSING CONNECTIONS: Hong Kong's distinct destinations fell "
                       "more sharply than vessel volume, indicating eroding route "
                       "connectivity, not just lower throughput.")
        else:
            verdict = ("MIXED: destinations and vessel volume moved together; "
                       "lower activity is broadly proportional, with no clear "
                       "signal of lost connections beyond reduced volume.")
    else:
        verdict = "Insufficient data for a verdict."
    verdict_lines.append(verdict)
    verdict_lines.append(
        f"Context — Shenzhen arrivals {sz['arrivals_pct']:+.1f}% / destinations "
        f"{sz['destinations_pct']:+.1f}%; Guangzhou arrivals {gz['arrivals_pct']:+.1f}% "
        f"/ destinations {gz['destinations_pct']:+.1f}%.")

    # ---- write artifacts ------------------------------------------------
    with open(os.path.join(OUT, "prd_metrics.json"), "w", encoding="utf-8") as fh:
        json.dump({"generated_utc": datetime.now(timezone.utc).isoformat(),
                   "port_zones": {k: list(v) for k, v in PORTS.items()},
                   "summary": summary, "verdict": verdict}, fh, indent=2)
    with open(os.path.join(OUT, "prd_port_summary.csv"), "w",
              newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["port", "arrivals_2024", "arrivals_2025", "arrivals_pct",
                    "density_2024", "density_2025", "density_pct",
                    "destinations_2024", "destinations_2025", "destinations_pct"])
        for z in PORTS:
            s = summary[z]
            w.writerow([z, s["arrivals_2024"], s["arrivals_2025"], s["arrivals_pct"],
                        s["density_2024"], s["density_2025"], s["density_pct"],
                        s["destinations_2024"], s["destinations_2025"],
                        s["destinations_pct"]])

    # ---- render ---------------------------------------------------------
    fig = plt.figure(figsize=(22, 14), dpi=140)
    fig.patch.set_facecolor(BG)
    fig.suptitle("Pearl River Delta Port Comparison — Hong Kong vs Shenzhen vs "
                 "Guangzhou (AIS 2024 vs 2025)", color="white", fontsize=19,
                 fontweight="bold", y=0.978)
    fig.text(0.5, 0.950,
             "Zones are approximate non-overlapping bounding boxes (proxies, not "
             "official port limits). Vessel 'type' is not in the source data; size "
             "mix uses ais_capts_length. Connectivity = distinct reported "
             "destinations of vessels observed in each zone.",
             ha="center", color=TXT, fontsize=9.5)

    # KPI strip
    gs_kpi = fig.add_gridspec(1, 1, left=0.035, right=0.965, top=0.918, bottom=0.842)
    axk = fig.add_subplot(gs_kpi[0]); axk.set_xlim(0, 3); axk.set_ylim(0, 1); axk.axis("off")
    for i, z in enumerate(PORTS):
        s = summary[z]
        axk.add_patch(Rectangle((i + 0.04, 0.06), 0.92, 0.88, fc=PANEL,
                                ec=PORT_COLORS[z], lw=1.6))
        axk.text(i + 0.5, 0.80, z, ha="center", color="white", fontsize=12,
                 fontweight="bold")
        axk.text(i + 0.5, 0.52,
                 f"Arrivals {s['arrivals_2024']:,} -> {s['arrivals_2025']:,} "
                 f"({s['arrivals_pct']:+.1f}%)", ha="center", color="white",
                 fontsize=9.5)
        axk.text(i + 0.5, 0.30,
                 f"Destinations {s['destinations_2024']:,} -> "
                 f"{s['destinations_2025']:,} ({s['destinations_pct']:+.1f}%)",
                 ha="center", color=TXT, fontsize=8.5)
        axk.text(i + 0.5, 0.12,
                 f"Density {s['density_2024']:,} -> {s['density_2025']:,} pts "
                 f"({s['density_pct']:+.1f}%)", ha="center", color=MUTED, fontsize=8)

    gs = fig.add_gridspec(2, 3, left=0.05, right=0.97, top=0.80, bottom=0.10,
                          hspace=0.55, wspace=0.30)
    ports_list = list(PORTS)
    x = range(len(ports_list))

    def grouped(ax, key, title, ylabel, log=False):
        w = 0.38
        for i, year in enumerate((2024, 2025)):
            vals = [data[year][z][key] for z in ports_list]
            ax.bar([xi + (i - 0.5) * w for xi in x], vals, width=w,
                   color="#7f8fa6" if year == 2024 else "#ffd166",
                   label=str(year))
        ax.set_xticks(list(x)); ax.set_xticklabels(ports_list, color="white", fontsize=9)
        ax.set_title(title, color="white", fontsize=11, pad=8)
        ax.set_ylabel(ylabel, color=TXT, fontsize=9)
        ax.tick_params(colors="white", labelsize=8)
        ax.legend(fontsize=8, labelcolor="white", framealpha=0.5)
        ax.grid(True, axis="y", ls=":", color=GRID, alpha=0.7)
        if log:
            ax.set_yscale("log")

    ax1 = fig.add_subplot(gs[0, 0]); ax1.set_facecolor(PANEL)
    grouped(ax1, "arrivals_distinct_vessels", "Vessel arrivals (distinct MMSIs)",
            "Distinct vessels")
    ax2 = fig.add_subplot(gs[0, 1]); ax2.set_facecolor(PANEL)
    grouped(ax2, "traffic_density_points", "Vessel traffic density (position points)",
            "Position points", log=True)
    ax3 = fig.add_subplot(gs[0, 2]); ax3.set_facecolor(PANEL)
    grouped(ax3, "distinct_destinations", "Route connectivity (distinct destinations)",
            "Distinct destinations")

    # size mix stacked (2025) per port
    ax4 = fig.add_subplot(gs[1, 0]); ax4.set_facecolor(PANEL)
    size_colors = {"<100 m": "#4ecdc4", "100-200 m": "#3fa7ff",
                   "200-300 m": "#ffd166", ">300 m": "#ff5b5b", "Unknown": "#5c6b7a"}
    bottom = [0] * len(ports_list)
    for sc in SIZE_ORDER:
        vals = [data[2025][z]["size_classes"][sc] for z in ports_list]
        ax4.bar(list(x), vals, bottom=bottom, color=size_colors[sc], label=sc, width=0.6)
        bottom = [b + v for b, v in zip(bottom, vals)]
    ax4.set_xticks(list(x)); ax4.set_xticklabels(ports_list, color="white", fontsize=9)
    ax4.set_title("Vessel size mix, 2025 (by length; no type field in data)",
                  color="white", fontsize=10, pad=8)
    ax4.set_ylabel("Distinct vessels", color=TXT, fontsize=9)
    ax4.tick_params(colors="white", labelsize=8)
    ax4.legend(fontsize=7, labelcolor="white", framealpha=0.5, ncol=2)
    ax4.grid(True, axis="y", ls=":", color=GRID, alpha=0.7)

    # PRD map
    ax5 = fig.add_subplot(gs[1, 1]); ax5.set_facecolor("#0a1626")
    for z in ports_list:
        la0, la1, lo0, lo1 = PORTS[z]
        ax5.add_patch(Rectangle((lo0, la0), lo1 - lo0, la1 - la0, fill=False,
                                edgecolor=PORT_COLORS[z], lw=1.6, ls="--"))
        xs = [p[0] for p in pts[2025][z]]; ys = [p[1] for p in pts[2025][z]]
        ax5.scatter(xs, ys, s=2, c=PORT_COLORS[z], alpha=0.5, linewidths=0)
        ax5.text(lo0, la1 + 0.02, z, color=PORT_COLORS[z], fontsize=9,
                 fontweight="bold")
    ax5.set_xlim(112.9, 114.7); ax5.set_ylim(21.9, 23.5)
    ax5.set_xlabel("Longitude (°E)", color=TXT, fontsize=9)
    ax5.set_ylabel("Latitude (°N)", color=TXT, fontsize=9)
    ax5.set_title("PRD traffic density 2025 (zone boxes = port proxies)",
                  color="white", fontsize=10, pad=8)
    ax5.tick_params(colors="white", labelsize=8)
    ax5.grid(True, ls=":", color=GRID, alpha=0.7)

    # monthly trend
    ax6 = fig.add_subplot(gs[1, 2]); ax6.set_facecolor(PANEL)
    for z in ports_list:
        md = data[2025][z]["monthly_distinct_vessels"]
        if not md:
            continue
        xs = [datetime.strptime(m, "%Y%m") for m in sorted(md)]
        ax6.plot(xs, [md[m] for m in sorted(md)], color=PORT_COLORS[z], lw=1.8,
                 marker="o", ms=3, label=f"{z} 2025")
    ax6.set_title("Monthly distinct vessels, 2025", color="white", fontsize=10, pad=8)
    ax6.set_ylabel("Distinct vessels", color=TXT, fontsize=9)
    ax6.tick_params(colors="white", labelsize=8)
    ax6.legend(fontsize=8, labelcolor="white", framealpha=0.5)
    ax6.grid(True, ls=":", color=GRID, alpha=0.7)

    fig.text(0.5, 0.035, "  |  ".join(verdict_lines), ha="center", va="center",
             color="#ffd166", fontsize=10.5, fontweight="bold",
             wrap=True, bbox=dict(boxstyle="round,pad=0.5", fc="#10233a",
                                  ec="#ffd166", alpha=0.95))

    out_png = os.path.join(OUT, "prd_comparison.png")
    fig.savefig(out_png, dpi=150, facecolor=fig.get_facecolor())
    print("wrote", out_png)
    print("\nVERDICT:\n" + "\n".join(verdict_lines))
    print("\nSUMMARY:")
    for z in ports_list:
        s = summary[z]
        print(f"  {z}: arrivals {s['arrivals_2024']}->{s['arrivals_2025']} "
              f"({s['arrivals_pct']}%), dest {s['destinations_2024']}->"
              f"{s['destinations_2025']} ({s['destinations_pct']}%), "
              f"density {s['density_2024']}->{s['density_2025']} ({s['density_pct']}%)")


if __name__ == "__main__":
    main()
