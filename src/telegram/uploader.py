import os
import logging
from typing import Union, Optional
from pyrogram import Client

from src.models import DownloadResult

class TelegramUploader:
    def __init__(self, bot_token: str, channel_id: Union[str, int]):
        """
        Initialize the Telegram uploader with bot credentials.
        
        :param bot_token: Telegram bot token
        :param channel_id: Telegram channel ID (can be string username or integer ID)
        """
        if not bot_token or not isinstance(bot_token, str):
            raise ValueError("Bot token must be a non-empty string")
        
        self.channel_id = channel_id
        
        api_id = os.getenv('TELEGRAM_API_ID')
        api_hash = os.getenv('TELEGRAM_API_HASH')
        
        if not api_id or not api_hash:
            raise ValueError("TELEGRAM_API_ID and TELEGRAM_API_HASH must be set in environment variables")
        
        self.app = Client(
            "youtube_downloader_bot",
            bot_token=bot_token,
            api_id=api_id,
            api_hash=api_hash
        )
        self._started = False
        
        self.logger = logging.getLogger(__name__)

    def start(self) -> None:
        """Start the Pyrogram client session. Call once before batch uploads."""
        if not self._started:
            self.app.start()
            self._started = True

    def stop(self) -> None:
        """Stop the Pyrogram client session. Call once after batch uploads."""
        if self._started:
            self.app.stop()
            self._started = False

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False

    def upload_to_telegram(self, download_result: DownloadResult, progress_callback=None) -> bool:
        """
        Upload video to Telegram channel.
        
        If the client was started externally (via start() or context manager),
        reuses that session. Otherwise starts and stops for this single upload.
        
        :param download_result: DownloadResult with video path and metadata
        :param progress_callback: Optional callback(current_bytes, total_bytes) for upload progress
        """
        if not os.path.exists(download_result.video_path):
            raise FileNotFoundError(f"Video file not found: {download_result.video_path}")
        
        # If session wasn't started externally, manage it for this single call
        manage_session = not self._started
        
        try:
            if manage_session:
                self.start()
            
            kwargs = {
                'chat_id': self.channel_id,
                'video': download_result.video_path,
                'caption': download_result.video_title,
                'duration': download_result.duration
            }
            
            if download_result.thumbnail_path and os.path.exists(download_result.thumbnail_path):
                kwargs['thumb'] = download_result.thumbnail_path
            
            if progress_callback:
                kwargs['progress'] = progress_callback
            
            self.app.send_video(**kwargs)
            return True
        
        except Exception as e:
            self.logger.error(f"Upload failed: {e}")
            raise RuntimeError(f"Failed to upload to Telegram: {e}")
        finally:
            if manage_session:
                self.stop()

