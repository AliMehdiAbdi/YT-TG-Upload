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
        video_options = list(formats['video_formats'].items())
        for i, (fmt_id, details) in enumerate(video_options, 1):
            print(f"{i}. {fmt_id}: {details}")
        
        print("\nAvailable Audio Formats:" if formats['audio_formats'] else "\nNo separate audio formats found")
        
        # Get video format
        while True:
            try:
                video_choice = input(f"\nEnter video format (1-{len(video_options)}): ").strip()
                if not video_choice:
                    print("Please enter a number.")
                    continue
                idx = int(video_choice) - 1
                if 0 <= idx < len(video_options):
                    video_format = video_options[idx][0]  # Get the fmt_id
                    print(f"Selected: {video_format}")
                    break
                else:
                    print(f"Please enter a number between 1 and {len(video_options)}")
            except ValueError:
                print("Please enter a valid number.")
        
        # Get optional audio format
        audio_format = None
        if formats['audio_formats']:
            audio_options = list(formats['audio_formats'].items())
            for i, (fmt_id, details) in enumerate(audio_options, 1):
                print(f"{i}. {fmt_id}: {details}")
            while True:
                try:
                    audio_choice = input(f"Enter audio format ID (1-{len(audio_options)}) or press Enter to skip: ").strip()
                    if not audio_choice:
                        break  # Skip audio
                    idx = int(audio_choice) - 1
                    if 0 <= idx < len(audio_options):
                        audio_format = audio_options[idx][0]  # Get the fmt_id
                        print(f"Selected audio: {audio_format}")
                        break
                    else:
                        print(f"Please enter a number between 1 and {len(audio_options)} or Enter to skip")
                except ValueError:
                    if audio_choice:  # Only warn if they entered something
                        print("Please enter a valid number or Enter to skip.")
        
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