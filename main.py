import os
import logging
from typing import Dict, List, Callable, Optional

from dotenv import load_dotenv
from tqdm import tqdm

from src.core.downloader import YouTubeTelegramDownloader
from src.telegram.uploader import TelegramUploader
from src.utils.validators import validate_youtube_url, validate_format_selection
from src.utils.helpers import get_env_setup_instructions, cleanup, convert_thumbnail, format_size
from src.models import VideoInfo, DownloadResult


# Load environment variables from .env file
load_dotenv()

# Configure logging once at the top level
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


def make_download_hook(pbar: tqdm):
    """
    Create a yt-dlp progress hook that feeds a tqdm progress bar.
    Handles multi-stream downloads (video + audio downloaded separately).
    """
    def hook(d):
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded = d.get('downloaded_bytes', 0)
            
            # Detect new stream starting (downloaded bytes dropped below current position)
            if downloaded < pbar.n:
                pbar.reset()
                pbar.set_description('  ↓ Audio      ')
            
            if total and pbar.total != total:
                pbar.total = total
                pbar.refresh()
            pbar.update(downloaded - pbar.n)
        elif d['status'] == 'finished':
            if pbar.total and pbar.n < pbar.total:
                pbar.update(pbar.total - pbar.n)
    return hook


def make_upload_progress(pbar: tqdm):
    """
    Create a Pyrogram upload progress callback that feeds a tqdm progress bar.
    """
    def callback(current, total):
        if pbar.total != total:
            pbar.total = total
            pbar.refresh()
        pbar.update(current - pbar.n)
    return callback


def display_video_formats(formats: VideoInfo) -> tuple:
    """
    Display available formats in a clean, grouped table and handle user selection.
    Returns (video_format_id, audio_format_id) where audio may be None.
    """
    video_formats = formats['video_formats']
    audio_formats = formats['audio_formats']
    
    # --- Video format table ---
    print("\n  Available Video Formats:")
    print(f"  {'#':>3}   {'Quality':<14} {'Codec':<7} {'Ext':<5} {'Size':<10}")
    print(f"  {'─'*3}   {'─'*14} {'─'*7} {'─'*5} {'─'*10}")
    
    for i, vf in enumerate(video_formats, 1):
        quality = f"{vf['resolution']}p"
        if vf['fps'] and vf['fps'] > 0:
            quality += f"@{vf['fps']}fps"
        size_str = format_size(vf['size_mb'])
        marker = "  ★ Recommended" if i == 1 else ""
        print(f"  {i:>3}.  {quality:<14} {vf['vcodec']:<7} {vf['ext']:<5} {size_str:<10}{marker}")
    
    # Video selection (Enter = recommended)
    while True:
        try:
            video_choice = input(f"\n  Select video format [1-{len(video_formats)}] (Enter = recommended): ").strip()
            if not video_choice:
                idx = 0  # Recommended = first
            else:
                idx = int(video_choice) - 1
            if 0 <= idx < len(video_formats):
                selected_video = video_formats[idx]
                quality = f"{selected_video['resolution']}p"
                if selected_video['fps']:
                    quality += f"@{selected_video['fps']}fps"
                print(f"  ✓ Video: {quality} ({selected_video['vcodec']}, {format_size(selected_video['size_mb'])})")
                break
            else:
                print(f"  Please enter a number between 1 and {len(video_formats)}")
        except ValueError:
            print("  Please enter a valid number.")
    
    # --- Audio format table ---
    selected_audio = None
    if audio_formats:
        print(f"\n  Available Audio Formats:")
        print(f"  {'#':>3}   {'Bitrate':<12} {'Codec':<7} {'Ext':<5}")
        print(f"  {'─'*3}   {'─'*12} {'─'*7} {'─'*5}")
        
        for i, af in enumerate(audio_formats, 1):
            bitrate_str = f"{af['bitrate']:.0f} kbps"
            marker = "  ★ Recommended" if i == 1 else ""
            print(f"  {i:>3}.  {bitrate_str:<12} {af['acodec']:<7} {af['ext']:<5}{marker}")
        
        while True:
            try:
                audio_choice = input(f"\n  Select audio format [1-{len(audio_formats)}] (Enter = recommended): ").strip()
                if not audio_choice:
                    idx = 0  # Recommended = first (highest bitrate)
                else:
                    idx = int(audio_choice) - 1
                if 0 <= idx < len(audio_formats):
                    selected_audio = audio_formats[idx]
                    print(f"  ✓ Audio: {selected_audio['bitrate']:.0f} kbps ({selected_audio['acodec']})")
                    break
                else:
                    print(f"  Please enter a number between 1 and {len(audio_formats)}")
            except ValueError:
                print("  Please enter a valid number.")
    else:
        print("\n  No separate audio formats found (audio may be included in video stream).")
    
    video_format_id = selected_video['format_id']
    audio_format_id = selected_audio['format_id'] if selected_audio else None
    return video_format_id, audio_format_id


