import json
import pandas as pd

from pathlib import Path
from dataclasses import dataclass

from .db_cmds import create_connection

from ..boilerplate import get_logger, get_app_settings

settings = get_app_settings()
logger = get_logger()

EXCLUDED_DAYLIO_DATA=["tag_colors", "milestones", "writingTemplates", "achievements", "goalSuccessWeeks", "reminders", "prefs", "assets"]


@dataclass
class DaylioTable():

    name: str
    data: pd.DataFrame

    def timestamps_to_datetime(self):
        datetime_cols = [col for col in self.data.columns if "date" in col.lower() or "create" in col.lower()]
        for col in datetime_cols:
            try:
                self.data[col] = pd.to_datetime(self.data[col], errors='coerce', unit='ms')
            except Exception as e:
                logger.warning(f"Failed to convert column '{col}' to datetime: {e}")

    def to_sql(self, engine=create_connection(settings.db_path)):
        if engine:
            self.data.to_sql(self.name, con=engine, if_exists='replace', index=False)
            engine.commit()
            engine.close()



class DaylioDataTransformer:

    def __init__(self):
        self.json_path = Path(settings.data_dir) / 'daylio.json'
        self.tables: list[DaylioTable] = []
        self.mood_groups_path = Path(__file__).parent / "daylio_tables.json"

    def transform(self):
        logger.info("Starting transformation of Daylio data...")
        self._load_daylio_data()
        self._create_mood_groups_table()
        self._map_missing_custom_moods()
        self._process_day_entries()
        self._normalize_scales()

        for table in self.tables:
            table.timestamps_to_datetime()

        return self

    def load_to_db(self):
        logger.info("Loading transformed data into the database...")
        for table in self.tables:
            table.to_sql()
        logger.info("Data loading complete.")

    def _load_daylio_data(self):
        if not self.json_path.exists():
            logger.error(f"JSON file '{self.json_path}' does not exist.")
            raise FileNotFoundError(f"JSON file '{self.json_path}' does not exist.")

        with self.json_path.open('r') as jp:
            daylio_data = json.load(jp)

        logger.info("Loading Daylio data into memory...")
        for name, data in daylio_data.items():
            if name not in EXCLUDED_DAYLIO_DATA and isinstance(data, list) and len(data) > 0:
                df = pd.DataFrame(data)
                table = DaylioTable(name=name, data=df)
                self.tables.append(table)

    def _create_mood_groups_table(self):
        logger.info("Creating mood_groups table from daylio_tables.json...")
        with self.mood_groups_path.open('r') as f:
            mood_groups = json.load(f)
            self.tables.append(DaylioTable(name="mood_groups", data=pd.DataFrame(mood_groups)))

    def _map_missing_custom_moods(self):
        logger.info("Mapping missing custom moods...")
        for table in self.tables:
            if table.name == "customMoods":
                mapping = {2: "Good", 3: "Meh", 4: "Bad"}
                mask = table.data["id"].isin(mapping.keys())
                table.data.loc[mask, "custom_name"] = table.data.loc[mask, "id"].map(mapping)
                break

    def _process_day_entries(self):
        for table in self.tables:
            if table.name == "dayEntries":
                logger.info("Processing dayEntries table to create dayEntryTags and dayEntryScales tables...")
                tags_df = table.data[['id', 'tags']].explode('tags')
                tags_df = tags_df.rename(columns={'id': 'entry_id', 'tags': 'tag'})
                tags_df['tag'] = tags_df['tag'].fillna(None)
                self.tables.append(DaylioTable(name="dayEntryTags", data=tags_df))
                table.data = table.data.drop(columns=['tags'])

                entry_scales_df = pd.json_normalize(table.data.to_records(index=False), "id", [['scaleValues', 'id_scale'], ['scaleValues', 'number_value']])
                entry_scales_df = entry_scales_df.rename(columns={'id': 'entry_id', 'scaleValues.id_scale': 'scale_id', 'scaleValues.number_value': 'scale_value'})
                self.tables.append(DaylioTable(name="dayEntryScales", data=entry_scales_df))
                table.data = table.data.drop(columns=['scaleValues'])
                break

    def _normalize_scales(self):
        columns = ['id', 'name', 'created_at', 'number_scale']
        for table in self.tables:
            if table.name == "scales":
                logger.info("Normalizing scales table...")
                table.data = pd.json_normalize(table.data[columns].to_records(index=False))
                break