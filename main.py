import os
from typing import Dict
from dotenv import load_dotenv

from src.core.downloader import YouTubeTelegramDownloader
from src.telegram.uploader import TelegramUploader
from src.utils.validators import validate_youtube_url, validate_format_selection
from src.utils.helpers import get_env_setup_instructions, cleanup, convert_thumbnail
from src.models import VideoInfo, DownloadResult


# Load environment variables from .env file
load_dotenv()

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
    
    download_result = None # Initialize download_result
    try:
        downloader = YouTubeTelegramDownloader(cookies_file)
        uploader = TelegramUploader(bot_token, channel_id)

        if not validate_youtube_url(url):
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
            container_choice = input(f"Select container format [1-{len(valid_containers)}]: ").strip()
            if not container_choice:
                break
            
            try:
                idx = int(container_choice) - 1
                if 0 <= idx < len(valid_containers):
                    container_format = valid_containers[idx]
                    break
                else:
                    print(f"Please enter a number between 1 and {len(valid_containers)}: ")
            except ValueError:
                print("Please enter a valid number: ")
        
        print(f"Using container format: {container_format}")
        
        # Download and upload
        print("\nDownloading video...")
        try:
            download_result = downloader.download_video(url, video_format, audio_format, container_format)
            print(f"Downloaded: {download_result.video_title} ({download_result.duration}s)")

            # Convert thumbnail after download
            if download_result.thumbnail_path:
                download_result.thumbnail_path = convert_thumbnail(download_result.thumbnail_path)
            
            print("Uploading to Telegram...")
            uploader.upload_to_telegram(download_result)
            print("Upload successful!")
            
        except Exception as e:
            print(f"ERROR: {e}")
    finally:
        if download_result:
            print("Cleaning up...")
            cleanup(download_result)
            print("Done!")


if __name__ == '__main__':
    main()