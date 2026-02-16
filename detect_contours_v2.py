"""
Robust plot contour detection from Figma export.
Uses "Frame 1 (1).png" (clean Figma) for contour detection.
Uses "Frame 1.png" (numbered town plan) for plot number identification.

Strategy:
1. In the Figma image, borders are black or red on white/gray background
2. Create a combined border mask (black + red lines)
3. Find enclosed regions (flood fill from gray areas)
4. Extract contour polygons for each region
5. Red-bordered plots across the river get merged into single multi-polygon plots
6. Match each region to a plot number using the numbered image
"""

import cv2
import numpy as np
import json
import os

FIGMA_IMG = "/home/suresh/dev/auctionfest/Frame 1 (1).png"
NUMBERED_IMG = "/home/suresh/dev/auctionfest/Frame 1.png"
OUTPUT_JSON = "/home/suresh/dev/auctionfest/backend/plot_contours.json"
DEBUG_DIR = "/home/suresh/dev/auctionfest/backend/debug"

os.makedirs(DEBUG_DIR, exist_ok=True)


def load_images():
    """Load both images."""
    figma = cv2.imread(FIGMA_IMG)
    numbered = cv2.imread(NUMBERED_IMG)
    if figma is None:
        raise FileNotFoundError(f"Cannot read: {FIGMA_IMG}")
    if numbered is None:
        raise FileNotFoundError(f"Cannot read: {NUMBERED_IMG}")
    return figma, numbered


def get_border_mask(figma):
    """Extract all borders (black + red) from the Figma image."""
    h, w = figma.shape[:2]
    hsv = cv2.cvtColor(figma, cv2.COLOR_BGR2HSV)
    
    # Black borders: very dark pixels
    black_mask = cv2.inRange(figma, np.array([0, 0, 0]), np.array([60, 60, 60]))
    
    # Red borders: red-hued pixels (HSV hue wraps around 0/180)
    red_mask1 = cv2.inRange(hsv, np.array([0, 80, 80]), np.array([12, 255, 255]))
    red_mask2 = cv2.inRange(hsv, np.array([168, 80, 80]), np.array([180, 255, 255]))
    red_mask = cv2.bitwise_or(red_mask1, red_mask2)
    
    # Combined border mask
    border_mask = cv2.bitwise_or(black_mask, red_mask)
    
    # Clean up: close small gaps in borders
    k = np.ones((3, 3), np.uint8)
    border_mask = cv2.morphologyEx(border_mask, cv2.MORPH_CLOSE, k, iterations=1)
    
    return border_mask, black_mask, red_mask


def get_red_border_mask(figma):
    """Get only red borders (for identifying river-split plots)."""
    hsv = cv2.cvtColor(figma, cv2.COLOR_BGR2HSV)
    red1 = cv2.inRange(hsv, np.array([0, 80, 80]), np.array([12, 255, 255]))
    red2 = cv2.inRange(hsv, np.array([168, 80, 80]), np.array([180, 255, 255]))
    red_mask = cv2.bitwise_or(red1, red2)
    # Dilate slightly to ensure connectivity
    k = np.ones((5, 5), np.uint8)
    return cv2.dilate(red_mask, k, iterations=1)


def find_gray_regions(figma, border_mask):
    """Find gray-filled plot regions using connected components."""
    h, w = figma.shape[:2]
    
    # Gray fill: pixels that are grayish (R≈G≈B) and in the range 180-230
    gray = cv2.cvtColor(figma, cv2.COLOR_BGR2GRAY)
    gray_fill = cv2.inRange(gray, 180, 235)
    
    # Remove border pixels from fill
    gray_fill = cv2.bitwise_and(gray_fill, cv2.bitwise_not(border_mask))
    
    # Remove pure white 
    white_mask = cv2.inRange(gray, 245, 255)
    gray_fill = cv2.bitwise_and(gray_fill, cv2.bitwise_not(white_mask))
    
    # Morphological cleanup
    k = np.ones((3, 3), np.uint8)
    gray_fill = cv2.morphologyEx(gray_fill, cv2.MORPH_OPEN, k, iterations=1)
    gray_fill = cv2.morphologyEx(gray_fill, cv2.MORPH_CLOSE, k, iterations=2)
    
    # Connected components
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(gray_fill)
    
    img_area = w * h
    min_area = img_area * 0.0002  # Minimum plot area
    
    regions = []
    for i in range(1, num_labels):
        area = stats[i, cv2.CC_STAT_AREA]
        if area < min_area:
            continue
        
        cx, cy = centroids[i]
        x = stats[i, cv2.CC_STAT_LEFT]
        y = stats[i, cv2.CC_STAT_TOP]
        bw = stats[i, cv2.CC_STAT_WIDTH]
        bh = stats[i, cv2.CC_STAT_HEIGHT]
        
        regions.append({
            'label': i,
            'area': area,
            'center': (cx, cy),
            'bbox': (x, y, bw, bh),
            'cx_pct': round(cx / w * 100, 2),
            'cy_pct': round(cy / h * 100, 2),
            'area_pct': round(area / img_area * 100, 3),
        })
    
    regions.sort(key=lambda r: (r['cy_pct'], r['cx_pct']))
    return regions, labels, gray_fill


