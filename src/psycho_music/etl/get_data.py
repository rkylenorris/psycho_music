import os
import json
import shutil
import base64
import hashlib
import zipfile as zf

from datetime import datetime
from pathlib import Path
from datetime import datetime

from ..boilerplate import get_app_settings, get_logger


logger = get_logger()
app_settings = get_app_settings()


class DaylioBackupDirectoryNotFoundError(Exception):
    """Custom exception raised when the Daylio backup directory is not found."""
    pass


class DaylioBackupNotFoundError(Exception):
    """Custom exception raised when a Daylio backup file is not found."""
    pass


class DaylioBackupData:
    """
    Class for finding, decoding, and checking if daylio data is new.
    """

    def __init__(self):
        self.pickup_dir: Path = Path(app_settings.pickup_dir)
        self.data_dir: Path = Path(app_settings.data_dir)
        self.archive_dir: Path = self.data_dir / 'archive'
        self.hashes_file_path: Path = Path(app_settings.consumed_files_hashes_file)
        self.extracted_path: Path = self.data_dir / 'backup.daylio'
        self.json_path = self.data_dir / 'daylio.json'
        self.consumed_hashes: set[str] = self._load_consumed_hashes()

        if not self.pickup_dir.exists():
            logger.error(f"Pickup directory '{self.pickup_dir}' does not exist.")
            raise DaylioBackupDirectoryNotFoundError(
                f"Pickup directory '{self.pickup_dir}' does not exist."
            )

        if not self.data_dir.exists():
            logger.info(f"Data directory '{self.data_dir}' does not exist. Creating it.")
            self.data_dir.mkdir(parents=True, exist_ok=True)

        if not self.archive_dir.exists():
            logger.info(f"Archive directory '{self.archive_dir}' does not exist. Creating it.")
            self.archive_dir.mkdir(parents=True, exist_ok=True)

        self.backup_path: Path = self._find_backup()
        self.backup_date: datetime = self._get_backup_date()
        

    def _load_consumed_hashes(self) -> set[str]:
        """Load the hashes of consumed files from the hashes file."""
        if not self.hashes_file_path.exists():
            logger.info(f"Hashes file '{self.hashes_file_path}' does not exist. Creating it.")
            self.hashes_file_path.touch()
            return set()

        with self.hashes_file_path.open('r') as f:
            return set(line.strip() for line in f if line.strip())


    def _get_file_hash(self, file_path: Path) -> str:
            """Calculate the SHA256 hash of a file."""
    
            sha256_hash = hashlib.sha256()
            with file_path.open("rb") as f:
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)
            return sha256_hash.hexdigest()
    
    
    def _add_hash_to_consumed(self, file_hash: str) -> None:
            """Add a file hash to the consumed hashes set and update the hashes file."""
            self.consumed_hashes.add(file_hash)
            with self.hashes_file_path.open('a') as f:
                f.write(file_hash + '\n')


    def _find_backup(self) -> Path:

        todays_file_name = datetime.today().strftime('backup_%Y_%m_%d.daylio')
        todays_file_path = self.pickup_dir / todays_file_name

        if todays_file_path.exists():
            logger.info(f"Found Daylio backup file: {todays_file_path}")
            return todays_file_path
        else:
            logger.info(f"No backup file for today found. Searching for the most recent backup in '{self.pickup_dir}'...")
            files = [f for f in self.pickup_dir.glob("backup*.daylio") if f.is_file()]
            daylio_file = max(files, key=os.path.getctime, default=None)
            if daylio_file:
                logger.info(f"Found Daylio backup file: {daylio_file}")
                return daylio_file
            else:
                logger.error(f"No Daylio backup files found in '{self.pickup_dir}'.")
                raise DaylioBackupNotFoundError(
                    f"No Daylio backup files found in '{self.pickup_dir}'."
                )


    def _get_backup_date(self) -> datetime:
        """Extract the date from the backup file name."""
        try:
            date_str = self.backup_path.stem.split('_')[1:]  # Skip 'backup'
            return datetime.strptime('_'.join(date_str), '%Y_%m_%d')
        except IndexError:
            logger.error(f"Unexpected backup file name format: {self.backup_path.name}")
            raise ValueError(f"Unexpected backup file name format: {self.backup_path.name}")


    def _extract_backup(self) -> None:
        """extract daylio data from zip archive"""

        logger.info(f"Extracting Daylio backup from '{self.backup_path}' to '{self.data_dir}'...")

        copy_target = self.data_dir / self.backup_path.name
        self.backup_path.copy(copy_target)

        if self.extracted_path.exists():
            logger.info(f"Extracted backup file already exists at '{self.extracted_path}'. Deleting it.")
            self.extracted_path.unlink()

        with zf.ZipFile(copy_target, 'r') as zr:
            zr.extractall(self.data_dir)
            assets_dir = self.data_dir / 'assets'
            if assets_dir.exists():
                shutil.rmtree(assets_dir)

        copy_target.unlink()


    def _is_new_backup(self) -> bool:
        """Check if the backup file is new (not consumed)."""
        logger.debug(f"Checking if backup file '{self.backup_path}' is new...")

        backup_hash = self._get_file_hash(self.backup_path)
        if backup_hash not in self.consumed_hashes:
            logger.info(f"Backup file '{self.backup_path}' is new. Adding its hash to consumed hashes.")
            self._add_hash_to_consumed(backup_hash)
            return True
        else:
            logger.info(f"Backup file '{self.backup_path}' has already been consumed.")
            return False


    def _decode_backup_to_json(self) -> None:
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
        if json_archive_path.exists():
            json_archive_path.unlink()
        json_path.copy(json_archive_path)


    def extract_data(self) -> Path:
        """
        Main method to get Daylio data. It checks for new backups, extracts them, and decodes to JSON.
        Returns the path to the JSON file.
        """
        if self._is_new_backup():
            self._extract_backup()
            self._decode_backup_to_json()
            logger.info(f"Daylio data has been updated and is available at '{self.json_path}'.")
        else:
            logger.info(f"No new Daylio backup found. Using existing JSON file at '{self.json_path}'.")

        return self.json_path