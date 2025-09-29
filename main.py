import os
from typing import Dict, List

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
    
    download_result = None  # Initialize download_result for single video
    try:
        downloader = YouTubeTelegramDownloader(cookies_file)
        uploader = TelegramUploader(bot_token, channel_id)

        if not validate_youtube_url(url):
            print("ERROR: Invalid YouTube URL")
            return

        is_playlist_url = downloader.is_playlist(url)
        
        formats = None
        if is_playlist_url:
            print("Detected YouTube playlist. Extracting videos...")
            print("Extracting playlist entries... This may take a moment for large playlists.")
            try:
                playlist_entries = downloader.get_playlist_entries(url)
                print(f"\nPlaylist contains {len(playlist_entries)} videos:")
                for i, entry in enumerate(playlist_entries, 1):
                    print(f"{i}. {entry['title']}")
                
                # Select videos
                while True:
                    selection_input = input("\nSelect videos (e.g., 'all', '1', '1,3-5'): ").strip().lower()
                    if not selection_input:
                        print("Please enter a selection.")
                        continue
                    
                    if selection_input == 'all':
                        selected_indices = list(range(len(playlist_entries)))
                        break
                    else:
                        try:
                            selected_indices = []
                            parts = selection_input.split(',')
                            for part in parts:
                                part = part.strip()
                                if '-' in part:
                                    start, end = map(int, part.split('-'))
                                    selected_indices.extend(range(start-1, end))
                                else:
                                    selected_indices.append(int(part)-1)
                            # Remove duplicates and sort
                            selected_indices = sorted(set(selected_indices))
                            if all(0 <= idx < len(playlist_entries) for idx in selected_indices):
                                break
                            else:
                                print("Invalid indices. Please try again.")
                        except ValueError:
                            print("Invalid input. Please use 'all' or comma-separated indices/ranges.")
                
                selected_entries = [playlist_entries[i] for i in selected_indices]
                print(f"Selected {len(selected_entries)} videos.")
                
                # Prompt for max file size
                max_size_input = input("Enter max file size in MB (default 2048, press Enter): ").strip()
                max_size_mb = 2048 if not max_size_input else float(max_size_input)
                
                # Fetch formats from first selected video
                first_video_url = selected_entries[0]['url']
                print("Fetching Available Formats from first video... This may take a moment.")
                formats = downloader.get_video_qualities(first_video_url)
                
            except Exception as e:
                print(f"ERROR: Failed to process playlist: {e}")
                return
        else:
            selected_entries = None
            max_size_mb = 2048  # Default for single, but with warning
        
        # Common format selection (for both single and playlist)
        print("\nAvailable Video Formats:")
        video_options = list(formats['video_formats'].items())
        for i, (fmt_id, details) in enumerate(video_options, 1):
            print(f"{i}. {fmt_id}: {details}")
        
        # Get video format first
        while True:
            try:
                video_choice = input(f"\nEnter video format (1-{len(video_options)}): ").strip()
                if not video_choice:
                    print("Please enter a number.")
                    continue
                idx = int(video_choice) - 1
                if 0 <= idx < len(video_options):
                    video_format = video_options[idx][0]
                    print(f"Selected: {video_format}")
                    break
                else:
                    print(f"Please enter a number between 1 and {len(video_options)}")
            except ValueError:
                print("Please enter a valid number.")
        
        # Now print and get optional audio format
        audio_format = None
        if formats['audio_formats']:
            print("\nAvailable Audio Formats:")
            audio_options = list(formats['audio_formats'].items())
            for i, (fmt_id, details) in enumerate(audio_options, 1):
                print(f"{i}. {fmt_id}: {details}")
            while True:
                try:
                    audio_choice = input(f"Enter audio format ID (1-{len(audio_options)}) or press Enter to skip: ").strip()
                    if not audio_choice:
                        break
                    idx = int(audio_choice) - 1
                    if 0 <= idx < len(audio_options):
                        audio_format = audio_options[idx][0]
                        print(f"Selected audio: {audio_format}")
                        break
                    else:
                        print(f"Please enter a number between 1 and {len(audio_options)} or Enter to skip")
                except ValueError:
                    if audio_choice:
                        print("Please enter a valid number or Enter to skip.")
        else:
            print("\nNo separate audio formats found.")
        
        # Container format selection
        valid_containers = ['mp4', 'mkv', 'webm']
        print("\nAvailable container formats:")
        for i, container in enumerate(valid_containers, 1):
            print(f"{i}. {container}")
        
        container_format = 'mp4'
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
        
        # For single video, check estimated size and warn
        if not is_playlist_url:
            print("\nEstimating download size...")
            estimated_size = downloader.get_estimated_size(url, video_format, audio_format, container_format)
            if estimated_size > 2048:
                confirm = input(f"Estimated size {estimated_size:.1f} MB > 2048 MB limit. Proceed anyway? (y/n, default y): ").strip().lower()
                if confirm == 'n':
                    print("Aborted by user.")
                    return
            else:
                print(f"Estimated size: {estimated_size:.1f} MB")
        
        # Process videos
        if is_playlist_url:
            successful_uploads = 0
            for idx, entry in enumerate(selected_entries, 1):
                entry_url = entry['url']
                entry_title = entry['title']
                print(f"\nProcessing {idx}/{len(selected_entries)}: {entry_title}")
                
                # Estimate size
                estimated_size = downloader.get_estimated_size(entry_url, video_format, audio_format, container_format)
                if estimated_size > max_size_mb:
                    print(f"Skipped {entry_title}: estimated {estimated_size:.1f} MB > {max_size_mb} MB limit")
                    continue
                
                print(f"Estimated size: {estimated_size:.1f} MB")
                
                local_download_result = None
                try:
                    local_download_result = downloader.download_video(entry_url, video_format, audio_format, container_format)
                    print(f"Downloaded: {local_download_result.video_title} ({local_download_result.duration}s)")

                    if local_download_result.thumbnail_path:
                        local_download_result.thumbnail_path = convert_thumbnail(local_download_result.thumbnail_path)
                    
                    print("Uploading to Telegram...")
                    uploader.upload_to_telegram(local_download_result)
                    print("Upload successful!")
                    successful_uploads += 1
                    
                except Exception as e:
                    print(f"ERROR processing {entry_title}: {e}")
                finally:
                    if local_download_result:
                        print("Cleaning up...")
                        cleanup(local_download_result)
            
            print(f"\nPlaylist processing complete. {successful_uploads}/{len(selected_entries)} videos uploaded successfully.")
        else:
            # Single video processing
            print("\nDownloading video...")
            try:
                download_result = downloader.download_video(url, video_format, audio_format, container_format)
                print(f"Downloaded: {download_result.video_title} ({download_result.duration}s)")

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