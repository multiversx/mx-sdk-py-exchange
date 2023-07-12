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

    x = data[data.columns[0]]   # rounds

    for column in data.columns[1:]:
        plt.plot(x, data[column], label=column)

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

    plt.style.use('default')
    ani = FuncAnimation(plt.gcf(), animate, interval=3000, cache_frame_data=False)

    plt.tight_layout()
    plt.show()
