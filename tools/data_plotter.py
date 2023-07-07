import csv
import sys
from argparse import ArgumentParser
from typing import List
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation


LOG_FILENAME = "dump/safe_price_observations.csv"


def animate(i):
    plt.cla()

    data = pd.read_csv(LOG_FILENAME)

    x = data['block']
    y1 = data['safe_price']
    y2 = data['spot_price']
    if '10min_avg_rounds' in data.columns:
        y3 = data['10min_avg_rounds']
        plt.plot(x, y3, label='10Min Average')
    if '20min_avg_timestamp' in data.columns:
        y5 = data['20min_avg_timestamp']
        plt.plot(x, y5, label='20Min Average')

    plt.plot(x, y2, label="Spot Price")
    plt.plot(x, y1, label='Safe Price')

    plt.legend(loc='upper left')
    plt.tight_layout()


def main(cli_args: List[str]):
    parser = ArgumentParser()
    parser.add_argument("--file-suffix", required=False, default="")
    args = parser.parse_args(cli_args)

    global LOG_FILENAME
    LOG_FILENAME = f"dump/safe_price_observations_{args.file_suffix}.csv"


if __name__ == "__main__":
    main(sys.argv[1:])

    plt.style.use('fivethirtyeight')
    ani = FuncAnimation(plt.gcf(), animate, interval=3000, cache_frame_data=False)

    plt.tight_layout()
    plt.show()
