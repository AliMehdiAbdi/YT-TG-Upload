"""
Interactive flow controller for YT-TG-Upload.

Owns the per-session orchestration: mode menu, single/playlist/batch processing,
retry-on-failure, per-attempt cleanup, and end-of-run summary.

main.py is the thin entry point that owns one-time setup (env vars, JS runtime
warning, cookies prompt, session loop) and delegates each iteration to run_session().
"""
from typing import Optional, List, Tuple, Protocol
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt

from src.models import DownloadResult
from src.config import config
from src.ui.cli import (
    console,
    display_video_formats,
    download_with_progress,
    upload_with_progress,
    prompt_failure_action,
    prompt_mode,
    prompt_url,
    prompt_batch_urls,
    prompt_container_format,
    prompt_playlist_selection,
    display_batch_summary,
    spinner,
)
from src.core.downloader import YouTubeTelegramDownloader
from src.telegram.uploader import TelegramUploader
from src.utils.helpers import (
    cleanup,
    convert_thumbnail,
    format_size,
    format_size_status,
)


# ---------------------------------------------------------------------------
#  Closure type hints (Protocol)
#
#  These Protocols tell IDEs (and future readers) the exact signature of the
#  closures returned by _make_attempt_one / _make_run_with_retry.  Without
#  them the factories return bare "function" and the IDE can't autocomplete
#  parameters, check argument types, or verify return values at call sites.
# ---------------------------------------------------------------------------

class AttemptFn(Protocol):
    """Signature of the closure returned by _make_attempt_one."""
    def __call__(
        self,
        url: str,
        video_format_id: str,
        audio_format_id: Optional[str],
    ) -> DownloadResult: ...


class RunWithRetryFn(Protocol):
    """Signature of the closure returned by _make_run_with_retry."""
    def __call__(
        self,
        url: str,
        video_format: str,
        audio_format: Optional[str],
        title: str,
        *,
        default_skip: bool = False,
    ) -> str: ...


# ---------------------------------------------------------------------------
#  Public entry point
# ---------------------------------------------------------------------------

def run_session(downloader: YouTubeTelegramDownloader, uploader: TelegramUploader) -> None:
    """One interactive session: mode menu → process. Does NOT loop; caller handles "do another?"."""
    mode = prompt_mode()
    if mode == "single":
        _run_single_mode(downloader, uploader)
    elif mode == "playlist":
        _run_playlist_mode(downloader, uploader)
    elif mode == "batch":
        _run_batch_mode(downloader, uploader)


# ---------------------------------------------------------------------------
#  Shared helpers
# ---------------------------------------------------------------------------

def _confirm_size(estimated_size: float, max_size_mb: float = 2048) -> bool:
    """Show size estimate, prompt for proceed if over limit. Returns False if user aborts."""
    if estimated_size <= 0:
        console.print(format_size_status(estimated_size))
        return Confirm.ask("[yellow]Proceed without a size estimate?[/yellow]", default=True)
    elif estimated_size > max_size_mb:
        return Confirm.ask(
            f"[yellow]Estimated size {format_size(estimated_size)} > {format_size(max_size_mb)} limit. Proceed anyway?[/yellow]",
            default=True,
        )
    else:
        console.print(format_size_status(estimated_size))
        return True


# ---------------------------------------------------------------------------
#  Retry machinery
# ---------------------------------------------------------------------------

def _make_attempt_one(downloader, uploader, container_format) -> AttemptFn:
    """Build a per-attempt download+upload closure bound to the session's deps."""
    def _attempt_one(url_to_use: str, v_fmt_id: str, a_fmt_id: Optional[str]) -> DownloadResult:
        result = download_with_progress(downloader, url_to_use, v_fmt_id, a_fmt_id, container_format)
        console.print(f"[green]✓ Downloaded:[/green] {result.video_title} ({result.duration}s)")
        if result.thumbnail_path:
            result.thumbnail_path = convert_thumbnail(result.thumbnail_path)
        upload_with_progress(uploader, result)
        console.print("[green]✓ Upload successful![/green]")
        return result
    return _attempt_one


