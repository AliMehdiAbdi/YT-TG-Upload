import os
import logging
import subprocess
from typing import Optional

from src.models import DownloadResult

def convert_thumbnail(input_thumbnail: str) -> Optional[str]:
    """
    Convert thumbnail to JPEG format for Telegram.
    No resizing — Pyrogram (MTProto) handles server-side scaling
    much better than client-side downscaling.
    """
    if not input_thumbnail or not os.path.exists(input_thumbnail):
        return None
    
    output_thumbnail = input_thumbnail.rsplit('.', 1)[0] + '.jpg'
    
    try:
        # Try PIL first
        try:
            from PIL import Image
            with Image.open(input_thumbnail) as img:
                img.convert('RGB').save(output_thumbnail, 'JPEG')
            return output_thumbnail
        except ImportError:
            logging.getLogger(__name__).info("PIL not available, trying FFmpeg")
        
        # Use FFmpeg as fallback
        try:
            subprocess.run(
                ['ffmpeg', '-y', '-i', input_thumbnail, output_thumbnail],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            return output_thumbnail
        except (subprocess.SubprocessError, FileNotFoundError):
            return None
            
    except Exception as e:
        logging.getLogger(__name__).error(f"Thumbnail conversion failed: {e}")
        return None

def cleanup(download_result: DownloadResult) -> None:
    """
    Clean up downloaded files
    """
    deleted = set()
    try:
        # Delete video file
        if download_result.video_path and os.path.exists(download_result.video_path):
            os.remove(download_result.video_path)
            deleted.add(os.path.abspath(download_result.video_path))
        
        # Delete thumbnail if set
        if download_result.thumbnail_path and os.path.exists(download_result.thumbnail_path):
            abs_path = os.path.abspath(download_result.thumbnail_path)
            if abs_path not in deleted:
                os.remove(download_result.thumbnail_path)
                deleted.add(abs_path)
        
        # Get base name for additional thumbnails (originals before conversion)
        base_name = download_result.video_path.rsplit('.', 1)[0]
        for ext in ['webp', 'jpg', 'png', 'jpeg']:
            potential_thumbnail = f"{base_name}.{ext}"
            abs_path = os.path.abspath(potential_thumbnail)
            if abs_path not in deleted and os.path.exists(potential_thumbnail):
                os.remove(potential_thumbnail)
                deleted.add(abs_path)
        
    except Exception as e:
        logging.getLogger(__name__).error(f"Cleanup error: {e}")

def get_env_setup_instructions() -> str:
    """
    Return instructions for setting up environment variables
    """
    return """
Create a .env file in the same directory as this script with the following content:

TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHANNEL_ID=-100XXXXXXXXXX

Replace the values with your actual Telegram API credentials.
You can obtain them from https://my.telegram.org/apps
"""

def format_size(size_mb: float) -> str:
    """
    Convert a size in MB to a human-readable string.
    
    :param size_mb: Size in megabytes
    :return: Formatted string (e.g. '320 MB', '1.2 GB', or 'unknown')
    """
    if size_mb <= 0:
        return "unknown"
    if size_mb >= 1024:
        return f"{size_mb / 1024:.1f} GB"
    return f"{size_mb:.0f} MB"

