import os
import logging
from typing import Optional, Tuple, Dict, Any, TypedDict, List, Union
import subprocess
import re
from dataclasses import dataclass
from urllib.parse import urlparse, parse_qs
import yt_dlp
from pyrogram import Client
from pyrogram.types import InputMediaVideo
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class VideoFormat(TypedDict):
    format_id: str
    resolution: int
    fps: int
    ext: str
    size_mb: float

class AudioFormat(TypedDict):
    format_id: str
    bitrate: float
    ext: str

class VideoInfo(TypedDict):
    video_formats: Dict[str, VideoFormat]
    audio_formats: Dict[str, AudioFormat]
    title: str
    duration: int
    thumbnail: Optional[str]

@dataclass
class DownloadResult:
    video_path: str
    thumbnail_path: Optional[str]
    video_title: str
    duration: int

class YouTubeTelegramDownloader:
    def __init__(self, bot_token: str, channel_id: Union[str, int], cookies_file: Optional[str] = None):
        """
        Initialize the downloader with Telegram bot credentials and optional cookies
        
        :param bot_token: Telegram bot token
        :param channel_id: Telegram channel ID (can be string or integer)
        :param cookies_file: Optional path to Netscape-format cookie file
        """
        # Validate inputs
        if not bot_token or not isinstance(bot_token, str):
            raise ValueError("Bot token must be a non-empty string")
        
        # Ensure channel_id is converted to string for Pyrogram
        self.channel_id = str(channel_id)
        
        # Get API credentials from environment variables
        api_id = os.getenv('TELEGRAM_API_ID')
        api_hash = os.getenv('TELEGRAM_API_HASH')
        
        if not api_id or not api_hash:
            raise ValueError("TELEGRAM_API_ID and TELEGRAM_API_HASH must be set in environment variables")
        
        # Pyrogram client configuration
        self.app = Client(
            "youtube_downloader_bot",
            bot_token=bot_token,
            api_id=api_id,
            api_hash=api_hash
        )
        
        # Validate cookies file
        self.cookies_file = None
        if cookies_file:
            if os.path.exists(cookies_file):
                self.cookies_file = cookies_file
            else:
                logging.warning(f"Cookie file {cookies_file} not found")
        
        # Configure logging
        logging.basicConfig(
            level=logging.INFO, 
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)

    def validate_youtube_url(self, url: str) -> bool:
        """
        Validate that the URL is a proper YouTube URL
        
        :param url: URL to validate
        :return: True if valid, False otherwise
        """
        # YouTube URL patterns
        patterns = [
            r'^(https?\:\/\/)?(www\.)?(youtube\.com|youtu\.?be)\/.+$',
            r'^(https?\:\/\/)?(www\.)?youtube\.com\/watch\?v=[\w-]+(\&.+)?$',
            r'^(https?\:\/\/)?(www\.)?youtu\.be\/[\w-]+(\?.+)?$'
        ]
        
        for pattern in patterns:
            if re.match(pattern, url):
                return True
        return False

    def get_video_qualities(self, url: str) -> VideoInfo:
        """
        Fetch available video and audio qualities
        
        :param url: YouTube video URL
        :return: VideoInfo with available formats and metadata
        :raises ValueError: If URL is invalid
        :raises RuntimeError: If extraction fails
        """
        # Validate URL
        if not self.validate_youtube_url(url):
            raise ValueError(f"Invalid YouTube URL: {url}")
        
        # Prepare download options to list formats
        ydl_opts = {
            'listformats': True,
            'quiet': True,
        }
        
        # Add cookie file if specified
        if self.cookies_file:
            ydl_opts['cookiefile'] = self.cookies_file
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                # Organize video formats
                video_formats: Dict[str, str] = {}
                audio_formats: Dict[str, str] = {}
                
                for format in info.get('formats', []):
                    # Video formats
                    if format.get('vcodec') != 'none':
                        resolution = format.get('height', 0)
                        fps = format.get('fps', 0)
                        format_id = format.get('format_id', '')
                        ext = format.get('ext', '')
                        file_size = format.get('filesize', 0)
                        
                        # Convert file size to MB
                        size_mb = file_size / (1024 * 1024) if file_size else 0
                        
                        video_formats[format_id] = f"{resolution}p @ {fps}fps ({ext}, {size_mb:.2f} MB)"
                    
                    # Audio formats
                    if format.get('acodec') != 'none' and format.get('vcodec') == 'none':
                        format_id = format.get('format_id', '')
                        audio_bitrate = format.get('abr', 0)
                        ext = format.get('ext', '')
                        
                        audio_formats[format_id] = f"{audio_bitrate} kbps ({ext})"
                
                return {
                    'video_formats': video_formats,
                    'audio_formats': audio_formats,
                    'title': info.get('title', 'Unknown Title'),
                    'duration': info.get('duration', 0),
                    'thumbnail': info.get('thumbnail')
                }
            
        except yt_dlp.utils.DownloadError as e:
            self.logger.error(f"Download error: {e}")
            raise RuntimeError(f"Failed to extract video info: {e}")
        except Exception as e:
            self.logger.error(f"Error fetching video qualities: {e}")
            raise RuntimeError(f"Unexpected error: {e}")

    def convert_thumbnail(self, input_thumbnail: str) -> Optional[str]:
        """
        Convert thumbnail to a Telegram-supported format (PNG)
        
        :param input_thumbnail: Path to the input thumbnail
        :return: Path to the converted thumbnail or None
        """
        if not input_thumbnail or not os.path.exists(input_thumbnail):
            return None
        
        # Generate output path
        output_thumbnail = input_thumbnail.rsplit('.', 1)[0] + '.png'
        
        try:
            # Try PIL first
            try:
                from PIL import Image
                img = Image.open(input_thumbnail)
                img.save(output_thumbnail, 'PNG')
                self.logger.info(f"Converted thumbnail using PIL")
                return output_thumbnail
            except ImportError:
                self.logger.info("PIL not available, trying FFmpeg")
            
            # Check if FFmpeg is available
            try:
                # Check if FFmpeg is installed
                subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
                
                # Use FFmpeg to convert
                subprocess.run([
                    'ffmpeg', 
                    '-i', input_thumbnail, 
                    '-vf', 'scale=trunc(iw/2)*2:trunc(ih/2)*2', 
                    output_thumbnail
                ], capture_output=True, check=True)
                
                self.logger.info(f"Converted thumbnail using FFmpeg")
                return output_thumbnail
            except (subprocess.SubprocessError, FileNotFoundError):
                self.logger.warning("FFmpeg not available or failed")
                return None
                
        except Exception as e:
            self.logger.error(f"Thumbnail conversion failed: {e}")
            return None

    def download_video(self, url: str, video_format: str, audio_format: Optional[str] = None) -> DownloadResult:
        """
        Download YouTube video with specified formats
        
        :param url: YouTube video URL
        :param video_format: Selected video format ID
        :param audio_format: Optional audio format ID for separate audio
        :return: DownloadResult with paths and metadata
        :raises ValueError: If URL or format IDs are invalid
        :raises RuntimeError: If download fails
        """
        # Validate URL
        if not self.validate_youtube_url(url):
            raise ValueError(f"Invalid YouTube URL: {url}")
        
        # Validate format IDs
        if not video_format:
            raise ValueError("Video format ID cannot be empty")
        
        # Prepare download options
        ydl_opts = {
            'format': video_format,
            'outtmpl': '%(title)s.%(ext)s',
            'writesubtitles': False,
            'writedescription': False,
            'writeinfojson': True,
            'writethumbnail': True,
            'no_warnings': False,
        }
        
        # Add cookie file if specified
        if self.cookies_file:
            ydl_opts['cookiefile'] = self.cookies_file
        
        # Add audio format if specified
        if audio_format:
            ydl_opts['format'] = f'{video_format}+{audio_format}'
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                self.logger.info(f"Downloading video with format: {ydl_opts['format']}")
                info_dict = ydl.extract_info(url, download=True)
                
                # Find downloaded files
                video_filename = ydl.prepare_filename(info_dict)
                
                # Confirm file exists
                if not os.path.exists(video_filename):
                    possible_extensions = ['mp4', 'mkv', 'webm']
                    for ext in possible_extensions:
                        alt_filename = video_filename.rsplit('.', 1)[0] + f'.{ext}'
                        if os.path.exists(alt_filename):
                            video_filename = alt_filename
                            break
                
                if not os.path.exists(video_filename):
                    raise FileNotFoundError(f"Downloaded video file not found: {video_filename}")
                
                # Find thumbnail
                thumbnail_candidates = [
                    video_filename.rsplit('.', 1)[0] + '.webp',
                    video_filename.rsplit('.', 1)[0] + '.jpg',
                    video_filename.rsplit('.', 1)[0] + '.png'
                ]
                
                thumbnail_path = next((path for path in thumbnail_candidates if os.path.exists(path)), None)
                
                # Convert thumbnail to PNG if needed
                converted_thumbnail = self.convert_thumbnail(thumbnail_path) if thumbnail_path else None
                
                # Get video title (without extension)
                video_title = info_dict.get('title', os.path.splitext(os.path.basename(video_filename))[0])
                
                # Get video duration
                duration = info_dict.get('duration', 0)
                
                return DownloadResult(
                    video_path=video_filename,
                    thumbnail_path=converted_thumbnail or thumbnail_path,
                    video_title=video_title,
                    duration=duration
                )
        
        except yt_dlp.utils.DownloadError as e:
            self.logger.error(f"Download error: {e}")
            raise RuntimeError(f"Failed to download video: {e}")
        except FileNotFoundError as e:
            self.logger.error(f"File not found: {e}")
            raise RuntimeError(f"File not found: {e}")
        except Exception as e:
            self.logger.error(f"Download failed: {e}")
            raise RuntimeError(f"Unexpected error during download: {e}")

    def upload_to_telegram(self, download_result: DownloadResult) -> bool:
        """
        Upload video to Telegram channel
        
        :param download_result: DownloadResult with video information
        :return: True if successful, False otherwise
        :raises RuntimeError: If upload fails
        """
        video_path = download_result.video_path
        thumbnail_path = download_result.thumbnail_path
        title = download_result.video_title
        duration = download_result.duration
        
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")
        
        try:
            with self.app:
                # Upload video with thumbnail, caption, and duration
                if thumbnail_path and os.path.exists(thumbnail_path):
                    self.logger.info(f"Uploading video with thumbnail to {self.channel_id}")
                    self.app.send_video(
                        chat_id=self.channel_id,
                        video=video_path,
                        caption=title,
                        thumb=thumbnail_path,
                        duration=duration
                    )
                else:
                    self.logger.info(f"Uploading video without thumbnail to {self.channel_id}")
                    self.app.send_video(
                        chat_id=self.channel_id,
                        video=video_path,
                        caption=title,
                        duration=duration
                    )
                
                self.logger.info(f"Successfully uploaded {video_path} to Telegram")
                return True
        
        except Exception as e:
            self.logger.error(f"Upload failed: {e}")
            raise RuntimeError(f"Failed to upload to Telegram: {e}")

    def cleanup(self, download_result: DownloadResult) -> None:
        """
        Clean up downloaded files
        
        :param download_result: DownloadResult with file paths
        """
        files_to_clean = [
            download_result.video_path,
            download_result.thumbnail_path,
            # Also clean up JSON info file
            download_result.video_path.rsplit('.', 1)[0] + '.info.json'
        ]
        
        for file_path in files_to_clean:
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    self.logger.info(f"Cleaned up file: {file_path}")
                except Exception as e:
                    self.logger.error(f"Cleanup failed for {file_path}: {e}")


