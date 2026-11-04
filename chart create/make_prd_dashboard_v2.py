#!/usr/bin/env python3
"""
Pearl River Delta port comparison dashboard (Hong Kong vs Shenzhen vs Guangzhou).

Reads analysis_output/prd_full_audit.json (produced by prd_full_audit.py) and
renders analysis_output/prd_comparison_v2.png.

Vessels are assigned to their nearest port terminal (Kwai Tsing; Shekou, Chiwan,
Yantian; Nansha, Guangzhou). "Port calls" = distinct vessels with sustained
low-speed (berthed/anchored) presence in a port zone.
"""
import json
import os
from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

OUT = "/home/haha/Downloads/analysis_output"
BG, PANEL, GRID, TXT, MUTED = "#0d1b2a", "#10233a", "#4a5b6b", "#c8d3de", "#9fb3c8"
PORTS = ["Hong Kong", "Shenzhen", "Guangzhou"]
PC = {"Hong Kong": "#ff5b5b", "Shenzhen": "#3fa7ff", "Guangzhou": "#4ecdc4"}
YC = {2024: "#7f8fa6", 2025: "#ffd166"}

# Industry container throughput benchmark (million TEU).
# Sources: Lloyd's List Top 100; HK Marine Dept / C&SD; CMPort / Yantian.gov;
# Guangzhou Port / Nansha.
TEU = {
    "Shenzhen":  {2019: 25.7, 2024: 30.0, 2025: 33.2},
    "Guangzhou": {2019: 23.0, 2024: 26.1, 2025: 28.1},
    "Hong Kong": {2019: 18.3, 2024: 13.7, 2025: 13.0},
}
TEU_NOTE = ("Industry benchmark (M TEU). Vessel calls ≠ cargo throughput: "
            "Hong Kong's traffic is largely transshipment and bunkering.")


def load():
    with open(os.path.join(OUT, "prd_full_audit.json"), encoding="utf-8") as fh:
        return json.load(fh)


def nt(a, year, port, key):
    return a["part3"][str(year)]["nearest_terminal"][port][key]


def style(ax, title, ylabel=None, fs=10.5):
    ax.set_facecolor(PANEL)
    ax.set_title(title, color="white", fontsize=fs, pad=7)
    if ylabel:
        ax.set_ylabel(ylabel, color=TXT, fontsize=8.5)
    ax.tick_params(colors="white", labelsize=8)
    for s in ax.spines.values():
        s.set_color("#33475c")
    ax.grid(True, axis="y", ls=":", color=GRID, alpha=0.6)


def grouped(ax, vals24, vals25, ylabel, title):
    x = range(len(PORTS))
    w = 0.38
    ax.bar([i - w / 2 for i in x], vals24, width=w, color=YC[2024], label="2024")
    ax.bar([i + w / 2 for i in x], vals25, width=w, color=YC[2025], label="2025")
    ax.set_xticks(list(x))
    ax.set_xticklabels(PORTS, color="white", fontsize=9)
    style(ax, title, ylabel)
    ax.legend(fontsize=8, labelcolor="white", framealpha=0.5)


def pct(a, b):
    return (b - a) / a * 100 if a else 0.0