def _make_run_with_retry(downloader, uploader, container_format) -> RunWithRetryFn:
    """
    Build a _run_with_retry closure bound to session deps.
    Returns a function(url, v_id, a_id, title, default_skip) -> 'ok' | 'skipped' | 'aborted'.
    Each attempt cleans up its own DownloadResult before any retry/return.
    """
    _attempt_one = _make_attempt_one(downloader, uploader, container_format)

    def _run_with_retry(
        url_to_use: str,
        cur_video_format: str,
        cur_audio_format: Optional[str],
        title_label: str,
        *,
        default_skip: bool = False,
    ) -> str:
        v_id = cur_video_format
        a_id = cur_audio_format
        while True:
            local_result = None
            try:
                local_result = _attempt_one(url_to_use, v_id, a_id)
                cleanup(local_result)
                return "ok"
            except Exception as e:
                action = prompt_failure_action(title_label, str(e), default_skip=default_skip)
                if local_result:
                    try:
                        cleanup(local_result)
                    except Exception as cleanup_err:
                        console.print(f"[dim]Cleanup note: {cleanup_err}[/dim]")
                if action == "retry":
                    continue
                elif action == "lower":
                    try:
                        with spinner("[bold cyan]Re-fetching formats..."):
                            refetch = downloader.get_video_qualities(url_to_use)
                        new_v, new_a = display_video_formats(refetch)
                        v_id = new_v['format_id']
                        a_id = new_a['format_id'] if new_a else None
                    except Exception as refetch_err:
                        console.print(Panel(
                            f"[red]✗ Could not re-fetch formats:[/red] {refetch_err}",
                            title="Error", border_style="red"
                        ))
                    continue
                elif action == "skip":
                    return "skipped"
                elif action == "abort":
                    return "aborted"
    return _run_with_retry


# ---------------------------------------------------------------------------
#  Shared processing loop for playlist & batch modes
# ---------------------------------------------------------------------------

