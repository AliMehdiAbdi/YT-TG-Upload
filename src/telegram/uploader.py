import os
import time
import logging
from typing import Union, Optional, Callable
from pyrogram import Client
from pyrogram.errors import FloodWait

from src.models import DownloadResult
from src.config import config

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

    def upload_to_telegram(self, download_result: DownloadResult, progress_callback=None, status_callback: Optional[Callable[[str], None]] = None) -> bool:
        """
        Upload video to Telegram channel.
        
        If the client was started externally (via start() or context manager),
        reuses that session. Otherwise starts and stops for this single upload.
        
        Handles FloodWait by sleeping the requested number of seconds and
        retrying, up to MAX_FLOOD_WAIT_RETRIES attempts. Longer waits than
        MAX_FLOOD_WAIT_SEC abort immediately.
        
        :param download_result: DownloadResult with video path and metadata
        :param progress_callback: Optional callback(current_bytes, total_bytes) for upload progress
        :param status_callback: Optional callback(message: str) for status messages shown to the user
        """
        if not os.path.exists(download_result.video_path):
            raise FileNotFoundError(f"Video file not found: {download_result.video_path}")
        
        def _status(msg: str) -> None:
            if status_callback:
                status_callback(msg)
        
        # If session wasn't started externally, manage it for this single call
        manage_session = not self._started
        
        attempt = 0
        try:
            if manage_session:
                self.start()
            
            while True:
                attempt += 1
                try:
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
                
                except FloodWait as e:
                    # Pyrogram v2 renamed .x → .value; support both.
                    wait = getattr(e, 'value', None) or getattr(e, 'x', None)
                    if wait is None:
                        raise
                    if wait > config.max_flood_wait_sec:
                        raise RuntimeError(
                            f"FloodWait {wait}s exceeds {config.max_flood_wait_sec}s limit — aborting"
                        ) from e
                    if attempt > config.max_flood_wait_retries:
                        raise RuntimeError(
                            f"FloodWait retried {config.max_flood_wait_retries} times — giving up (last wait {wait}s)"
                        ) from e
                    
                    self.logger.warning(f"FloodWait {wait}s, attempt {attempt}/{config.max_flood_wait_retries}")
                    _status(f"Telegram requests {wait}s wait (attempt {attempt}/{config.max_flood_wait_retries}). Sleeping...")
                    time.sleep(wait + 1)
                    # loop and retry the same send_video
                
                except Exception as e:
                    self.logger.error(f"Upload failed: {e}")
                    raise RuntimeError(f"Failed to upload to Telegram: {e}") from e
        finally:
            if manage_session:
                self.stop()

