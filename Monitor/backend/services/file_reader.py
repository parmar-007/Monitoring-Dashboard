import json
from pathlib import Path

# Shared PVC path
LOGS_PATH = "../logs"


def get_applications_by_date(selected_date):

    results = []

    logs_root = Path(LOGS_PATH)

    # Loop through all application folders

    for app_folder in logs_root.iterdir():

        if not app_folder.is_dir():
            continue

        file_path = app_folder / f"{selected_date}.json"

        if file_path.exists():

            with open(file_path, "r") as file:

                data = json.load(file)

                results.append(data)

    return results