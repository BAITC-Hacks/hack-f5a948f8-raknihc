"""Read the original JSON/CSV files without changing them."""
import csv
import json
from pathlib import Path

def load_dataset(directory):
    directory = Path(directory)
    def read(name):
        return json.loads((directory / name).read_text(encoding="utf-8-sig"))
    employees = read("employees.json")
    skills = read("skills.json")
    events = read("events.json")
    with (directory / "activity_history.csv").open(encoding="utf-8-sig", newline="") as file:
        history = list(csv.DictReader(file))
    return {"employees": employees["employees"], "history": history,
            "events": events["events"], "catalog": skills,
            "as_of_date": employees["meta"]["as_of_date"]}
