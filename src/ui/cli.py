from contextlib import contextmanager

from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.table import Table
from rich.panel import Panel
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    DownloadColumn,
    TransferSpeedColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
    TaskID,
)

from src.models import VideoInfo
from src.config import config
from src.utils.helpers import format_size

# Global console instance for UI rendering
console = Console()


def prompt_mode() -> str:
    """
    Show the top-level mode menu. Returns 'single' | 'playlist' | 'batch'.
    """
    console.print(Panel.fit(
        "[bold]Choose mode[/bold]\n"
        "  [bold]1.[/bold] Single video\n"
        "  [bold]2.[/bold] Playlist\n"
        "  [bold]3.[/bold] Batch — multiple URLs at once",
        title="Mode", border_style="blue"
    ))
    while True:
        choice = Prompt.ask("Mode", default="1", show_default=False).strip()
        if choice == "1":
            return "single"
        elif choice == "2":
            return "playlist"
        elif choice == "3":
            return "batch"
        console.print("[red]Please enter 1, 2, or 3.[/red]")


def prompt_url(label: str = "Enter YouTube URL") -> str:
    """
    Prompt for a single YouTube URL. No pre-validation — yt-dlp validates downstream
    and produces a better error message than a regex would.
    """
    while True:
        url = Prompt.ask(f"[bold]{label}[/bold]").strip()
        if not url:
            console.print("[red]URL cannot be empty.[/red]")
            continue
        return url


def prompt_batch_urls() -> list:
    """
    Prompt user to paste multiple YouTube URLs, one per line. Stop on empty line.
    Returns a list of URLs (non-empty, non-duplicate). No pre-validation — yt-dlp
    will reject bad URLs downstream with a proper error.
    """
    console.print(Panel.fit(
        "[bold]Batch mode[/bold] — paste URLs one per line.\n"
        "[dim]Press Enter on an empty line to finish.[/dim]",
        border_style="blue"
    ))
    urls = []
    while True:
        line = Prompt.ask("URL (or empty to finish)", default="", show_default=False).strip()
        if not line:
            if not urls:
                console.print("[red]No URLs entered. Please add at least one.[/red]")
                continue
            break
        if line in urls:
            console.print(f"[yellow]⚠ Already added this URL — skipping duplicate:[/yellow] {line}")
            continue
        urls.append(line)
        console.print(f"[green]Added:[/green] {line}  [dim]({len(urls)} total)[/dim]")
    return urls


def prompt_continue() -> bool:
    """Ask whether the user wants to process another set of URLs."""
    return Confirm.ask("[bold]Process another?[/bold]", default=False)


def prompt_container_format() -> str:
    """
    Show the container-format menu (mp4 / mkv / webm) and return the chosen format.
    mp4 is recommended and selected by default.
    """
    valid_containers = list(config.valid_containers)
    console.print("\n[bold]Available container formats:[/bold]")
    for i, container in enumerate(valid_containers, 1):
        marker = " [bold green]★ Recommended[/bold green]" if i == 1 else ""
        console.print(f"  {i}. {container}{marker}")

    while True:
        container_choice = Prompt.ask(
            "\n[bold]Select container format[/bold] [dim](Enter = recommended)[/dim]",
            default="1", show_default=False,
        ).strip()
        try:
            idx = int(container_choice) - 1
            if 0 <= idx < len(valid_containers):
                chosen = valid_containers[idx]
                console.print(f"[green]✓ Container:[/green] {chosen}")
                return chosen
            else:
                console.print(f"[red]Please enter a number between 1 and {len(valid_containers)}[/red]")
        except ValueError:
            console.print("[red]Please enter a valid number[/red]")

def make_download_hook(progress: Progress, task_id: TaskID):
    """Create a yt-dlp progress_hook callback that drives a Rich progress bar."""
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
    """Create a Pyrogram progress callback that drives a Rich progress bar."""
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
    v_table.add_column("#", justify="right", width=5)
    v_table.add_column("Quality", style="cyan")
    v_table.add_column("Codec", style="green")
    v_table.add_column("Type", justify="center")
    v_table.add_column("Ext", style="yellow")
    v_table.add_column("Size", justify="right")
    
    def get_clean_note(vf):
        # Strip redundant "1080p60fps" text from format_note — resolution and
        # fps are already shown in their own table columns.
        note = vf.get('format_note', '').strip()
        if not note: return ''
        nl = note.lower()
        res = str(vf['resolution'])
        fps = str(int(vf['fps'] or 0))
        test_str = nl.replace(res, '').replace('p', '').replace(fps, '').replace('fps', '').strip()
        return '' if not test_str else note

    # Deduplicate video formats visually (including HDR and progressive status)
    unique_video_formats = []
    seen_video = set()
    for vf in video_formats:
        clean_note = get_clean_note(vf)
        sig = (
            vf['resolution'], vf['fps'], vf['vcodec'], vf['ext'], clean_note,
            vf.get('dynamic_range', 'SDR'), vf.get('is_progressive', False),
        )
        if sig not in seen_video:
            seen_video.add(sig)
            unique_video_formats.append(vf)
            
    for i, vf in enumerate(unique_video_formats, 1):
        # Quality column — append HDR badge when not SDR
        quality = f"{vf['resolution']}p"
        if vf['fps'] and vf['fps'] > 0:
            quality += f"@{vf['fps']}fps"
        dr = vf.get('dynamic_range', 'SDR')
        if dr and dr != 'SDR':
            quality += f" [magenta]{dr}[/magenta]"

        # Type column — progressive (A+V) vs video-only
        type_badge = "[bold cyan]▶ + ♪[/bold cyan]" if vf.get('is_progressive') else "[dim]▶[/dim]"

        size_str = format_size(vf['size_mb'], rich=True)

        # Highlight row 1 as recommended
        if i == 1:
            row_num = f"[green]★ {i}[/green]"
            row_style = "bold"
        else:
            row_num = f"[dim]{i}[/dim]"
            row_style = None

        v_table.add_row(row_num, quality, vf['vcodec'], type_badge, vf['ext'], size_str, style=row_style)
    
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
        console.print("\n[yellow]⚠ No separate audio formats found (audio may be included in video stream).[/yellow]")
        
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
        # FloodWait status messages print above the live progress bar without
        # interrupting it. Rich's Progress.console supports print while live.
        def _status(msg: str) -> None:
            progress.console.print(f"[yellow]{msg}[/yellow]")
        uploader.upload_to_telegram(
            download_result,
            progress_callback=make_upload_progress(progress, task_id),
            status_callback=_status,
        )


