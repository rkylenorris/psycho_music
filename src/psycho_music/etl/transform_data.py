import json
import pandas as pd

from pathlib import Path
from dataclasses import dataclass

from ..boilerplate import get_logger


logger = get_logger()

EXCLUDED_DAYLIO_DATA=["tag_colors", "milestones", "writingTemplates", "achievements", "goalSuccessWeeks", "reminders", "prefs", "assets"]


@dataclass
class DaylioTable():

    name: str
    data: pd.DataFrame


def get_daylio_tables(json_path: Path) -> list[DaylioTable]:

    if not json_path.exists():
        logger.error(f"JSON file '{json_path}' does not exist.")
        raise FileNotFoundError(f"JSON file '{json_path}' does not exist.")

    with json_path.open('r') as jp:
        daylio_data = json.load(jp)

    daylio_tables = []

    for k, v in daylio_data.items():
        if k not in EXCLUDED_DAYLIO_DATA and isinstance(v, list) and len(v) > 0:
            df = pd.DataFrame(v)
        else:
            continue

        if k == "customMoods":
            mapping = {2: "Good", 3: "Meh", 4: "Bad"}
            mask = df["id"].isin(mapping.keys())
            df.loc[mask, "custom_name"] = df.loc[mask, "id"].map(mapping)
        elif k == "dayEntries":
            tags_df = df[['id', 'tags']].explode('tags')
            tags_df = tags_df.rename(columns={'id': 'entry_id', 'tags': 'tag'})
            tags_df['tag'] = tags_df['tag'].fillna(None)
            # TODO: extract nested scales fields

        datetime_cols = [col for col in df.columns if "date" in col.lower() or "create" in col.lower()]
        for col in datetime_cols:
            try:
                df[col] = pd.to_datetime(df[col], errors='coerce', unit='ms')
            except Exception as e:
                logger.warning(f"Failed to convert column '{col}' to datetime: {e}")

        daylio_tables.append(DaylioTable(name=k, data=df))

    with open(Path(__file__).parent / "daylio_tables.json", 'r') as f:
        mood_groups = json.load(f)
        daylio_tables.append(DaylioTable(name="mood_groups", data=pd.DataFrame(mood_groups)))

    return daylio_tables


# dayEntries, customMoods, scales