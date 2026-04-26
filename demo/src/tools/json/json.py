import json
from pathlib import Path

def save_as_json(file_path: str, data: dict) -> None:
    """Save or merge dictionary data to a json file"""
    # 1. Handle Path objects natively
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    # 2. Merge with existing data if it exists
    if file_path.exists():
        existing_data = load_json(file_path) or {}
        # Merge dictionaries. In Python 3.9+, you can use the | operator. 
        # It creates a new dict with updated values.
        merged_data = existing_data | data
    else:
        merged_data = data

    # 3. Write securely
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(merged_data, f, indent=2)

def load_json(file_path: str) -> dict:
    """Load data from a json file securely"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {} # Return empty dict if file doesn't exist yet
    except json.JSONDecodeError:
        print(f"File {file_path} is corrupted or empty. Returning empty dict.")
        return {}
    except Exception as e:
        print(f"Error reading {file_path}: {e}")
        return {}