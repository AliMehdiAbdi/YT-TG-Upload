import os
import logging
from typing import Optional, Dict, Any, TypedDict, List, Union
import subprocess
import re
from dataclasses import dataclass
import yt_dlp
from pyrogram import Client
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
    video_formats: Dict[str, str]
    audio_formats: Dict[str, str]
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
        :param channel_id: Telegram channel ID (can be string username or integer ID)
        :param cookies_file: Optional path to Netscape-format cookie file
        """
        # Validate inputs
        if not bot_token or not isinstance(bot_token, str):
            raise ValueError("Bot token must be a non-empty string")
        
        # Store channel ID as provided (string or integer)
        self.channel_id = channel_id
        
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
        if cookies_file and os.path.exists(cookies_file):
            self.cookies_file = cookies_file
        elif cookies_file:
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
        patterns = [
            r'^(https?\:\/\/)?(www\.)?(youtube\.com|youtu\.?be)\/.+$',
            r'^(https?\:\/\/)?(www\.)?youtube\.com\/watch\?v=[\w-]+',
            r'^(https?\:\/\/)?(www\.)?youtu\.be\/[\w-]+'
        ]
        
        return any(re.match(pattern, url) for pattern in patterns)

    def get_video_qualities(self, url: str) -> VideoInfo:
        """
        Fetch available video and audio qualities
        
        :param url: YouTube video URL
        :return: VideoInfo with available formats and metadata
        :raises ValueError: If URL is invalid
        :raises RuntimeError: If extraction fails
        """
        if not self.validate_youtube_url(url):
            raise ValueError(f"Invalid YouTube URL: {url}")
        
        ydl_opts = {
            'listformats': True,
            'quiet': True,
        }
        
        if self.cookies_file:
            ydl_opts['cookiefile'] = self.cookies_file
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                video_formats = {}
                audio_formats = {}
                
                for fmt in info.get('formats', []):
                    if fmt.get('vcodec') != 'none':
                        resolution = fmt.get('height', 0)
                        fps = fmt.get('fps', 0)
                        size_mb = fmt.get('filesize', 0) / (1024 * 1024) if fmt.get('filesize') else 0
                        video_formats[fmt['format_id']] = (
                            f"{resolution}p{f'@{fps}fps' if fps else ''} "
                            f"({fmt['ext']}, {size_mb:.1f}MB)"
                        )
                    
                    if fmt.get('acodec') != 'none' and fmt.get('vcodec') == 'none':
                        audio_formats[fmt['format_id']] = (
                            f"{fmt.get('abr', 0)}kbps ({fmt['ext']})"
                        )
                
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
                self.logger.info("PIL not available, trying FFmpeg")
            
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
            self.logger.error(f"Thumbnail conversion failed: {e}")
            return None

    def download_video(self, url: str, video_format: str, audio_format: Optional[str] = None, container_format: str = 'mp4') -> DownloadResult:
        """
        Download YouTube video with specified formats and container
        
        :param url: YouTube video URL
        :param video_format: Video format ID
        :param audio_format: Optional audio format ID
        :param container_format: Container format (mp4, mkv, webm)
        :return: DownloadResult with path and metadata
        """
        if not self.validate_youtube_url(url):
            raise ValueError(f"Invalid YouTube URL: {url}")
        
        if not video_format:
            raise ValueError("Video format ID cannot be empty")
        
        # Validate container format
        valid_containers = ['mp4', 'mkv', 'webm']
        if container_format not in valid_containers:
            self.logger.warning(f"Invalid container format: {container_format}. Using mp4 instead.")
            container_format = 'mp4'
        
        ydl_opts = {
            'format': f'{video_format}+{audio_format}' if audio_format else video_format,
            'outtmpl': '%(title)s.%(ext)s',
            'writethumbnail': True,
            'no_warnings': False,
            'merge_output_format': container_format,  # Specify the container format
        }
        
        if self.cookies_file:
            ydl_opts['cookiefile'] = self.cookies_file
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(url, download=True)
                video_filename = ydl.prepare_filename(info_dict)
                
                # Update extension to match the selected container format
                base_filename = video_filename.rsplit('.', 1)[0]
                video_filename = f"{base_filename}.{container_format}"
                
                if not os.path.exists(video_filename):
                    raise FileNotFoundError(f"Downloaded video file not found: {video_filename}")
                
                # Find thumbnail
                base_name = base_filename
                thumbnail_path = next(
                    (f"{base_name}.{ext}" for ext in ['webp', 'jpg', 'png'] 
                    if os.path.exists(f"{base_name}.{ext}")
                ), None)
                
                converted_thumbnail = self.convert_thumbnail(thumbnail_path) if thumbnail_path else None
                
                return DownloadResult(
                    video_path=video_filename,
                    thumbnail_path=converted_thumbnail or thumbnail_path,
                    video_title=info_dict.get('title', os.path.splitext(os.path.basename(video_filename))[0]),
                    duration=info_dict.get('duration', 0)
                )
        
        except Exception as e:
            self.logger.error(f"Download failed: {e}")
            raise RuntimeError(f"Failed to download video: {e}")

    def upload_to_telegram(self, download_result: DownloadResult) -> bool:
        """
        Upload video to Telegram channel
        """
        if not os.path.exists(download_result.video_path):
            raise FileNotFoundError(f"Video file not found: {download_result.video_path}")
        
        try:
            with self.app:
                kwargs = {
                    'chat_id': self.channel_id,
                    'video': download_result.video_path,
                    'caption': download_result.video_title,
                    'duration': download_result.duration
                }
                
                if download_result.thumbnail_path and os.path.exists(download_result.thumbnail_path):
                    kwargs['thumb'] = download_result.thumbnail_path
                
                self.app.send_video(**kwargs)
                return True
        
        except Exception as e:
            self.logger.error(f"Upload failed: {e}")
            raise RuntimeError(f"Failed to upload to Telegram: {e}")

    def cleanup(self, download_result: DownloadResult) -> None:
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
                        self.logger.error(f"Failed to remove {file_path}: {e}")
        except Exception as e:
            self.logger.error(f"Cleanup error: {e}")


def validate_format_selection(available_formats: Dict[str, str], selected_format: str) -> bool:
    """
    Validate that the selected format is available
    """
    return selected_format in available_formats


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


def main() -> None:
    """
    Main function to orchestrate the download and upload process
    """
    print("YT-TG-Upload")
    print("=============================")
    
    # Check for required environment variables
    required_vars = ['TELEGRAM_API_ID', 'TELEGRAM_API_HASH', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHANNEL_ID']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        print("ERROR: Missing required environment variables:")
        for var in missing_vars:
            print(f"- {var}")
        print(get_env_setup_instructions())
        return
    
    # Get YouTube video URL
    url = input("Enter YouTube video URL: ").strip()
    if not url:
        print("ERROR: URL cannot be empty")
        return
    
    # Get credentials from environment
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    channel_id = int(os.getenv('TELEGRAM_CHANNEL_ID'))
    
    # Optional cookies file
    cookies_file = input("Enter path to cookies file (optional, press Enter to skip): ").strip()
    if cookies_file and not os.path.exists(cookies_file):
        print(f"Warning: Cookie file {cookies_file} not found")
        cookies_file = None
    
    try:
        downloader = YouTubeTelegramDownloader(bot_token, channel_id, cookies_file)
        
        if not downloader.validate_youtube_url(url):
            print("ERROR: Invalid YouTube URL")
            return
        
        print("Fetching Available Formats...")
        try:
            formats = downloader.get_video_qualities(url)
        except Exception as e:
            print(f"ERROR: Failed to fetch formats: {e}")
            return
        
        print("\nAvailable Video Formats:")
        for fmt_id, details in formats['video_formats'].items():
            print(f"{fmt_id}: {details}")
        
        print("\nAvailable Audio Formats:" if formats['audio_formats'] else "\nNo separate audio formats found")
        for fmt_id, details in formats['audio_formats'].items():
            print(f"{fmt_id}: {details}")
        
        # Get video format
        while True:
            video_format = input("\nEnter video format ID: ").strip()
            if validate_format_selection(formats['video_formats'], video_format):
                break
            print("Invalid format ID, please try again")
        
        # Get optional audio format
        audio_format = None
        if formats['audio_formats']:
            audio_format = input("Enter audio format ID (optional, press Enter to skip): ").strip()
            if audio_format and not validate_format_selection(formats['audio_formats'], audio_format):
                print("Warning: Invalid audio format, proceeding without separate audio")
                audio_format = None
        
        # Container format selection
        valid_containers = ['mp4', 'mkv', 'webm']
        print("\nAvailable container formats:")
        for i, container in enumerate(valid_containers, 1):
            print(f"{i}. {container}")
        
        container_format = 'mp4'  # Default
        while True:
            container_choice = input(f"Select container format [1-{len(valid_containers)}]").strip()
            if not container_choice:
                break
            
            try:
                idx = int(container_choice) - 1
                if 0 <= idx < len(valid_containers):
                    container_format = valid_containers[idx]
                    break
                else:
                    print(f"Please enter a number between 1 and {len(valid_containers)}")
            except ValueError:
                print("Please enter a valid number")
        
        print(f"Using container format: {container_format}")
        
        # Download and upload
        print("\nDownloading video...")
        try:
            result = downloader.download_video(url, video_format, audio_format, container_format)
            print(f"Downloaded: {result.video_title} ({result.duration}s)")
            
            print("Uploading to Telegram...")
            downloader.upload_to_telegram(result)
            print("Upload successful!")
            
            print("Cleaning up...")
            downloader.cleanup(result)
            print("Done!")
            
        except Exception as e:
            print(f"ERROR: {e}")
    
    except Exception as e:
        print(f"ERROR: {e}")


if __name__ == '__main__':
    main()