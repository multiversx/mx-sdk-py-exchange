"""
Plot the CSV output produced by safeprice_monitor.py.

Usage:
    python3 tools/safeprice_plot.py --file dump/safe_price_observations_<suffix>.csv
    python3 tools/safeprice_plot.py --file dump/safe_price_observations_<suffix>.csv --smooth 50
    python3 tools/safeprice_plot.py --file dump/safe_price_observations_<suffix>.csv --output chart.png
"""

import sys
import argparse
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker


SPOT_COLOR = "#e74c3c"       # red  — most manipulable
LEGACY_COLOR = "#f39c12"     # orange — legacy on-chain TWAP
ONLINE_COLORS = ["#2980b9", "#1abc9c", "#8e44ad"]  # blue/teal/purple — view contract
OFFLINE_COLORS = ["#27ae60", "#16a085", "#2c3e50"]  # greens — offline models


def smooth(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window, min_periods=1, center=True).mean()


def classify_column(col: str) -> str:
    if col == "spot_price":
        return "spot"
    if col == "updateAndGetSafePrice":
        return "legacy"
    if col.startswith("getSafePriceBy"):
        return "online"
    if col.endswith("_rounds_avg_offline"):
        return "offline"
    if col.endswith("_rounds_avg_uniswap"):
        return "uniswap"
    return "other"


def main(cli_args):
    parser = argparse.ArgumentParser(description="Plot safeprice_monitor CSV output")
    parser.add_argument("--file", required=True, help="Path to the CSV file")
    parser.add_argument("--smooth", type=int, default=0,
                        help="Rolling-average window (blocks) applied to every series before plotting")
    parser.add_argument("--output", default="", help="Save figure to this path instead of showing interactively")
    parser.add_argument("--title", default="", help="Optional chart title override")
    args = parser.parse_args(cli_args)

    csv_path = Path(args.file)
    if not csv_path.exists():
        print(f"ERROR: file not found: {csv_path}", file=sys.stderr)
        sys.exit(1)

    df = pd.read_csv(csv_path)
    if "block" not in df.columns:
        print("ERROR: CSV has no 'block' column", file=sys.stderr)
        sys.exit(1)

    price_cols = [c for c in df.columns if c != "block"]

    fig, ax = plt.subplots(figsize=(14, 6))

    online_i = offline_i = 0
    for col in price_cols:
        series = df[col]
        if args.smooth > 1:
            series = smooth(series, args.smooth)

        kind = classify_column(col)
        if kind == "spot":
            ax.plot(df["block"], series, color=SPOT_COLOR, linewidth=1.2,
                    alpha=0.7, label=col, zorder=3)
        elif kind == "legacy":
            ax.plot(df["block"], series, color=LEGACY_COLOR, linewidth=1.5,
                    linestyle="--", label=col, zorder=4)
        elif kind == "online":
            color = ONLINE_COLORS[online_i % len(ONLINE_COLORS)]
            ax.plot(df["block"], series, color=color, linewidth=1.8,
                    label=col, zorder=5)
            online_i += 1
        elif kind in ("offline", "uniswap"):
            color = OFFLINE_COLORS[offline_i % len(OFFLINE_COLORS)]
            ax.plot(df["block"], series, color=color, linewidth=1.8,
                    linestyle="-.", label=col, zorder=5)
            offline_i += 1
        else:
            ax.plot(df["block"], series, linewidth=1.2, label=col)

    title = args.title or f"Safe Price Oracle Comparison — {csv_path.name}"
    if args.smooth > 1:
        title += f"  (smoothed {args.smooth}-block window)"
    ax.set_title(title, fontsize=13)
    ax.set_xlabel("Block (round)", fontsize=11)
    ax.set_ylabel("Price (normalised, 1 token)", fontsize=11)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.4f"))
    ax.legend(loc="upper left", fontsize=9, framealpha=0.8)
    ax.grid(True, linestyle=":", alpha=0.5)
    fig.tight_layout()

    if args.output:
        fig.savefig(args.output, dpi=150)
        print(f"Saved: {args.output}")
    else:
        plt.show()


if __name__ == "__main__":
    main(sys.argv[1:])
