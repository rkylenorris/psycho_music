import os
import re
import json
import shutil
import base64
import hashlib
import zipfile as zf

from pathlib import Path
from datetime import datetime
from dataclasses import dataclass

from ..boilerplate import AppSettings, get_logger

logger = get_logger()


class DaylioBackupDirectoryNotFoundError(Exception):
    """Custom exception raised when the Daylio backup directory is not found."""
    pass


class DaylioBackupNotFoundError(Exception):
    """Custom exception raised when a Daylio backup file is not found."""
    pass


class DaylioBackupMissingDate(Exception):
    pass


@dataclass
class DaylioBackupHash:
    date: str
    hash: str


class DaylioBackupData:
    """
    Class for finding, decoding, and checking if daylio data is new.
    """

    def __init__(self, app_settings: AppSettings):
        self.pickup_dir: Path = Path(app_settings.pickup_dir)
        self.data_dir: Path = Path(app_settings.data_dir)
        self.archive_dir: Path = self.data_dir / 'archive'
        self.hashes_file_path: Path = Path(app_settings.consumed_files_hashes_file)
        self.extracted_path: Path = self.data_dir / 'backup.daylio'
        self.json_path = self.data_dir / 'daylio.json'
        self.consumed_hashes: list[DaylioBackupHash] = self._load_consumed_hashes()
        self.backup_path: Path
        self.backup_date: datetime
        self.backup_hash: DaylioBackupHash
        self.data_dir_backup_copy: Path


    def _load_consumed_hashes(self) -> list[DaylioBackupHash]:
        """Load the hashes of consumed files from the hashes file."""
        if not self.hashes_file_path.exists():
            logger.info(f"Hashes file '{self.hashes_file_path}' does not exist. Creating it.")
            with self.hashes_file_path.open('w') as h:
                 h.write('[]')
            return []

        with self.hashes_file_path.open('r') as f:
            hashes = json.load(f)
            return [DaylioBackupHash(**h) for h in hashes]


    def get_file_hash(self):
            """Calculate the SHA256 hash of a file."""
    
            sha256_hash = hashlib.sha256()
            with self.extracted_path.open("rb") as f:
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)
            self.backup_hash = DaylioBackupHash(self.backup_date.strftime('%Y.%m.%d'), sha256_hash.hexdigest())
    
    
    def add_hash_to_consumed(self) -> None:
            """Add a file hash to the consumed hashes set and update the hashes file."""
            self.consumed_hashes.append(self.backup_hash)
            with self.hashes_file_path.open('w') as f:
                json.dump([d.__dict__ for d in self.consumed_hashes], f)

    
    def find_backup(self):

        if not self.pickup_dir.exists():
                    logger.error(f"Pickup directory '{self.pickup_dir}' does not exist.")
                    raise DaylioBackupDirectoryNotFoundError(
                        f"Pickup directory '{self.pickup_dir}' does not exist."
                    )

        todays_file_name = datetime.today().strftime('backup_%Y_%m_%d.daylio')
        todays_file_path = self.pickup_dir / todays_file_name

        if todays_file_path.exists():
            logger.info(f"Found Daylio backup file: {todays_file_path}")
            self.backup_path = todays_file_path
            self._get_backup_date()
        else:
            logger.info(f"No backup file for today found. Searching for the most recent backup in '{self.pickup_dir}'...")
            files = [f for f in self.pickup_dir.glob("backup*.daylio") if f.is_file()]
            daylio_file = max(files, key=os.path.getctime, default=None)
            if daylio_file:
                logger.info(f"Found Daylio backup file: {daylio_file}")
                self.backup_path = daylio_file
                self._get_backup_date()
            else:
                logger.error(f"No Daylio backup files found in '{self.pickup_dir}'.")
                raise DaylioBackupNotFoundError(
                    f"No Daylio backup files found in '{self.pickup_dir}'."
                )


    def _get_backup_date(self):
        """Extract the date from the backup file name."""
        date_search = re.search(r"(\d{4}_\d{2}_\d{2})", self.backup_path.name)
        if date_search:
            date_str = date_search.group()
            self.backup_date = datetime.strptime(date_str, '%Y_%m_%d')
        else:
            raise DaylioBackupMissingDate(f"Backup '{self.backup_path}' missing expected date string in file name.")


    def copy_backup(self):
        logger.info("Copying backup to local data directory...")
        if not self.data_dir.exists():
                    logger.debug(f"Data directory '{self.data_dir}' does not exist. Creating it.")
                    self.data_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir_backup_copy = self.data_dir / self.backup_path.name
        if self.data_dir_backup_copy.exists():
            self.data_dir_backup_copy.unlink()
        shutil.copy2(self.backup_path, self.data_dir_backup_copy)
        logger.info("Copy completed.")


    def extract_backup(self) -> None:
        """extract daylio data from zip archive"""

        logger.info(f"Extracting Daylio backup from '{self.data_dir_backup_copy}'..")

        if self.extracted_path.exists():
            logger.debug(f"Extracted backup file already exists at '{self.extracted_path}'. Deleting it.")
            self.extracted_path.unlink()

        with zf.ZipFile(self.data_dir_backup_copy, 'r') as zr:
            zr.extractall(self.data_dir)
            assets_dir = self.data_dir / 'assets'
            if assets_dir.exists():
                shutil.rmtree(assets_dir)

        logger.info(f'{self.data_dir_backup_copy.name} extraction complete.')


    def is_new_backup(self) -> bool:
        """Check if the backup file is new (not consumed)."""
        logger.debug(f"Checking if backup file '{self.backup_path}' is new...")

        if self.backup_hash not in self.consumed_hashes:
            logger.info(f"Backup file '{self.backup_path}' is new.")
            return True
        else:
            logger.info(f"Backup file '{self.backup_path}' has already been consumed")
            return False


    def decode_backup_to_json(self) -> None:
        logger.info(f"Decoding backup file '{self.backup_path}' to JSON...")
        json_path = self.json_path
        json_archive_path = self.archive_dir / f"daylio_{self.backup_date.strftime('%Y_%m_%d')}.json"
        with open(self.extracted_path) as f:
            contents = base64.b64decode(f.read()).decode("utf-8")

        daylio_data = json.loads(contents) if contents else []

        if json_path.exists():
            logger.debug(f"JSON file '{json_path}' already exists. Deleting it.")
            json_path.unlink()

        with json_path.open('w') as jp:
            json.dump(daylio_data, jp, indent=4)

        logger.info(f"Copying JSON file '{json_path}' to archive '{json_archive_path}'...")

        if not self.archive_dir.exists():
                    logger.debug(f"Archive directory '{self.archive_dir}' does not exist. Creating it.")
                    self.archive_dir.mkdir(parents=True, exist_ok=True)

        if json_archive_path.exists():
            json_archive_path.unlink()

        shutil.copy2(json_path, json_archive_path)

    def extract(self) -> Path:
        self.find_backup()
        self.copy_backup()
        self.extract_backup()
        self.get_file_hash()
        if self.is_new_backup():
            self.decode_backup_to_json()
            self.add_hash_to_consumed()
        return self.json_path
            
