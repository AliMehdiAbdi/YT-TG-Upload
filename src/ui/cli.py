from rich.console import Console
from rich.prompt import Prompt
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

from src.models import VideoInfo
from src.utils.helpers import format_size

# Global console instance for UI rendering
console = Console()

def make_download_hook(progress: Progress, task_id: TaskID):
    def hook(d):
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded = d.get('downloaded_bytes', 0)
            
            speed = d.get('_speed_str', '').strip()
            eta = d.get('_eta_str', '').strip()
            if eta:
                eta = f"ETA {eta}"
            
            task = progress.tasks[task_id]
            if downloaded < task.completed:
                # new stream (e.g. video finished, audio started)
                progress.update(task_id, completed=downloaded, description="[cyan]↓ Audio")
            
            if total and task.total != total:
                progress.update(task_id, total=total)
            progress.update(task_id, completed=downloaded, yt_speed=speed, yt_eta=eta)
        elif d['status'] == 'finished':
            task = progress.tasks[task_id]
            if task.total and task.completed < task.total:
                progress.update(task_id, completed=task.total)
            progress.update(task_id, yt_speed="", yt_eta="")
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
    
    def get_clean_note(vf):
        note = vf.get('format_note', '').strip()
        if not note: return ''
        nl = note.lower()
        res = str(vf['resolution'])
        fps = str(int(vf['fps'] or 0))
        test_str = nl.replace(res, '').replace('p', '').replace(fps, '').replace('fps', '').strip()
        return '' if not test_str else note

    # Deduplicate video formats visually
    unique_video_formats = []
    seen_video = set()
    for vf in video_formats:
        clean_note = get_clean_note(vf)
        sig = (vf['resolution'], vf['fps'], vf['vcodec'], vf['ext'], clean_note)
        if sig not in seen_video:
            seen_video.add(sig)
            unique_video_formats.append(vf)
            
    for i, vf in enumerate(unique_video_formats, 1):
        quality = f"{vf['resolution']}p"
        if vf['fps'] and vf['fps'] > 0:
            quality += f"@{vf['fps']}fps"
        size_str = format_size(vf['size_mb'], rich=True)
        v_table.add_row(str(i), quality, vf['vcodec'], vf['ext'], size_str)
    
    console.print(v_table)
    
    # Video Selection
    while True:
        video_choice = Prompt.ask("Select video format", default="1")
        try:
            idx = int(video_choice) - 1
            if 0 <= idx < len(unique_video_formats):
                selected_video = unique_video_formats[idx]
                quality = f"{selected_video['resolution']}p"
                if selected_video['fps']:
                    quality += f"@{selected_video['fps']}fps"
                size_label = format_size(selected_video['size_mb'], rich=True)
                console.print(f"[green]✓ Selected Video:[/green] {quality} ({selected_video['vcodec']}, {size_label})")
                break
            else:
                console.print(f"[red]Please enter a number between 1 and {len(unique_video_formats)}[/red]")
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
        a_table.add_column("Size", justify="right")
        
        # Deduplicate audio formats visually
        unique_audio_formats = []
        seen_audio = set()
        for af in audio_formats:
            sig = (af['bitrate'], af['acodec'], af['ext'])
            if sig not in seen_audio:
                seen_audio.add(sig)
                unique_audio_formats.append(af)
        
        for i, af in enumerate(unique_audio_formats, 1):
            bitrate_str = f"{af['bitrate']:.0f} kbps"
            size_str = format_size(af.get('size_mb', 0), rich=True)
            a_table.add_row(str(i), bitrate_str, af['acodec'], af['ext'], size_str)
        
        console.print(a_table)
        
        while True:
            audio_choice = Prompt.ask("Select audio format", default="1")
            try:
                idx = int(audio_choice) - 1
                if 0 <= idx < len(unique_audio_formats):
                    selected_audio = unique_audio_formats[idx]
                    size_label = format_size(selected_audio.get('size_mb', 0), rich=True)
                    console.print(f"[green]✓ Selected Audio:[/green] {selected_audio['bitrate']:.0f} kbps ({selected_audio['acodec']}, {size_label})")
                    break
                else:
                    console.print(f"[red]Please enter a number between 1 and {len(unique_audio_formats)}[/red]")
            except ValueError:
                console.print("[red]Please enter a valid number.[/red]")
    else:
        console.print("\n[yellow]No separate audio formats found (audio may be included in video stream).[/yellow]")
        
    return selected_video, selected_audio


def download_with_progress(downloader, url, video_format, audio_format, container_format):
    progress = Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        "[progress.percentage]{task.percentage:>3.0f}%",
        DownloadColumn(),
        TextColumn("[cyan]{task.fields[yt_speed]}"),
        TextColumn("[yellow]{task.fields[yt_eta]}"),
        console=console,
    )
    with progress:
        task_id = progress.add_task("[cyan]↓ Video", total=None, yt_speed="", yt_eta="")
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