def _process_entries(
    entries: List[Tuple[str, str]],
    downloader: YouTubeTelegramDownloader,
    uploader: TelegramUploader,
    preferred_video,
    preferred_audio,
    container_format: str,
    max_size_mb: int,
    *,
    entry_label: str = "Video",
) -> Tuple[int, int, list]:
    """
    Download+upload a list of entries, matching each one to the user-selected quality.

    :param entries: list of (url, display_title) tuples
    :param preferred_video: reference video format chosen from the first entry
    :param preferred_audio: reference audio format chosen from the first entry
    :param entry_label: label for progress panels ("Video" or "URL")
    :return: (successful_uploads, skipped, summary_rows)
    """
    _run_with_retry = _make_run_with_retry(downloader, uploader, container_format)

    successful_uploads = 0
    skipped = 0
    summary_rows: list = []

    with uploader:
        for idx, (entry_url, entry_title) in enumerate(entries, 1):
            console.print(Panel(
                f"[bold]{entry_title}[/bold]",
                title=f"{entry_label} {idx}/{len(entries)}",
                border_style="blue",
            ))

            quality_label = "?"
            size_label = "?"

            # Outer while-loop allows retrying format-fetch failures.
            while True:
                try:
                    with spinner("[bold cyan]Matching formats..."):
                        entry_formats = downloader.get_video_qualities(entry_url)
                        matched_video = YouTubeTelegramDownloader.match_video_format(
                            entry_formats['video_formats'], preferred_video
                        )
                        matched_audio = YouTubeTelegramDownloader.match_audio_format(
                            entry_formats['audio_formats'], preferred_audio
                        )

                    if not matched_video:
                        console.print("[yellow]⚠ Skipped:[/yellow] no video formats available")
                        skipped += 1
                        summary_rows.append({"title": entry_title, "quality": "-", "size": "-", "status": "skipped"})
                        break

                    v_id = matched_video['format_id']
                    a_id = matched_audio['format_id'] if matched_audio else None

                    fps = matched_video.get('fps') or 0
                    fps_part = f"@{int(fps)}fps" if fps else ""
                    quality_label = (
                        f"{matched_video['resolution']}p{fps_part} "
                        f"{matched_video.get('vcodec', '')}"
                    )

                    if v_id != preferred_video['format_id']:
                        console.print(f"[dim]Matched format:[/dim] {quality_label}")
                    else:
                        console.print(f"[dim]Format:[/dim] {quality_label}")

                    estimated_size = YouTubeTelegramDownloader.estimate_size(
                        entry_formats['video_formats'],
                        entry_formats['audio_formats'],
                        v_id, a_id,
                    )

                    if estimated_size > max_size_mb:
                        console.print(
                            f"[yellow]⚠ Skipped:[/yellow] estimated "
                            f"{format_size(estimated_size)} > {format_size(max_size_mb)} limit"
                        )
                        skipped += 1
                        summary_rows.append({"title": entry_title, "quality": quality_label, "size": format_size(estimated_size), "status": "skipped"})
                        break

                    console.print(format_size_status(estimated_size, max_size_mb))
                    size_label = format_size(estimated_size)

                    outcome = _run_with_retry(
                        entry_url, v_id, a_id, entry_title,
                        default_skip=True,
                    )
                    if outcome == "ok":
                        successful_uploads += 1
                        summary_rows.append({"title": entry_title, "quality": quality_label, "size": size_label, "status": "ok"})
                    elif outcome == "skipped":
                        skipped += 1
                        summary_rows.append({"title": entry_title, "quality": quality_label, "size": size_label, "status": "skipped"})
                    elif outcome == "aborted":
                        console.print(f"[red]✗ Aborted by user. Stopping {entry_label.lower()} processing.[/red]")
                        summary_rows.append({"title": entry_title, "quality": quality_label, "size": size_label, "status": "failed"})
                        return successful_uploads, skipped, summary_rows
                    break  # success or skip — move to next entry

                except Exception as e:
                    action = prompt_failure_action(entry_title, str(e), default_skip=True)
                    if action == "retry":
                        continue  # retry format fetch
                    elif action == "lower":
                        # "Lower quality" is not applicable when the format fetch
                        # itself failed — skip with an explanation.
                        console.print("[yellow]⚠ Cannot offer lower quality — format fetch failed. Skipping.[/yellow]")
                        skipped += 1
                        summary_rows.append({"title": entry_title, "quality": quality_label, "size": size_label, "status": "skipped"})
                        break
                    elif action == "skip":
                        skipped += 1
                        summary_rows.append({"title": entry_title, "quality": quality_label, "size": size_label, "status": "skipped"})
                        break
                    elif action == "abort":
                        console.print(f"[red]✗ Aborted by user. Stopping {entry_label.lower()} processing.[/red]")
                        summary_rows.append({"title": entry_title, "quality": quality_label, "size": size_label, "status": "failed"})
                        return successful_uploads, skipped, summary_rows

    return successful_uploads, skipped, summary_rows


# ---------------------------------------------------------------------------
#  Mode runners
# ---------------------------------------------------------------------------

def _run_single_mode(downloader, uploader) -> None:
    url = prompt_url("Enter YouTube video URL")

    with spinner("[bold cyan]Fetching Available Formats..."):
        try:
            formats = downloader.get_video_qualities(url)
        except Exception as e:
            console.print(Panel(
                f"[red]✗ ERROR: Could not read this URL.[/red]\n"
                f"[dim]Details: {e}[/dim]\n"
                f"[dim]Hint: check that it is a valid YouTube video URL and is not private/deleted.[/dim]",
                title="Error", border_style="red"
            ))
            return

    preferred_video, preferred_audio = display_video_formats(formats)
    video_format = preferred_video['format_id']
    audio_format = preferred_audio['format_id'] if preferred_audio else None

    container_format = prompt_container_format()

    estimated_size = YouTubeTelegramDownloader.estimate_size(
        formats['video_formats'], formats['audio_formats'], video_format, audio_format
    )
    if not _confirm_size(estimated_size):
        console.print("[red]✗ Aborted by user.[/red]")
        return

    _run_with_retry = _make_run_with_retry(downloader, uploader, container_format)
    console.print("")
    outcome = _run_with_retry(url, video_format, audio_format, "Single video", default_skip=False)
    if outcome == "aborted":
        console.print("[red]✗ Aborted by user.[/red]")