@contextmanager
def spinner(message: str):
    """Context manager: spinner + elapsed time."""
    progress = Progress(
        SpinnerColumn(),
        TextColumn(message),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    )
    with progress as p:
        p.add_task("", total=None)
        yield p

def prompt_failure_action(title: str, error_message: str, *, default_skip: bool = False) -> str:
    """
    Show an interactive menu when a video fails. User chooses what to do next.

    :param title: Title of the failed video (display only)
    :param error_message: The error message (display only)
    :param default_skip: When True (batch/playlist), default selection is Skip.
    :return: One of 'retry', 'lower', 'skip', 'abort'
    """
    console.print(Panel(
        f"[bold red]✗ ERROR processing[/bold red] [bold]{title}[/bold]\n\n"
        f"[red]{error_message}[/red]",
        title="Failure", border_style="red"
    ))

    options = [
        ("1", "Retry (same quality)"),
        ("2", "Try lower quality"),
        ("3", "Skip this video"),
        ("4", "Abort everything"),
    ]
    default_choice = "3" if default_skip else "1"
    for key, label in options:
        marker = " [green](default)[/green]" if key == default_choice else ""
        console.print(f"  [bold]{key}.[/bold] {label}{marker}")

    while True:
        choice = Prompt.ask("Choose", default=default_choice, show_default=False).strip()
        if choice == "1":
            return "retry"
        elif choice == "2":
            return "lower"
        elif choice == "3":
            return "skip"
        elif choice == "4":
            return "abort"
        console.print("[red]Please enter 1, 2, 3, or 4.[/red]")


def prompt_playlist_selection(playlist_entries: list) -> list:
    """
    Display numbered playlist entries and let the user select which to process.
    Supports 'all', single indices, comma-separated lists, and ranges (e.g. '1,3-5').

    :param playlist_entries: list of dicts with at least a 'title' key
    :return: selected subset of playlist_entries
    """
    console.print(f"\n[bold]Playlist contains {len(playlist_entries)} videos:[/bold]")
    for i, entry in enumerate(playlist_entries, 1):
        console.print(f"  {i}. {entry['title']}")

    while True:
        selection_input = Prompt.ask(
            "\n[bold]Select videos[/bold] [dim](e.g., 'all', '1', '1,3-5')[/dim]"
        ).strip().lower()
        if not selection_input:
            console.print("[yellow]Please enter a selection.[/yellow]")
            continue

        if selection_input == 'all':
            return playlist_entries

        try:
            selected_indices = []
            parts = selection_input.split(',')
            for part in parts:
                part = part.strip()
                if '-' in part:
                    start, end = map(int, part.split('-'))
                    selected_indices.extend(range(start - 1, end))
                else:
                    selected_indices.append(int(part) - 1)
            selected_indices = sorted(set(selected_indices))
            if all(0 <= idx < len(playlist_entries) for idx in selected_indices):
                return [playlist_entries[i] for i in selected_indices]
            else:
                console.print("[red]Invalid indices. Please try again.[/red]")
        except ValueError:
            console.print("[red]Invalid input. Please use 'all' or comma-separated indices/ranges.[/red]")


def display_batch_summary(rows: list) -> None:
    """
    Print a final summary table for batch/playlist runs.

    :param rows: list of dicts with keys 'title', 'quality', 'size', 'status'.
                 'status' is one of 'ok', 'skipped', 'failed'.
    """
    table = Table(title="Batch Summary", show_header=True, header_style="bold magenta")
    table.add_column("#", justify="right", style="dim", width=4)
    table.add_column("Title", style="cyan", max_width=50, no_wrap=True)
    table.add_column("Quality", style="green")
    table.add_column("Size", justify="right")
    table.add_column("Status", justify="center")

    for i, r in enumerate(rows, 1):
        status = r.get("status", "")
        if status == "ok":
            status_str = "[green]✓ Done[/green]"
        elif status == "skipped":
            status_str = "[yellow]⚠ Skipped[/yellow]"
        else:
            status_str = "[red]✗ Failed[/red]"
        table.add_row(
            str(i),
            r.get("title", "?"),
            r.get("quality", "?"),
            r.get("size", "?"),
            status_str,
        )
    console.print(table)
