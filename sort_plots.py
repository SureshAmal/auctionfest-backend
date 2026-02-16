
import json
import os

FILE_PATH = "backend/plot_data_v2.json"

def sort_json():
    if not os.path.exists(FILE_PATH):
        print(f"File not found: {FILE_PATH}")
        return

    with open(FILE_PATH, 'r') as f:
        data = json.load(f)

    # data is a list of objects
    if isinstance(data, list):
        # Sort by id, handling potential None values
        data.sort(key=lambda x: x.get("id") if x.get("id") is not None else 999999)
        print(f"Sorted {len(data)} plot entries by id.")
        
        with open(FILE_PATH, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"Saved sorted data to {FILE_PATH}")
    else:
        print("Error: JSON root is not a list, cannot sort.")

if __name__ == "__main__":
    sort_json()