def download_with_progress(downloader, url, video_format, audio_format, container_format):
    """
    Download a video with a tqdm progress bar.
    Returns DownloadResult.
    """
    with tqdm(unit='B', unit_scale=True, unit_divisor=1024,
              desc='  ↓ Video      ', miniters=1,
              bar_format='{desc}: {percentage:3.0f}%|{bar:30}| {n_fmt}/{total_fmt} [{rate_fmt}, ETA {remaining}]') as pbar:
        result = downloader.download_video(
            url, video_format, audio_format, container_format,
            progress_hook=make_download_hook(pbar)
        )
    return result


def upload_with_progress(uploader, download_result):
    """
    Upload a video to Telegram with a tqdm progress bar.
    """
    with tqdm(unit='B', unit_scale=True, unit_divisor=1024,
              desc='  ↑ Uploading  ', miniters=1,
              bar_format='{desc}: {percentage:3.0f}%|{bar:30}| {n_fmt}/{total_fmt} [{rate_fmt}, ETA {remaining}]') as pbar:
        uploader.upload_to_telegram(
            download_result,
            progress_callback=make_upload_progress(pbar)
        )


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
            print("Fetching Available Formats... This may take a moment.")
            try:
                formats = downloader.get_video_qualities(url)
            except Exception as e:
                print(f"ERROR: Failed to fetch video formats: {e}")
                return
        
        # Smart format selection (for both single and playlist)
        video_format, audio_format = display_video_formats(formats)
        
        # Container format selection
        valid_containers = ['mp4', 'mkv', 'webm']
        print("\n  Available container formats:")
        for i, container in enumerate(valid_containers, 1):
            marker = "  ★ Recommended" if i == 1 else ""
            print(f"  {i:>3}.  {container}{marker}")
        
        container_format = 'mp4'
        while True:
            container_choice = input(f"\n  Select container format [1-{len(valid_containers)}] (Enter = recommended): ").strip()
            if not container_choice:
                break
            
            try:
                idx = int(container_choice) - 1
                if 0 <= idx < len(valid_containers):
                    container_format = valid_containers[idx]
                    break
                else:
                    print(f"  Please enter a number between 1 and {len(valid_containers)}")
            except ValueError:
                print("  Please enter a valid number")
        
        print(f"  ✓ Container: {container_format}")
        
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
                print(f"Estimated size: {format_size(estimated_size)}")
        
        # Process videos
        if is_playlist_url:
            successful_uploads = 0
            # Use context manager to keep Telegram session alive for all playlist uploads
            with uploader:
                for idx, entry in enumerate(selected_entries, 1):
                    entry_url = entry['url']
                    entry_title = entry['title']
                    print(f"\n[{idx}/{len(selected_entries)}] {entry_title}")
                    
                    # Estimate size
                    estimated_size = downloader.get_estimated_size(entry_url, video_format, audio_format, container_format)
                    if estimated_size > max_size_mb:
                        print(f"  Skipped: estimated {format_size(estimated_size)} > {format_size(max_size_mb)} limit")
                        continue
                    
                    if estimated_size > 0:
                        print(f"  Estimated size: {format_size(estimated_size)}")
                    
                    local_download_result = None
                    try:
                        local_download_result = download_with_progress(
                            downloader, entry_url, video_format, audio_format, container_format
                        )
                        print(f"  ✓ Downloaded: {local_download_result.video_title} ({local_download_result.duration}s)")

                        if local_download_result.thumbnail_path:
                            local_download_result.thumbnail_path = convert_thumbnail(local_download_result.thumbnail_path)
                        
                        upload_with_progress(uploader, local_download_result)
                        print("  ✓ Upload successful!")
                        successful_uploads += 1
                        
                    except Exception as e:
                        print(f"  ✗ ERROR processing {entry_title}: {e}")
                    finally:
                        if local_download_result:
                            cleanup(local_download_result)
            
            print(f"\n{'='*40}")
            print(f"Playlist complete: {successful_uploads}/{len(selected_entries)} videos uploaded successfully.")
        else:
            # Single video processing
            print("")
            try:
                download_result = download_with_progress(
                    downloader, url, video_format, audio_format, container_format
                )
                print(f"  ✓ Downloaded: {download_result.video_title} ({download_result.duration}s)")

                if download_result.thumbnail_path:
                    download_result.thumbnail_path = convert_thumbnail(download_result.thumbnail_path)
                
                upload_with_progress(uploader, download_result)
                print("  ✓ Upload successful!")
                
            except Exception as e:
                print(f"ERROR: {e}")
    finally:
        # Cleanup for single video mode (playlist handles its own cleanup above)
        if download_result is not None:
            cleanup(download_result)
        print("Done!")


if __name__ == '__main__':
    main()