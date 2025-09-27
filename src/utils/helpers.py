import os
import logging
import subprocess
from typing import Optional

from src.models import DownloadResult

def convert_thumbnail(input_thumbnail: str) -> Optional[str]:
    """
    Convert thumbnail to a Telegram-supported format (PNG)
    """
    if not input_thumbnail or not os.path.exists(input_thumbnail):
        return None
    
    output_thumbnail = input_thumbnail.rsplit('.', 1)[0] + '.png'
    
    try:
        # Try PIL first
        try:
            from PIL import Image
            img = Image.open(input_thumbnail)
            img.save(output_thumbnail, 'PNG')
            return output_thumbnail
        except ImportError:
            logging.getLogger(__name__).info("PIL not available, trying FFmpeg")
        
        # Use FFmpeg as fallback
        try:
            subprocess.run(
                ['ffmpeg', '-i', input_thumbnail, output_thumbnail],
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
        base_name = download_result.video_path.rsplit('.', 1)[0]
        
        files_to_clean = [
            download_result.video_path,
            download_result.thumbnail_path
        ]
        
        # Add possible thumbnail extensions
        for ext in ['webp', 'jpg', 'png']:
            thumbnail_path = f"{base_name}.{ext}"
            if thumbnail_path != download_result.thumbnail_path:  # Avoid duplicate entries
                files_to_clean.append(thumbnail_path)
        
        for file_path in files_to_clean:
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception as e:
                    logging.getLogger(__name__).error(f"Failed to remove {file_path}: {e}")
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
TELEGRAM_CHANNEL_ID=-100XXXXXXXXXX # Your channel ID (numeric, no quotes)

Replace the values with your actual Telegram API credentials.
You can obtain them from https://my.telegram.org/apps
"""
