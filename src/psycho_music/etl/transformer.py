import json
import pandas as pd
import sqlite3 as sql

from pathlib import Path
from dataclasses import dataclass

from .db_cmds import get_connection
from ..boilerplate import get_logger, AppSettings


logger = get_logger()

EXCLUDED_DAYLIO_DATA=["tag_colors", "milestones", "writingTemplates", "achievements", "goalSuccessWeeks", "reminders", "prefs", "assets"]


@dataclass
class DaylioTable:

    name: str
    data: pd.DataFrame

    def timestamps_to_datetime(self):
        datetime_cols = [col for col in self.data.columns if "date" in col.lower() or "create" in col.lower()]
        for col in datetime_cols:
            try:
                self.data[col] = pd.to_datetime(self.data[col], errors='coerce', unit='ms')
            except Exception as e:
                logger.warning(f"Failed to convert column '{col}' to datetime: {e}")

    def to_sql(self, engine: sql.Connection):
        self.data.to_sql(self.name, con=engine, if_exists='replace', index=False)




class DaylioDataTransformer:

    def __init__(self, settings: AppSettings):
        self.settings = settings
        self.json_path = Path(self.settings.data_dir) / 'daylio.json'
        self.tables: list[DaylioTable] = []
        self.mood_groups_path = Path(__file__).parent / "mood_groups.json"

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
        with get_connection(self.settings.db_path) as conn:
            for table in self.tables:
                table.to_sql(conn)
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
                tags_df = self._explode_table_column(table, ['id', 'tags'], 'tags', {'id': 'entry_id', 'tags': 'tag'})
                self.tables.append(DaylioTable(name="dayEntryTags", data=tags_df))
                table.data = table.data.drop(columns=['tags'])

                self._explode_entry_scales(table)
                table.data = table.data.drop(columns=['scaleValues'])
                break

    def _explode_table_column(self, table: DaylioTable, select_columns: list[str], column_explode: str, columns_rename: dict[str, str] | None = None):
        exploded = table.data[select_columns].dropna().explode(column_explode).dropna()
        if columns_rename:
            return exploded.rename(columns=columns_rename)
        else:
            return exploded

    def _explode_entry_scales(self, table: DaylioTable):

        scales_exploded = self._explode_table_column(table, ['id', 'scaleValues'], 'scaleValues')

        scales_unnested = pd.json_normalize(scales_exploded['scaleValues']).reset_index(drop=True)

        entry_scales_df = pd.concat(
            [scales_exploded[['id']].reset_index(drop=True), scales_unnested],
            axis=1,
        ).rename(columns={'id': 'entry_id', 'id_scale': 'scale_id', 'number_value': 'scale_value'})

        self.tables.append(DaylioTable('dayEntryScales', entry_scales_df))

    def _normalize_scales(self):        
        for table in self.tables:
            if table.name == "scales":
                logger.info("Normalizing scales table...")

                unpacked = pd.json_normalize(table.data['number_scale']).reset_index(drop=True)
                table.data = pd.concat([table.data[['id', 'name', 'created_at']].reset_index(drop=True), unpacked], axis=1)
                
                break