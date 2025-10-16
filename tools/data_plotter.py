import csv
import sys
from argparse import ArgumentParser
from typing import Any, Dict, List
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.backend_bases import PickEvent


LOG_FILENAME = "dump/safe_price_observations.csv"

# Global dictionary to track line visibility states
line_visibility: Dict[str, bool] = {}
# Global dictionary to store line objects
line_objects: Dict[str, plt.Line2D] = {}


def on_legend_click(event: Any) -> None:
    """Handle legend click events to toggle line visibility."""
    legend = event.artist
    if legend is None:
        return
    
    # Get the legend object from the current axes
    ax = plt.gca()
    leg = ax.get_legend()
    if leg is None:
        return
    
    # Find which legend entry was clicked
    for legend_line, legend_text in zip(leg.get_lines(), leg.get_texts()):
        if legend_line == event.artist or legend_text == event.artist:
            label = legend_text.get_text()
            
            # Toggle visibility state
            if label in line_visibility:
                line_visibility[label] = not line_visibility[label]
                is_visible = line_visibility[label]
                
                # Update the corresponding plot line
                if label in line_objects:
                    line_objects[label].set_visible(is_visible)
                
                # Update legend appearance
                alpha = 1.0 if is_visible else 0.3
                legend_line.set_alpha(alpha)
                legend_text.set_alpha(alpha)
                
                plt.draw()
            break


def animate(i: int) -> None:
    plt.cla()

    data = pd.read_csv(LOG_FILENAME)

    x = data[data.columns[0]]   # rounds

    # Clear old line objects
    line_objects.clear()
    
    for column in data.columns[1:]:
        # Initialize visibility state for new columns
        if column not in line_visibility:
            line_visibility[column] = True
        
        # Create the line and store it
        line, = plt.plot(x, data[column], label=column)
        line_objects[column] = line
        
        # Apply visibility state
        line.set_visible(line_visibility[column])

    # Create legend with picker enabled
    leg = plt.legend(loc='upper left', fancybox=True, shadow=True)
    
    # Update legend appearance based on visibility states and enable picking
    for legend_line, legend_text in zip(leg.get_lines(), leg.get_texts()):
        label = legend_text.get_text()
        if label in line_visibility:
            alpha = 1.0 if line_visibility[label] else 0.3
            legend_line.set_alpha(alpha)
            legend_text.set_alpha(alpha)
        
        # Enable picking on legend items with tolerance
        legend_line.set_picker(True)
        legend_line.set_pickradius(5)
        legend_text.set_picker(True)
    
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
    
    # Connect the legend click handler
    fig = plt.gcf()
    fig.canvas.mpl_connect('pick_event', on_legend_click)
    
    ani = FuncAnimation(fig, animate, interval=3000, cache_frame_data=False)  # type: ignore

    plt.tight_layout()
    plt.show()