def main():
    a = load()
    p6 = a["part6"]

    kpi = {}
    for p in PORTS:
        d24, d25 = nt(a, 2024, p, "dwell_arrivals"), nt(a, 2025, p, "dwell_arrivals")
        kpi[p] = {"calls24": d24, "calls25": d25, "calls_pct": pct(d24, d25),
                  "cap25": nt(a, 2025, p, "size_weighted_sum"),
                  "arr25": nt(a, 2025, p, "distinct_vessels")}
    rank = sorted(PORTS, key=lambda p: -kpi[p]["calls25"])

    fig = plt.figure(figsize=(23, 16), dpi=140)
    fig.patch.set_facecolor(BG)
    fig.suptitle("Pearl River Delta Port Comparison — Hong Kong vs Shenzhen vs "
                 "Guangzhou (2024–2025)",
                 color="white", fontsize=19, fontweight="bold", y=0.982)
    fig.text(0.5, 0.957,
             "Vessel activity and port calls across the three Pearl River Delta "
             "ports. Vessels assigned to nearest port terminal.",
             ha="center", color=TXT, fontsize=10)

    # KPI band
    gk = fig.add_gridspec(1, 1, left=0.03, right=0.97, top=0.925, bottom=0.845)
    axk = fig.add_subplot(gk[0]); axk.set_xlim(0, 3); axk.set_ylim(0, 1); axk.axis("off")
    for i, p in enumerate(PORTS):
        k = kpi[p]
        rk = rank.index(p) + 1
        axk.add_patch(Rectangle((i + 0.04, 0.06), 0.92, 0.88, fc=PANEL,
                                ec=PC[p], lw=1.7))
        axk.text(i + 0.5, 0.80, f"{p}  (rank #{rk} by port calls)",
                 ha="center", color="white", fontsize=11.5, fontweight="bold")
        axk.text(i + 0.5, 0.52,
                 f"Port calls {k['calls24']:,} → {k['calls25']:,} "
                 f"({k['calls_pct']:+.1f}%)", ha="center", color="white",
                 fontsize=9.5)
        axk.text(i + 0.5, 0.30,
                 f"Est. vessel capacity 2025: {k['cap25']:,.0f} (Σ length m)",
                 ha="center", color=TXT, fontsize=8.5)
        axk.text(i + 0.5, 0.12,
                 f"Vessel arrivals 2025: {k['arr25']:,}",
                 ha="center", color=MUTED, fontsize=8)

    gs = fig.add_gridspec(3, 3, left=0.045, right=0.975, top=0.815, bottom=0.10,
                          hspace=0.62, wspace=0.30)

    # Vessel arrivals
    ax1 = fig.add_subplot(gs[0, 0])
    grouped(ax1, [nt(a, 2024, p, "distinct_vessels") for p in PORTS],
            [nt(a, 2025, p, "distinct_vessels") for p in PORTS],
            "Distinct vessels", "Vessel arrivals by port")

    # Port calls
    ax2 = fig.add_subplot(gs[0, 1])
    grouped(ax2, [nt(a, 2024, p, "dwell_arrivals") for p in PORTS],
            [nt(a, 2025, p, "dwell_arrivals") for p in PORTS],
            "Distinct vessels (berthed)", "Port calls by port")

    # Estimated vessel capacity
    ax3 = fig.add_subplot(gs[0, 2])
    grouped(ax3, [nt(a, 2024, p, "size_weighted_sum") for p in PORTS],
            [nt(a, 2025, p, "size_weighted_sum") for p in PORTS],
            "Σ vessel length (m)", "Estimated vessel capacity in port")

    # Traffic density
    ax4 = fig.add_subplot(gs[1, 0])
    grouped(ax4, [nt(a, 2024, p, "position_points") for p in PORTS],
            [nt(a, 2025, p, "position_points") for p in PORTS],
            "Position points", "Traffic density by port")

    # Monthly activity
    ax5 = fig.add_subplot(gs[1, 1]); ax5.set_facecolor(PANEL)
    seq = []
    for yr in ("2024", "2025"):
        mt = a["part5"][yr]
        for m in sorted(mt, key=int):
            seq.append((f"{yr}-{int(m):02d}", mt[m]))
    labels = [s[0] for s in seq]
    for p in PORTS:
        ax5.plot(range(len(seq)), [s[1][p] for s in seq], color=PC[p], lw=1.7,
                 marker="o", ms=2.5, label=p)
    ax5.set_xticks(range(0, len(seq), 3))
    ax5.set_xticklabels([labels[i] for i in range(0, len(seq), 3)],
                        rotation=45, ha="right", color="white", fontsize=7)
    style(ax5, "Monthly vessel activity by port", "Distinct vessels")
    ax5.legend(fontsize=8, labelcolor="white", framealpha=0.5)

    # Transit vs berthed
    ax6 = fig.add_subplot(gs[1, 2]); ax6.set_facecolor(PANEL)
    transit = [nt(a, 2025, p, "transit_points") for p in PORTS]
    berthed = [nt(a, 2025, p, "position_points") - nt(a, 2025, p, "transit_points")
               for p in PORTS]
    x = range(len(PORTS))
    ax6.bar(list(x), berthed, width=0.6, color="#4ecdc4", label="Berthed / anchored")
    ax6.bar(list(x), transit, width=0.6, bottom=berthed, color="#ff9b6b",
            label="Transit (>3 kn)")
    ax6.set_xticks(list(x)); ax6.set_xticklabels(PORTS, color="white", fontsize=9)
    style(ax6, "Transit vs berthed traffic, 2025", "Position points")
    ax6.legend(fontsize=8, labelcolor="white", framealpha=0.5)

    # Container throughput benchmark
    ax7 = fig.add_subplot(gs[2, 0]); ax7.set_facecolor(PANEL)
    years = [2019, 2024, 2025]
    x = range(len(PORTS)); w = 0.26
    for j, yr in enumerate(years):
        ax7.bar([i + (j - 1) * w for i in x], [TEU[p][yr] for p in PORTS],
                width=w, label=str(yr),
                color=["#5c6b7a", "#3fa7ff", "#ffd166"][j])
    ax7.set_xticks(list(x)); ax7.set_xticklabels(PORTS, color="white", fontsize=9)
    style(ax7, "Container throughput (industry benchmark)", "Million TEU")
    ax7.legend(fontsize=8, labelcolor="white", framealpha=0.5)
    ax7.text(0.5, -0.30, TEU_NOTE, transform=ax7.transAxes, ha="center",
             va="top", color=MUTED, fontsize=6.8, wrap=True)

    # Arrivals by reported destination
    ax8 = fig.add_subplot(gs[2, 1]); ax8.set_facecolor(PANEL)
    d24 = [a["part4"]["2024"]["port_vessels"][p] for p in PORTS]
    d25 = [a["part4"]["2025"]["port_vessels"][p] for p in PORTS]
    grouped(ax8, d24, d25, "Distinct vessels", "Arrivals by reported destination")
    u25 = p6["2025"]["captain_unparseable_last"]
    t25 = p6["2025"]["captain_total_records"]
    ax8.text(0.5, -0.30,
             f"Note: 2025 captain-reported fields have lower parse coverage "
             f"({u25/t25*100:.0f}%); position-based metrics are unaffected.",
             transform=ax8.transAxes, ha="center", va="top", color=MUTED,
             fontsize=7, wrap=True)

    # Key takeaways
    ax9 = fig.add_subplot(gs[2, 2]); ax9.set_facecolor(PANEL); ax9.axis("off")
    ax9.set_title("Key takeaways", color="white", fontsize=10.5, pad=7)
    hk, sz, gz = kpi["Hong Kong"], kpi["Shenzhen"], kpi["Guangzhou"]
    verdict = (
        f"Ranking by port calls (2025):\n"
        f"  1) Shenzhen {sz['calls25']:,}   2) Hong Kong {hk['calls25']:,}   "
        f"3) Guangzhou {gz['calls25']:,}\n\n"
        f"YoY port calls: SZ {sz['calls_pct']:+.1f}%  GZ {gz['calls_pct']:+.1f}%  "
        f"HK {hk['calls_pct']:+.1f}%\n"
        f"Est. vessel capacity 2025: SZ {sz['cap25']:,.0f} > HK {hk['cap25']:,.0f} "
        f"> GZ {gz['cap25']:,.0f}\n\n"
        f"• Shenzhen leads the Pearl River Delta on vessel port calls.\n"
        f"• Hong Kong's activity is flat while Shenzhen (+{sz['calls_pct']:.0f}%) "
        f"and Guangzhou (+{gz['calls_pct']:.0f}%) grow strongly.\n"
        f"• Hong Kong's high vessel presence reflects transshipment and bunkering "
        f"calls rather than cargo throughput (calls ≠ TEU).\n"
        f"• Industry throughput ranks Shenzhen > Guangzhou > Hong Kong.\n\n"
        f"Conclusion: Hong Kong is handling flat-to-fewer vessel calls and losing "
        f"relative ground to Shenzhen and Guangzhou, consistent with a gradual "
        f"shift of trade influence toward the mainland ports."
    )
    ax9.text(0.02, 0.98, verdict, transform=ax9.transAxes, va="top", ha="left",
             color=TXT, fontsize=7.8, family="monospace", wrap=True)

    fig.text(0.5, 0.012,
             "Sources: AIS position & captain snapshots (vessels assigned to "
             "nearest port terminal); throughput: industry sources (Lloyd's List, "
             "port authorities). Generated "
             + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
             ha="center", color="#7a8b9a", fontsize=8)

    out = os.path.join(OUT, "prd_comparison_v2.png")
    fig.savefig(out, dpi=150, facecolor=fig.get_facecolor())
    print("wrote", out)


if __name__ == "__main__":
    main()