def validate_format_selection(available_formats, selected_format):
    """
    Validate that the selected format is available
    
    :param available_formats: Dictionary of available formats
    :param selected_format: Format ID selected by user
    :return: True if valid, False otherwise
    """
    return selected_format in available_formats


def get_env_setup_instructions():
    """
    Return instructions for setting up environment variables
    """
    return """
Create a .env file in the same directory as this script with the following content:

TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_BOT_TOKEN=your_bot_token

Replace the values with your actual Telegram API credentials.
You can obtain them from https://my.telegram.org/apps
"""


def main():
    """
    Main function to orchestrate the download and upload process
    """
    print("YouTube to Telegram Downloader")
    print("==============================")
    
    # Check for environment variables
    if not os.getenv('TELEGRAM_API_ID') or not os.getenv('TELEGRAM_API_HASH'):
        print("ERROR: Required environment variables not set.")
        print(get_env_setup_instructions())
        return
    
    # Get YouTube video URL from user
    url = input("Enter YouTube video URL: ").strip()
    
    # Get bot token - try from env var first, then prompt
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not bot_token:
        bot_token = input("Enter your Telegram bot token: ").strip()
        if not bot_token:
            print("ERROR: Bot token is required")
            return
    
    # Get channel ID
    channel_id_input = input("Enter Telegram channel ID (e.g., -1001234567890): ").strip()
    if not channel_id_input:
        print("ERROR: Channel ID is required")
        return
    
    # Parse channel_id to ensure it's valid
    try:
        # Try to convert to int (for channels like -1001234567890)
        channel_id = int(channel_id_input)
    except ValueError:
        # If not an integer, use as string (for channels like @channelname)
        channel_id = channel_id_input
    
    # Prompt for cookie file (optional)
    cookies_file = input("Enter path to Netscape cookies file (optional, press Enter to skip): ").strip()
    
    try:
        # Initialize downloader
        downloader = YouTubeTelegramDownloader(bot_token, channel_id, cookies_file)
        
        # Validate URL
        if not downloader.validate_youtube_url(url):
            print("ERROR: Invalid YouTube URL")
            return
        
        # Get available formats
        print("Fetching available video and audio formats...")
        try:
            formats = downloader.get_video_qualities(url)
        except Exception as e:
            print(f"ERROR: Failed to fetch video formats: {e}")
            return
        
        # Display video formats
        print("\nAvailable Video Formats:")
        if not formats['video_formats']:
            print("No video formats found")
            return
            
        for format_id, details in formats['video_formats'].items():
            print(f"Format ID: {format_id} - {details}")
        
        # Display audio formats
        print("\nAvailable Audio Formats:")
        if formats['audio_formats']:
            for format_id, bitrate in formats['audio_formats'].items():
                print(f"Format ID: {format_id} - {bitrate}")
        else:
            print("No separate audio formats found")
        
        # User selection with validation
        while True:
            video_format = input("\nEnter desired video format ID: ").strip()
            if not video_format:
                print("ERROR: Video format ID is required")
                continue
            
            if not validate_format_selection(formats['video_formats'], video_format):
                print("ERROR: Invalid video format ID, please select from the list")
                continue
            break
        
        # Optional audio format
        audio_format = None
        if formats['audio_formats']:
            audio_input = input("Enter desired audio format ID (optional, press Enter to skip): ").strip()
            if audio_input and validate_format_selection(formats['audio_formats'], audio_input):
                audio_format = audio_input
            elif audio_input:
                print("Warning: Invalid audio format ID, proceeding without separate audio")
        
        try:
            # Download video
            print(f"\nDownloading video with format ID: {video_format}")
            if audio_format:
                print(f"and audio format ID: {audio_format}")
                
            download_result = downloader.download_video(url, video_format, audio_format)
            
            print(f"\nDownload complete: {download_result.video_path}")
            print(f"Video title: {download_result.video_title}")
            print(f"Duration: {download_result.duration} seconds")
            
            # Upload to Telegram
            print("\nUploading to Telegram channel...")
            downloader.upload_to_telegram(download_result)
            
            print("Upload successful!")
            
            # Clean up
            print("\nCleaning up downloaded files...")
            downloader.cleanup(download_result)
            
            print("Process completed successfully!")
        
        except FileNotFoundError as e:
            print(f"ERROR: File not found: {e}")
        except ValueError as e:
            print(f"ERROR: {e}")
        except RuntimeError as e:
            print(f"ERROR: {e}")
        except Exception as e:
            print(f"ERROR: An unexpected error occurred: {e}")
    
    except Exception as e:
        print(f"ERROR: {e}")


if __name__ == '__main__':
    main()
