import os
import logging
from typing import Dict, List, Callable, Optional
from rich.panel import Panel
from rich.prompt import Prompt, IntPrompt, Confirm

from dotenv import load_dotenv

from src.ui.cli import (
    console,
    display_video_formats,
    download_with_progress,
    upload_with_progress
)
from src.core.downloader import YouTubeTelegramDownloader
from src.telegram.uploader import TelegramUploader
from src.utils.validators import validate_youtube_url
from src.utils.helpers import get_env_setup_instructions, cleanup, convert_thumbnail, format_size

def main() -> None:
    load_dotenv()
    console.print(Panel.fit("[bold blue]YT-TG-Upload[/bold blue]\n[dim]YouTube to Telegram Downloader/Uploader[/dim]"))
    
    required_vars = ['TELEGRAM_API_ID', 'TELEGRAM_API_HASH', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHANNEL_ID']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        console.print("[bold red]ERROR: Missing required environment variables:[/bold red]")
        for var in missing_vars:
            console.print(f"  - {var}")
        console.print(get_env_setup_instructions())
        return
    
    url = Prompt.ask("[bold]Enter YouTube video URL[/bold]").strip()
    if not url:
        console.print("[red]ERROR: URL cannot be empty[/red]")
        return
    
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    channel_id = int(os.getenv('TELEGRAM_CHANNEL_ID'))
    
    cookies_file = Prompt.ask("[bold]Enter path to cookies file[/bold] [dim](optional, press Enter to skip)[/dim]", default="", show_default=False).strip()
    if cookies_file and not os.path.exists(cookies_file):
        console.print(f"[yellow]Warning: Cookie file {cookies_file} not found[/yellow]")
        cookies_file = None
        
    download_result = None
    try:
        downloader = YouTubeTelegramDownloader(cookies_file)
        uploader = TelegramUploader(bot_token, channel_id)

        if not validate_youtube_url(url):
            console.print("[red]ERROR: Invalid YouTube URL[/red]")
            return

        is_playlist_url = downloader.is_playlist(url)
        
        formats = None
        if is_playlist_url:
            with console.status("[bold cyan]Extracting playlist entries..."):
                try:
                    playlist_entries = downloader.get_playlist_entries(url)
                except Exception as e:
                    console.print(f"[red]ERROR: Failed to process playlist: {e}[/red]")
                    return
            
            console.print(f"\n[bold]Playlist contains {len(playlist_entries)} videos:[/bold]")
            for i, entry in enumerate(playlist_entries, 1):
                console.print(f"  {i}. {entry['title']}")
                
            while True:
                selection_input = Prompt.ask("\n[bold]Select videos[/bold] [dim](e.g., 'all', '1', '1,3-5')[/dim]").strip().lower()
                if not selection_input:
                    console.print("[yellow]Please enter a selection.[/yellow]")
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
                        selected_indices = sorted(set(selected_indices))
                        if all(0 <= idx < len(playlist_entries) for idx in selected_indices):
                            break
                        else:
                            console.print("[red]Invalid indices. Please try again.[/red]")
                    except ValueError:
                        console.print("[red]Invalid input. Please use 'all' or comma-separated indices/ranges.[/red]")
            
            selected_entries = [playlist_entries[i] for i in selected_indices]
            console.print(f"[green]✓ Selected {len(selected_entries)} videos.[/green]")
            
            max_size_mb = IntPrompt.ask("[bold]Enter max file size in MB[/bold]", default=2048)
            
            first_video_url = selected_entries[0]['url']
            with console.status("[bold cyan]Fetching Available Formats from first video..."):
                formats = downloader.get_video_qualities(first_video_url)
                
        else:
            selected_entries = None
            max_size_mb = 2048
            with console.status("[bold cyan]Fetching Available Formats..."):
                try:
                    formats = downloader.get_video_qualities(url)
                except Exception as e:
                    console.print(f"[red]ERROR: Failed to fetch video formats: {e}[/red]")
                    return
        
        video_format, audio_format = display_video_formats(formats)
        
        valid_containers = ['mp4', 'mkv', 'webm']
        console.print("\n[bold]Available container formats:[/bold]")
        for i, container in enumerate(valid_containers, 1):
            marker = " [bold green]★ Recommended[/bold green]" if i == 1 else ""
            console.print(f"  {i}. {container}{marker}")
        
        container_format = 'mp4'
        while True:
            container_choice = Prompt.ask("\n[bold]Select container format[/bold] [dim](Enter = recommended)[/dim]", default="1", show_default=False).strip()
            try:
                idx = int(container_choice) - 1
                if 0 <= idx < len(valid_containers):
                    container_format = valid_containers[idx]
                    break
                else:
                    console.print(f"[red]Please enter a number between 1 and {len(valid_containers)}[/red]")
            except ValueError:
                console.print("[red]Please enter a valid number[/red]")
                
        console.print(f"[green]✓ Container:[/green] {container_format}")
        
        if not is_playlist_url:
            with console.status("[bold cyan]Estimating download size..."):
                estimated_size = downloader.get_estimated_size(url, video_format, audio_format, container_format)
            
            if estimated_size > 2048:
                confirm = Confirm.ask(f"[yellow]Estimated size {estimated_size:.1f} MB > 2048 MB limit. Proceed anyway?[/yellow]", default=True)
                if not confirm:
                    console.print("[red]Aborted by user.[/red]")
                    return
            else:
                console.print(f"Estimated size: [cyan]{format_size(estimated_size)}[/cyan]")
        
        if is_playlist_url:
            successful_uploads = 0
            with uploader:
                for idx, entry in enumerate(selected_entries, 1):
                    entry_url = entry['url']
                    entry_title = entry['title']
                    console.print(Panel(f"[bold]{entry_title}[/bold]", title=f"Video {idx}/{len(selected_entries)}", border_style="blue"))
                    
                    with console.status("[bold cyan]Estimating size..."):
                        estimated_size = downloader.get_estimated_size(entry_url, video_format, audio_format, container_format)
                    
                    if estimated_size > max_size_mb:
                        console.print(f"[yellow]⚠ Skipped:[/yellow] estimated {format_size(estimated_size)} > {format_size(max_size_mb)} limit")
                        continue
                    
                    if estimated_size > 0:
                        console.print(f"Estimated size: [cyan]{format_size(estimated_size)}[/cyan]")
                    
                    local_download_result = None
                    try:
                        local_download_result = download_with_progress(
                            downloader, entry_url, video_format, audio_format, container_format
                        )
                        console.print(f"[green]✓ Downloaded:[/green] {local_download_result.video_title} ({local_download_result.duration}s)")

                        if local_download_result.thumbnail_path:
                            local_download_result.thumbnail_path = convert_thumbnail(local_download_result.thumbnail_path)
                        
                        upload_with_progress(uploader, local_download_result)
                        console.print("[green]✓ Upload successful![/green]")
                        successful_uploads += 1
                        
                    except Exception as e:
                        console.print(f"[red]✗ ERROR processing {entry_title}: {e}[/red]")
                    finally:
                        if local_download_result:
                            cleanup(local_download_result)
            
            console.print(Panel(f"[bold green]Playlist complete:[/bold green] {successful_uploads}/{len(selected_entries)} videos uploaded successfully.", border_style="green"))
        else:
            console.print("")
            try:
                download_result = download_with_progress(
                    downloader, url, video_format, audio_format, container_format
                )
                console.print(f"[green]✓ Downloaded:[/green] {download_result.video_title} ({download_result.duration}s)")

                if download_result.thumbnail_path:
                    download_result.thumbnail_path = convert_thumbnail(download_result.thumbnail_path)
                
                upload_with_progress(uploader, download_result)
                console.print("[green]✓ Upload successful![/green]")
                
            except Exception as e:
                console.print(f"[red]ERROR: {e}[/red]")
    finally:
        if download_result is not None:
            cleanup(download_result)
        console.print("[bold green]Done![/bold green]")

if __name__ == '__main__':
    main()