import os
import logging
from typing import Dict, List, Callable, Optional

from dotenv import load_dotenv

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, IntPrompt, Confirm
from rich.table import Table
from rich.progress import (
    Progress,
    TextColumn,
    BarColumn,
    DownloadColumn,
    TransferSpeedColumn,
    TimeRemainingColumn,
    TaskID,
)

from src.core.downloader import YouTubeTelegramDownloader
from src.telegram.uploader import TelegramUploader
from src.utils.validators import validate_youtube_url, validate_format_selection
from src.utils.helpers import get_env_setup_instructions, cleanup, convert_thumbnail, format_size
from src.models import VideoInfo, DownloadResult

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

console = Console()

def make_download_hook(progress: Progress, task_id: TaskID):
    def hook(d):
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded = d.get('downloaded_bytes', 0)
            
            task = progress.tasks[task_id]
            if downloaded < task.completed:
                # new stream (e.g. video finished, audio started)
                progress.update(task_id, completed=downloaded, description="[cyan]↓ Audio")
            
            if total and task.total != total:
                progress.update(task_id, total=total)
            progress.update(task_id, completed=downloaded)
        elif d['status'] == 'finished':
            task = progress.tasks[task_id]
            if task.total and task.completed < task.total:
                progress.update(task_id, completed=task.total)
    return hook

def make_upload_progress(progress: Progress, task_id: TaskID):
    def callback(current, total):
        task = progress.tasks[task_id]
        if task.total != total:
            progress.update(task_id, total=total)
        progress.update(task_id, completed=current)
    return callback

def display_video_formats(formats: VideoInfo) -> tuple:
    video_formats = formats['video_formats']
    audio_formats = formats['audio_formats']
    
    # Video Table
    console.print("\n")
    v_table = Table(title="Available Video Formats", show_header=True, header_style="bold magenta")
    v_table.add_column("#", justify="right", style="dim", width=4)
    v_table.add_column("Quality", style="cyan")
    v_table.add_column("Codec", style="green")
    v_table.add_column("Ext", style="yellow")
    v_table.add_column("Size", justify="right")
    v_table.add_column("Note", style="bold green")
    
    for i, vf in enumerate(video_formats, 1):
        quality = f"{vf['resolution']}p"
        if vf['fps'] and vf['fps'] > 0:
            quality += f"@{vf['fps']}fps"
        size_str = format_size(vf['size_mb'])
        marker = "★ Recommended" if i == 1 else ""
        v_table.add_row(str(i), quality, vf['vcodec'], vf['ext'], size_str, marker)
    
    console.print(v_table)
    
    # Video Selection
    while True:
        video_choice = Prompt.ask("Select video format [dim](Enter = recommended)[/dim]", default="1", show_default=False)
        try:
            idx = int(video_choice) - 1
            if 0 <= idx < len(video_formats):
                selected_video = video_formats[idx]
                quality = f"{selected_video['resolution']}p"
                if selected_video['fps']:
                    quality += f"@{selected_video['fps']}fps"
                console.print(f"[green]✓ Selected Video:[/green] {quality} ({selected_video['vcodec']}, {format_size(selected_video['size_mb'])})")
                break
            else:
                console.print(f"[red]Please enter a number between 1 and {len(video_formats)}[/red]")
        except ValueError:
            console.print("[red]Please enter a valid number.[/red]")
            
    # Audio Table
    selected_audio = None
    if audio_formats:
        console.print("\n")
        a_table = Table(title="Available Audio Formats", show_header=True, header_style="bold magenta")
        a_table.add_column("#", justify="right", style="dim", width=4)
        a_table.add_column("Bitrate", style="cyan")
        a_table.add_column("Codec", style="green")
        a_table.add_column("Ext", style="yellow")
        a_table.add_column("Note", style="bold green")
        
        for i, af in enumerate(audio_formats, 1):
            bitrate_str = f"{af['bitrate']:.0f} kbps"
            marker = "★ Recommended" if i == 1 else ""
            a_table.add_row(str(i), bitrate_str, af['acodec'], af['ext'], marker)
        
        console.print(a_table)
        
        while True:
            audio_choice = Prompt.ask("Select audio format [dim](Enter = recommended)[/dim]", default="1", show_default=False)
            try:
                idx = int(audio_choice) - 1
                if 0 <= idx < len(audio_formats):
                    selected_audio = audio_formats[idx]
                    console.print(f"[green]✓ Selected Audio:[/green] {selected_audio['bitrate']:.0f} kbps ({selected_audio['acodec']})")
                    break
                else:
                    console.print(f"[red]Please enter a number between 1 and {len(audio_formats)}[/red]")
            except ValueError:
                console.print("[red]Please enter a valid number.[/red]")
    else:
        console.print("\n[yellow]No separate audio formats found (audio may be included in video stream).[/yellow]")
        
    video_format_id = selected_video['format_id']
    audio_format_id = selected_audio['format_id'] if selected_audio else None
    return video_format_id, audio_format_id


def download_with_progress(downloader, url, video_format, audio_format, container_format):
    progress = Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        "[progress.percentage]{task.percentage:>3.0f}%",
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console,
    )
    with progress:
        task_id = progress.add_task("[cyan]↓ Video", total=None)
        result = downloader.download_video(
            url, video_format, audio_format, container_format,
            progress_hook=make_download_hook(progress, task_id)
        )
    return result

def upload_with_progress(uploader, download_result):
    progress = Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        "[progress.percentage]{task.percentage:>3.0f}%",
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console,
    )
    with progress:
        task_id = progress.add_task("[magenta]↑ Uploading", total=None)
        uploader.upload_to_telegram(
            download_result,
            progress_callback=make_upload_progress(progress, task_id)
        )

def main() -> None:
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