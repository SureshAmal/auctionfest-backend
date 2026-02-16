"""
visualize_plots.py

Reads plot_data_v2.json and overlays polygons onto the source image.
Each plot is drawn with its unique color and labeled with its ID.

Usage:
    python visualize_plots.py                          # Uses Frame 1.png
    python visualize_plots.py --image /path/to/img.png # Uses custom image
    python visualize_plots.py --json /path/to/data.json
"""

import cv2
import numpy as np
import json
import argparse
import os
import sys

DEFAULT_IMAGE = "/home/suresh/dev/auctionfest/Frame 1.png"
DEFAULT_JSON = "/home/suresh/dev/auctionfest/backend/plot_data_v2.json"
OUTPUT_IMG = "/home/suresh/dev/auctionfest/backend/plot_overlay.png"


def hex_to_bgr(hex_color: str) -> tuple:
    """Convert hex color string (#rrggbb) to BGR tuple for OpenCV."""
    hex_color = hex_color.lstrip("#")
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    return (b, g, r)


def draw_text_with_bg(img, text, pos, color, scale=0.7, thickness=2):
    """Draw text with a white background rectangle for readability."""
    x, y = pos
    font = cv2.FONT_HERSHEY_SIMPLEX
    (tw, th), _ = cv2.getTextSize(text, font, scale, thickness)
    # Clamp position
    x = max(tw // 2 + 5, min(x, img.shape[1] - tw // 2 - 5))
    y = max(th + 10, y)
    # Background
    cv2.rectangle(img, (x - tw // 2 - 4, y - th - 4), (x + tw // 2 + 4, y + 4), (255, 255, 255), -1)
    cv2.rectangle(img, (x - tw // 2 - 4, y - th - 4), (x + tw // 2 + 4, y + 4), color, 1)
    # Text
    cv2.putText(img, text, (x - tw // 2, y), font, scale, color, thickness)


def visualize(image_path: str, json_path: str, output_path: str):
    """Load image and JSON, overlay polygons, save result."""
    # Load image
    img = cv2.imread(image_path)
    if img is None:
        print(f"Error: Could not read image '{image_path}'")
        sys.exit(1)

    h, w = img.shape[:2]

    # Load JSON
    if not os.path.exists(json_path):
        print(f"Error: JSON file not found '{json_path}'")
        sys.exit(1)

    with open(json_path, "r") as f:
        plots = json.load(f)

    vis = img.copy()

    for plot in plots:
        plot_id = plot.get("id", "?")
        color_hex = plot.get("color", "#00ff00")
        polygon_pct = plot.get("polygon", [])
        cx_pct = plot.get("cx", 0)
        cy_pct = plot.get("cy", 0)

        if not polygon_pct:
            continue

        # Convert percentage polygon to pixel coordinates
        pts = np.array(
            [[int(pt[0] / 100 * w), int(pt[1] / 100 * h)] for pt in polygon_pct],
            dtype=np.int32
        )

        bgr = hex_to_bgr(color_hex)

        # Draw filled polygon with transparency
        overlay = vis.copy()
        cv2.fillPoly(overlay, [pts], bgr)
        cv2.addWeighted(overlay, 0.25, vis, 0.75, 0, vis)

        # Draw polygon border
        cv2.polylines(vis, [pts], isClosed=True, color=bgr, thickness=2)

        # Draw centroid dot
        cx_px = int(cx_pct / 100 * w)
        cy_px = int(cy_pct / 100 * h)
        cv2.circle(vis, (cx_px, cy_px), 4, bgr, -1)

        # Label with ID
        draw_text_with_bg(vis, str(plot_id), (cx_px, cy_px - 12), bgr)

    # Save
    cv2.imwrite(output_path, vis)
    print(f"Overlay saved to: {output_path}")
    print(f"Plots drawn: {len(plots)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Visualize plot polygons on image")
    parser.add_argument("--image", default=DEFAULT_IMAGE, help="Source image path")
    parser.add_argument("--json", default=DEFAULT_JSON, help="Plot data JSON path")
    parser.add_argument("--output", default=OUTPUT_IMG, help="Output image path")
    args = parser.parse_args()

    visualize(args.image, args.json, args.output)
