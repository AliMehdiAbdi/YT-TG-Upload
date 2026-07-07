import os
import logging
import subprocess
from typing import Optional

from src.models import DownloadResult

def convert_thumbnail(input_thumbnail: str) -> Optional[str]:
    """
    Convert thumbnail to a Telegram-supported format (JPEG, max 320x320, < 200KB)
    """
    if not input_thumbnail or not os.path.exists(input_thumbnail):
        return None
    
    output_thumbnail = input_thumbnail.rsplit('.', 1)[0] + '.jpg'
    
    try:
        # Try PIL first
        try:
            from PIL import Image
            img = Image.open(input_thumbnail)
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
            # Maintain aspect ratio, max 320px
            # Image.Resampling.LANCZOS is high-quality downsampling
            if hasattr(Image, 'Resampling'):
                img.thumbnail((320, 320), Image.Resampling.LANCZOS)
            else:
                img.thumbnail((320, 320), Image.ANTIALIAS) # Fallback for older PIL
            
            img.save(output_thumbnail, 'JPEG', quality=90)
            return output_thumbnail
        except ImportError:
            logging.getLogger(__name__).info("PIL not available, trying FFmpeg")
        
        # Use FFmpeg as fallback
        try:
            subprocess.run(
                ['ffmpeg', '-y', '-i', input_thumbnail, '-vf', 'scale=320:320:force_original_aspect_ratio=decrease', '-q:v', '2', output_thumbnail],
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
    try:
        # Delete video file
        if download_result.video_path and os.path.exists(download_result.video_path):
            os.remove(download_result.video_path)
        
        # Delete thumbnail if set
        if download_result.thumbnail_path and os.path.exists(download_result.thumbnail_path):
            os.remove(download_result.thumbnail_path)
        
        # Get base name for additional thumbnails (originals before conversion)
        base_name = download_result.video_path.rsplit('.', 1)[0]
        for ext in ['webp', 'jpg', 'png', 'jpeg']:
            potential_thumbnail = f"{base_name}.{ext}"
            if os.path.exists(potential_thumbnail):
                os.remove(potential_thumbnail)
        
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

