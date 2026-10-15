"""Device catalogue and the device list shown in the device hub.

The hub talks to one device today, the DL8780 scale. The catalogue and the
device records are kept generic so more models can be added as rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from bathroom_hub.db import Database

SCALE_ID = "scale"


@dataclass(frozen=True)
class Model:
    model: str
    name: str
    category: str
    support: str  # "supported" | "planned"
    measures: str
    pairing: str | None = None


CATALOGUE: tuple[Model, ...] = (
    Model(
        model="DL8780",
        name="Body analysis scale",
        category="Scales",
        support="supported",
        measures="Weight, body fat, lean mass",
        pairing="Hold the unit button on the scale for 3 seconds, until the pairing symbols alternate.",
    ),
    Model(
        model="HX9393",
        name="Sonicare DiamondClean toothbrush",
        category="Oral care",
        support="planned",
        measures="Brushing sessions",
    ),
)

CATEGORIES: tuple[str, ...] = ("Scales", "Oral care")


def category_counts() -> list[tuple[str, int]]:
    return [
        (category, sum(1 for model in CATALOGUE if model.category == category))
        for category in CATEGORIES
    ]


def search_catalogue(query: str = "", category: str = "") -> list[Model]:
    query = query.strip().lower()
    results = []
    for model in CATALOGUE:
        if category and model.category != category:
            continue
        if (
            query
            and query not in f"{model.model} {model.name} {model.category}".lower()
        ):
            continue
        results.append(model)
    return results


def model_info(model: str) -> Model | None:
    return next((item for item in CATALOGUE if item.model == model), None)


def hub_devices(status: dict[str, Any], db: Database) -> list[dict[str, Any]]:
    """Devices the hub knows about, as plain dicts for the templates."""
    devices = []
    if status.get("paired") or status.get("address"):
        latest = db.latest_measurement()
        last_weigh = datetime.fromisoformat(latest["measured_at"]) if latest else None
        if not status.get("paired"):
            state, note = "attention", "Not paired with the hub. Pair it again."
        elif status.get("state") == "connected":
            state, note = "online", "Connected now"
        elif status.get("state") == "disabled":
            state, note = "attention", "Bluetooth is off on the hub"
        else:
            state, note = "online", "Listening"
        devices.append(
            {
                "id": SCALE_ID,
                "name": db.get_setting("device_scale_name", "Bathroom scale"),
                "room": db.get_setting("device_scale_room", "Bathroom"),
                "model": "DL8780",
                "category": "Scales",
                "state": state,
                "note": note,
                "last_weigh": last_weigh,
                "address": status.get("address"),
                "serial": db.get_setting("scale_serial"),
            }
        )
    return devices
