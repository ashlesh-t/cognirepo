import json
import os
from datetime import datetime


FILE = ".cognirepo/memory/episodic.json"


def log_event(event):

    if not os.path.exists(FILE):
        with open(FILE, "w") as f:
            json.dump([], f)

    with open(FILE) as f:
        data = json.load(f)

    data.append({
        "event": event,
        "time": str(datetime.now())
    })

    with open(FILE, "w") as f:
        json.dump(data, f)