def extract_contour_for_region(labels, label_id, img_shape):
    """Extract the contour polygon for a labeled region."""
    h, w = img_shape[:2]
    
    # Create binary mask for this region
    region_mask = (labels == label_id).astype(np.uint8) * 255
    
    # Dilate slightly to touch the borders, then find external contour
    k = np.ones((5, 5), np.uint8)
    dilated = cv2.dilate(region_mask, k, iterations=2)
    
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    if not contours:
        return None
    
    # Take the largest contour
    cnt = max(contours, key=cv2.contourArea)
    
    # Approximate polygon - balance between accuracy and simplicity
    peri = cv2.arcLength(cnt, True)
    epsilon = 0.006 * peri  # Moderate approximation
    approx = cv2.approxPolyDP(cnt, epsilon, True)
    
    # Convert to percentage coordinates
    polygon = [[round(pt[0][0] / w * 100, 2),
                round(pt[0][1] / h * 100, 2)] for pt in approx]
    
    return polygon, cnt


def is_touching_red_border(labels, label_id, red_mask, img_shape):
    """Check if a region touches red borders (river-split indicator)."""
    region_mask = (labels == label_id).astype(np.uint8) * 255
    
    # Dilate region slightly
    k = np.ones((7, 7), np.uint8)
    dilated = cv2.dilate(region_mask, k, iterations=2)
    
    # Check overlap with red mask
    overlap = cv2.bitwise_and(dilated, red_mask)
    return np.count_nonzero(overlap) > 50


def merge_river_split_regions(regions, labels, red_mask, figma):
    """
    Merge regions that are split by the river (red-bordered).
    Red-bordered pairs on opposite sides of the river form one plot.
    """
    h, w = figma.shape[:2]
    
    # Find all regions that touch red borders
    red_regions = []
    non_red_regions = []
    
    for r in regions:
        if is_touching_red_border(labels, r['label'], red_mask, figma.shape):
            red_regions.append(r)
        else:
            non_red_regions.append(r)
    
    print(f"  Red-bordered regions: {len(red_regions)}")
    print(f"  Normal regions: {len(non_red_regions)}")
    
    # Pair red regions: match left-right or top-bottom pairs near the river
    # The river runs roughly vertically through the center (~49-51% x)
    # Red pairs should have similar y but be on opposite sides of center x
    merged = []
    used = set()
    
    for i, r1 in enumerate(red_regions):
        if i in used:
            continue
        best_j = None
        best_dist = 999
        
        for j, r2 in enumerate(red_regions):
            if j <= i or j in used:
                continue
            
            # Y should be similar (same plot row)
            dy = abs(r1['cy_pct'] - r2['cy_pct'])
            if dy > 3.0:
                continue
            
            # X should be different (opposite sides of river)
            dx = abs(r1['cx_pct'] - r2['cx_pct'])
            if dx < 2.0 or dx > 20.0:
                continue
            
            dist = dy + dx * 0.1  # Prefer close Y, allow X spread
            if dist < best_dist:
                best_dist = dist
                best_j = j
        
        if best_j is not None:
            r2 = red_regions[best_j]
            used.add(best_j)
            
            # Merge: keep both polygons as separate parts of the same plot
            merged.append({
                'regions': [r1, r2],
                'cx_pct': round((r1['cx_pct'] + r2['cx_pct']) / 2, 2),
                'cy_pct': round((r1['cy_pct'] + r2['cy_pct']) / 2, 2),
                'is_merged': True,
            })
            print(f"    Merged: ({r1['cx_pct']:.1f}%,{r1['cy_pct']:.1f}%) + "
                  f"({r2['cx_pct']:.1f}%,{r2['cy_pct']:.1f}%)")
        else:
            # Unpaired red region - treat as normal
            non_red_regions.append(r1)
        
        used.add(i)
    
    return non_red_regions, merged


