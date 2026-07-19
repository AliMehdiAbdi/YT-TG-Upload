import os
import sys
import logging
from rich.panel import Panel
from rich.prompt import Prompt, Confirm

from dotenv import load_dotenv

from src.ui.cli import console, prompt_continue
from src.ui.flow import run_session
from src.core.downloader import YouTubeTelegramDownloader
from src.telegram.uploader import TelegramUploader
from src.utils.validators import validate_cookies_path
from src.utils.helpers import get_env_setup_instructions


def main() -> None:
    logging.getLogger("pyrogram").setLevel(logging.ERROR)
    load_dotenv()
    console.print(Panel.fit("[bold blue]YT-TG-Upload[/bold blue]\n[dim]YouTube to Telegram Downloader/Uploader[/dim]"))
    console.print()

    required_vars = ['TELEGRAM_API_ID', 'TELEGRAM_API_HASH', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHANNEL_ID']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    if missing_vars:
        console.print("[bold red]✗ Missing required environment variables:[/bold red]")
        for var in missing_vars:
            console.print(f"  - {var}")
        console.print(get_env_setup_instructions())
        return

    if not YouTubeTelegramDownloader.check_js_runtime():
        console.print(Panel(
            "[yellow]No supported JavaScript runtime (Node.js or Deno) could be found.[/yellow]\n\n"
            "YouTube extraction without a JS runtime is deprecated. Some premium or high-quality formats may be missing.\n"
            "To fix this, install [bold]Node.js[/bold] or [bold]Deno[/bold] on your system.",
            title="Warning: JS Runtime Missing",
            border_style="yellow"
        ))

    # Safe to call int() — missing_vars check above guarantees these are non-empty.
    bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
    channel_id = int(os.getenv('TELEGRAM_CHANNEL_ID'))

    cookies_file = None
    while True:
        cookies_input = Prompt.ask(
            "[bold]Enter path to cookies file[/bold] [dim](optional, press Enter to skip)[/dim]",
            default="",
            show_default=False,
        ).strip()
        if not cookies_input:
            break
        ok, err = validate_cookies_path(cookies_input)
        if ok:
            cookies_file = cookies_input.strip().strip('"').strip("'")
            console.print(f"[green]✓ Cookies:[/green] {cookies_file}")
            break
        console.print(f"[red]✗ Invalid cookies path:[/red] {err}")
        retry = Confirm.ask("Try another path?", default=True)
        if not retry:
            console.print("[yellow]⚠ Continuing without cookies.[/yellow]")
            break

    console.print()
    downloader = YouTubeTelegramDownloader(cookies_file)
    uploader = TelegramUploader(bot_token, channel_id)

    # Main interactive loop: each iteration is one full single/playlist/batch session.
    # Cookies (above) are answered once per program run and reused across iterations.
    while True:
        try:
            run_session(downloader, uploader)
        except KeyboardInterrupt:
            console.print("\n[yellow]⚠ Current operation cancelled. Returning to mode menu.[/yellow]")
        except Exception as e:
            console.print(f"[red]✗ Unexpected error: {e}[/red]")

        if not prompt_continue():
            break

    console.print("[bold green]Done![/bold green]")


if __name__ == '__main__':
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        console.print("\n[yellow]⚠ Operation cancelled by user.[/yellow]")
        sys.exit(0)