def _run_playlist_mode(downloader, uploader) -> None:
    url = prompt_url("Enter YouTube playlist URL")

    is_playlist_url = downloader.is_playlist(url)
    if not is_playlist_url:
        console.print("[yellow]⚠ This URL does not appear to be a playlist. Try single mode instead.[/yellow]")
        return

    with spinner("[bold cyan]Extracting playlist entries..."):
        try:
            playlist_entries = downloader.get_playlist_entries(url)
        except Exception as e:
            console.print(Panel(
                f"[red]✗ ERROR: Could not read this playlist.[/red]\n"
                f"[dim]Details: {e}[/dim]\n"
                f"[dim]Hint: check that the URL is a YouTube playlist and is public/unlisted.[/dim]",
                title="Error", border_style="red"
            ))
            return

    selected_entries = prompt_playlist_selection(playlist_entries)
    console.print(f"[green]✓ Selected {len(selected_entries)} videos.[/green]")
    console.print(
        "[dim]Quality is chosen once from the first video; "
        "later videos auto-match the same resolution/fps/codec.[/dim]"
    )

    max_size_mb = IntPrompt.ask(
        "[bold]Enter max file size in MB[/bold]", default=config.default_max_size_mb,
    )

    first_video_url = selected_entries[0]['url']
    with spinner("[bold cyan]Fetching Available Formats from first video..."):
        try:
            formats = downloader.get_video_qualities(first_video_url)
        except Exception as e:
            console.print(Panel(
                f"[red]✗ ERROR: Could not read formats from the first video.[/red]\n"
                f"[dim]Details: {e}[/dim]",
                title="Error", border_style="red"
            ))
            return

    preferred_video, preferred_audio = display_video_formats(formats)
    container_format = prompt_container_format()

    entries = [(e['url'], e['title']) for e in selected_entries]
    successful, skipped, summary_rows = _process_entries(
        entries, downloader, uploader, preferred_video, preferred_audio,
        container_format, max_size_mb, entry_label="Video",
    )

    summary = f"[bold green]Playlist complete:[/bold green] {successful}/{len(selected_entries)} uploaded"
    if skipped:
        summary += f", {skipped} skipped"
    console.print(Panel(summary, border_style="green"))
    display_batch_summary(summary_rows)


def _run_batch_mode(downloader, uploader) -> None:
    urls = prompt_batch_urls()
    if not urls:
        return

    max_size_mb = IntPrompt.ask(
        "[bold]Enter max file size in MB[/bold]", default=config.default_max_size_mb,
    )

    first_url = urls[0]
    with spinner("[bold cyan]Fetching Available Formats from first URL..."):
        try:
            formats = downloader.get_video_qualities(first_url)
        except Exception as e:
            console.print(Panel(
                f"[red]✗ ERROR: Could not read formats from the first URL.[/red]\n"
                f"[dim]Details: {e}[/dim]\n"
                f"[dim]Hint: check that this URL is a valid YouTube video.[/dim]",
                title="Error", border_style="red"
            ))
            return

    preferred_video, preferred_audio = display_video_formats(formats)
    container_format = prompt_container_format()

    entries = [(u, u) for u in urls]  # use URL as both url and display title
    successful, skipped, summary_rows = _process_entries(
        entries, downloader, uploader, preferred_video, preferred_audio,
        container_format, max_size_mb, entry_label="URL",
    )

    summary = f"[bold green]Batch complete:[/bold green] {successful}/{len(urls)} uploaded"
    if skipped:
        summary += f", {skipped} skipped"
    console.print(Panel(summary, border_style="green"))
    display_batch_summary(summary_rows)