def read_plot_number_at(numbered_img, cx, cy, size=120):
    """Try to read the plot number from the numbered image at given coordinates."""
    h, w = numbered_img.shape[:2]
    
    # Extract ROI around center
    x1 = max(0, int(cx - size))
    y1 = max(0, int(cy - size))
    x2 = min(w, int(cx + size))
    y2 = min(h, int(cy + size))
    
    roi = numbered_img[y1:y2, x1:x2]
    if roi.size == 0:
        return None
    
    # In the numbered image, plot numbers are dark text
    gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    
    # Look for dark text on lighter background
    _, binary = cv2.threshold(gray_roi, 80, 255, cv2.THRESH_BINARY_INV)
    
    try:
        import pytesseract
        # Upscale for better OCR
        scaled = cv2.resize(binary, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        text = pytesseract.image_to_string(scaled, config='--psm 7 -c tessedit_char_whitelist=0123456789')
        digits = ''.join(filter(str.isdigit, text))
        if digits:
            num = int(digits)
            if 1 <= num <= 43:
                return num
    except ImportError:
        pass
    except Exception:
        pass
    
    return None


def assign_plot_numbers_by_position(regions, merged_regions, numbered_img):
    """
    Assign plot numbers to regions.
    First try OCR, then fall back to positional matching.
    """
    h, w = numbered_img.shape[:2]
    
    # Known plot center positions from the map analysis
    # These are approximate centers from the Map.tsx PLOT_POSITIONS and manual inspection
    KNOWN_CENTERS = {
        # Inner ring (around lake) - these are river-split merged pairs
        1:  (39.7, 50.1),   # left of lake
        2:  (42.4, 43.5),   # upper-left wedge
        3:  (49.2, 37.0),   # top of lake (river-split merged)
        4:  (48.9, 39.5),   # below plot 3 (river-split merged)
        5:  (55.5, 43.5),   # upper-right wedge
        6:  (58.2, 50.0),   # right of lake
        7:  (59.2, 60.1),   # lower-right wedge
        8:  (48.9, 60.4),   # bottom of lake (river-split merged)
        9:  (49.2, 63.0),   # below plot 8 (river-split merged)
        10: (42.4, 56.5),   # lower-left wedge
        
        # Second ring
        11: (34.6, 50.0),   # left mid
        12: (38.7, 39.9),   # upper-left diagonal
        13: (49.9, 34.4),   # top center (river-split merged)
        14: (55.3, 29.9),   # top right of second ring
        15: (59.2, 39.9),   # upper-right diagonal
        16: (63.3, 50.0),   # right mid
        17: (55.6, 56.5),   # lower-right
        18: (49.9, 65.5),   # bottom center (river-split merged)
        19: (53.0, 70.1),   # bottom right (river-split merged)
        20: (38.7, 60.1),   # lower-left diagonal
        
        # Third ring / outer
        21: (26.8, 54.5),   # outer left-lower
        22: (28.0, 35.1),   # outer left-upper
        23: (33.9, 29.1),   # outer upper-left diagonal
        24: (44.4, 27.7),   # outer top-left
        25: (51.1, 26.1),   # outer top-center-left
        26: (56.3, 26.0),   # outer top-center-right
        27: (50.8, 29.8),   # outer top mid
        28: (64.0, 29.1),   # outer upper-right diagonal
        29: (69.9, 35.0),   # outer right-upper
        30: (71.1, 45.5),   # outer right-mid-upper
        31: (71.2, 54.5),   # outer right-mid-lower
        32: (69.9, 64.9),   # outer right-lower
        33: (64.0, 70.8),   # outer lower-right diagonal
        34: (53.7, 73.9),   # outer bottom-right (river-split merged)
        35: (44.5, 72.2),   # outer bottom-center
        36: (17.9, 50.0),   # far left center
        37: (34.0, 71.0),   # outer lower-left diagonal
        38: (28.0, 65.0),   # outer left-lower diagonal
        39: (26.7, 45.6),   # outer left-mid-upper
        40: (17.9, 72.9),   # far bottom-left
        41: (80.0, 49.9),   # far right center
        42: (75.6, 19.0),   # far top-right
        43: (79.9, 30.4),   # far upper-right
    }
    
    # Try OCR first for each region
    all_items = []
    
    for r in regions:
        cx_px = r['center'][0]
        cy_px = r['center'][1]
        num = read_plot_number_at(numbered_img, cx_px, cy_px)
        all_items.append({
            'region': r,
            'ocr_number': num,
            'cx_pct': r['cx_pct'],
            'cy_pct': r['cy_pct'],
            'is_merged': False,
        })
    
    for m in merged_regions:
        all_items.append({
            'region': m,
            'ocr_number': None,
            'cx_pct': m['cx_pct'],
            'cy_pct': m['cy_pct'],
            'is_merged': True,
        })
    
    # Now assign by nearest known center
    assigned = {}
    used_items = set()
    
    for plot_num, (kx, ky) in KNOWN_CENTERS.items():
        best_idx = None
        best_dist = 999
        
        for i, item in enumerate(all_items):
            if i in used_items:
                continue
            dx = item['cx_pct'] - kx
            dy = item['cy_pct'] - ky
            dist = (dx**2 + dy**2)**0.5
            
            if dist < best_dist:
                best_dist = dist
                best_idx = i
        
        if best_idx is not None and best_dist < 8.0:
            assigned[plot_num] = all_items[best_idx]
            used_items.add(best_idx)
    
    return assigned


def build_plot_data(assigned, labels, figma):
    """Build the final plot data with contour polygons."""
    h, w = figma.shape[:2]
    plots = []
    
    for plot_num in sorted(assigned.keys()):
        item = assigned[plot_num]
        
        if item['is_merged']:
            # Multi-polygon plot (river-split)
            polygons = []
            for r in item['region']['regions']:
                result = extract_contour_for_region(labels, r['label'], figma.shape)
                if result:
                    poly, _ = result
                    polygons.append(poly)
            
            if polygons:
                plots.append({
                    'plot_number': plot_num,
                    'cx_pct': item['cx_pct'],
                    'cy_pct': item['cy_pct'],
                    'polygon': polygons[0],  # Primary polygon
                    'polygons': polygons,     # All polygons for multi-part plots
                    'is_river_split': True,
                })
        else:
            # Single polygon plot
            r = item['region']
            result = extract_contour_for_region(labels, r['label'], figma.shape)
            if result:
                poly, _ = result
                plots.append({
                    'plot_number': plot_num,
                    'cx_pct': item['cx_pct'],
                    'cy_pct': item['cy_pct'],
                    'polygon': poly,
                    'polygons': [poly],
                    'is_river_split': False,
                })
    
    plots.sort(key=lambda p: p['plot_number'])
    return plots


def save_debug_image(figma, plots, labels):
    """Save a debug visualization."""
    h, w = figma.shape[:2]
    debug = figma.copy()
    
    colors = [
        (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0),
        (255, 0, 255), (0, 255, 255), (128, 0, 255), (255, 128, 0),
    ]
    
    for i, p in enumerate(plots):
        c = colors[i % len(colors)]
        
        for poly in p['polygons']:
            pts = np.array([[int(x / 100 * w), int(y / 100 * h)] for x, y in poly], dtype=np.int32)
            cv2.polylines(debug, [pts], True, c, 4)
        
        cx = int(p['cx_pct'] / 100 * w)
        cy = int(p['cy_pct'] / 100 * h)
        
        # Draw number label
        label = str(p['plot_number'])
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 2.0
        thickness = 4
        (tw, th), baseline = cv2.getTextSize(label, font, font_scale, thickness)
        cv2.rectangle(debug, (cx - tw//2 - 5, cy - th//2 - 5),
                     (cx + tw//2 + 5, cy + th//2 + 5), (0, 0, 0), -1)
        cv2.putText(debug, label, (cx - tw//2, cy + th//2),
                   font, font_scale, (255, 255, 255), thickness)
    
    # Scale down for output
    out = cv2.resize(debug, (w // 3, h // 3))
    cv2.imwrite(os.path.join(DEBUG_DIR, "contours_detected.png"), out)
    print(f"Debug image saved: {os.path.join(DEBUG_DIR, 'contours_detected.png')}")


def main():
    print("=" * 60)
    print("ROBUST PLOT CONTOUR DETECTION")
    print("=" * 60)
    
    # Step 1: Load images
    print("\n[1] Loading images...")
    figma, numbered = load_images()
    h, w = figma.shape[:2]
    print(f"    Image size: {w}x{h}")
    
    # Step 2: Extract borders
    print("\n[2] Extracting borders...")
    border_mask, black_mask, red_only_mask = get_border_mask(figma)
    red_dilated = get_red_border_mask(figma)
    print(f"    Border pixels: {np.count_nonzero(border_mask)}")
    print(f"    Black borders: {np.count_nonzero(black_mask)}")
    print(f"    Red borders: {np.count_nonzero(red_only_mask)}")
    cv2.imwrite(os.path.join(DEBUG_DIR, "borders.png"),
                cv2.resize(border_mask, (w // 4, h // 4)))
    
    # Step 3: Find gray fill regions
    print("\n[3] Finding gray fill regions...")
    regions, labels, gray_fill = find_gray_regions(figma, border_mask)
    print(f"    Found {len(regions)} significant regions")
    cv2.imwrite(os.path.join(DEBUG_DIR, "gray_fill.png"),
                cv2.resize(gray_fill, (w // 4, h // 4)))
    
    for r in regions:
        print(f"      ({r['cx_pct']:5.1f}%, {r['cy_pct']:5.1f}%)  area={r['area_pct']:.3f}%")
    
    # Step 4: Identify river-split plots
    print("\n[4] Identifying river-split plots...")
    normal_regions, merged_regions = merge_river_split_regions(
        regions, labels, red_dilated, figma)
    print(f"    Normal: {len(normal_regions)}, Merged pairs: {len(merged_regions)}")
    
    # Step 5: Assign plot numbers
    print("\n[5] Assigning plot numbers...")
    assigned = assign_plot_numbers_by_position(
        normal_regions, merged_regions, numbered)
    print(f"    Assigned: {len(assigned)}/43 plots")
    
    missing = set(range(1, 44)) - set(assigned.keys())
    if missing:
        print(f"    MISSING: {sorted(missing)}")
    else:
        print(f"    ALL 43 PLOTS ASSIGNED!")
    
    for pn in sorted(assigned.keys()):
        item = assigned[pn]
        tag = " [RIVER-SPLIT]" if item['is_merged'] else ""
        print(f"      Plot {pn:2d}: ({item['cx_pct']:5.1f}%, {item['cy_pct']:5.1f}%){tag}")
    
    # Step 6: Build plot data
    print("\n[6] Building plot data with contour polygons...")
    plots = build_plot_data(assigned, labels, figma)
    print(f"    Generated {len(plots)} plots with polygons")
    
    for p in plots:
        n_polys = len(p['polygons'])
        n_verts = sum(len(poly) for poly in p['polygons'])
        tag = f" [{n_polys} parts]" if p['is_river_split'] else ""
        print(f"      Plot {p['plot_number']:2d}: {n_verts} vertices{tag}")
    
    # Step 7: Save output
    print("\n[7] Saving output...")
    output = {
        'plots': [{
            'plot_number': p['plot_number'],
            'cx_pct': p['cx_pct'],
            'cy_pct': p['cy_pct'],
            'polygon': p['polygon'],
            'polygons': p['polygons'],
            'is_river_split': p['is_river_split'],
        } for p in plots]
    }
    
    with open(OUTPUT_JSON, 'w') as f:
        json.dump(output, f, indent=2)
    print(f"    JSON: {OUTPUT_JSON}")
    
    # Step 8: Debug visualization
    print("\n[8] Generating debug visualization...")
    save_debug_image(figma, plots, labels)
    
    print("\n" + "=" * 60)
    print("DONE!")
    print("=" * 60)


if __name__ == "__main__":
    main()
