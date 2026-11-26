import sys

from enum import Enum
from uuid import uuid4
from typing import TextIO
from pydantic import BaseModel, ConfigDict
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


def _generate_run_guid() -> str:
    return str(uuid4())



class LogFileSettings(BaseModel):
    log_level: int
    file_path: str


class ConsoleLogSettings(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    output: TextIO = sys.stdout
    log_level: int
    format: str = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | {name}:{function} - "
        "{message}"
    )


class LoggingSettings(BaseModel):

    run_guid: str = _generate_run_guid()
    console_settings: ConsoleLogSettings
    flat_file_settings: LogFileSettings
    json_file_settings: LogFileSettings


class AppSettings(BaseSettings):

    model_config = SettingsConfigDict(env_file=".env",
                                      env_file_encoding="utf-8",
                                      env_nested_delimiter="__",
                                      case_sensitive=False)

    app_name: str
    pickup_dir: str
    data_dir: str
    consumed_files_hashes_file: str
    logging: LoggingSettings
    excluded_daylio_data: list[str]
    db_path: str


@lru_cache
def get_app_settings() -> AppSettings:
    return AppSettings()  # type: ignore
