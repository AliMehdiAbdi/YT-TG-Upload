"""
Centralised configuration constants for YT-TG-Upload.

All tunable magic numbers live here so they can be adjusted in one place
instead of hunting through multiple modules.
"""
from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class Config:
    """Immutable application-wide defaults. Override by creating a new instance."""

    # Download / container settings
    valid_containers: Tuple[str, ...] = ('mp4', 'mkv', 'webm')
    concurrent_fragment_downloads: int = 10

    # Size limits (MB)
    default_max_size_mb: int = 2048

    # Telegram FloodWait retry policy
    max_flood_wait_retries: int = 3
    max_flood_wait_sec: int = 900  # 15 minutes — abort if Telegram asks for longer


# Singleton used throughout the app.
config = Config()
