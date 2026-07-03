import os
import shutil
import logging
from typing import Optional, Dict, List, Union
from dataclasses import dataclass
import yt_dlp

from src.models import VideoFormat, AudioFormat, ParsedVideoFormat, ParsedAudioFormat, VideoInfo, DownloadResult
from src.utils.validators import validate_youtube_url
from src.utils.helpers import convert_thumbnail

class YouTubeTelegramDownloader:
    def __init__(self, cookies_file: Optional[str] = None):
        """
        Initialize the downloader with optional cookies.
        
        :param cookies_file: Optional path to Netscape-format cookie file
        """
        self.cookies_file = None
        if cookies_file and os.path.exists(cookies_file):
            self.cookies_file = cookies_file
        elif cookies_file:
            logging.warning(f"Cookie file {cookies_file} not found")
        
        self.logger = logging.getLogger(__name__)

    def _base_opts(self, **extra) -> dict:
        """
        Build base yt-dlp options with cookies and JS runtime detection.
        """
        opts = {}
        if self.cookies_file:
            opts['cookiefile'] = self.cookies_file
        
        # Auto-detect JS runtime for YouTube EJS signature solving
        if shutil.which('deno'):
            opts['js_runtimes'] = {'deno': {}}
            opts['remote_components'] = ['ejs:npm']
        elif shutil.which('node'):
            opts['js_runtimes'] = {'node': {}}
        
        opts.update(extra)
        return opts

    def get_video_qualities(self, url: str) -> VideoInfo:
        """
        Fetch available video and audio qualities.
        
        Returns structured, grouped, and sorted format lists.
        Video formats are grouped by (resolution, fps) keeping the best codec
        per group, sorted descending by resolution then fps.
        Audio formats are sorted descending by bitrate.
        
        :param url: YouTube video URL
        :return: VideoInfo with available formats and metadata
        :raises ValueError: If URL is invalid
        :raises RuntimeError: If extraction fails
        """
        if not validate_youtube_url(url):
            raise ValueError(f"Invalid YouTube URL: {url}")
        
        ydl_opts = self._base_opts(quiet=True, no_warnings=False)
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                raw_video: List[ParsedVideoFormat] = []
                raw_audio: List[ParsedAudioFormat] = []
                
                for fmt in info.get('formats', []):
                    vcodec = fmt.get('vcodec', 'none')
                    acodec = fmt.get('acodec', 'none')
                    
                    # Video-only or video+audio streams
                    if vcodec != 'none':
                        resolution = fmt.get('height', 0)
                        if resolution == 0:
                            continue
                        fps = fmt.get('fps', 0) or 0
                        filesize = fmt.get('filesize') or fmt.get('filesize_approx', 0) or 0
                        size_mb = filesize / (1024 * 1024) if filesize else 0
                        raw_video.append({
                            'format_id': fmt['format_id'],
                            'resolution': resolution,
                            'fps': fps,
                            'ext': fmt.get('ext', '?'),
                            'vcodec': vcodec.split('.')[0],  # e.g. 'avc1.64001f' -> 'avc1'
                            'size_mb': round(size_mb, 1),
                        })
                    
                    # Audio-only streams
                    if acodec != 'none' and vcodec == 'none':
                        raw_audio.append({
                            'format_id': fmt['format_id'],
                            'bitrate': fmt.get('abr', 0) or 0,
                            'ext': fmt.get('ext', '?'),
                            'acodec': acodec.split('.')[0],
                        })
                
                # --- Group video formats by (resolution, fps) ---
                # Keep the best codec per group: prefer avc1/h264 (widest compatibility),
                # then largest size as a proxy for quality.
                groups: Dict[tuple, ParsedVideoFormat] = {}
                # Codec priority: lower = better (prefer h264/avc1 for compatibility)
                codec_priority = {'avc1': 0, 'h264': 0, 'av01': 1, 'vp9': 2, 'vp09': 2}
                
                for vf in raw_video:
                    key = (vf['resolution'], vf['fps'])
                    existing = groups.get(key)
                    if existing is None:
                        groups[key] = vf
                    else:
                        # Compare: prefer better codec priority, then larger size
                        new_prio = codec_priority.get(vf['vcodec'], 99)
                        old_prio = codec_priority.get(existing['vcodec'], 99)
                        if new_prio < old_prio or (new_prio == old_prio and vf['size_mb'] > existing['size_mb']):
                            groups[key] = vf
                
                # Sort: highest resolution first, then highest fps
                video_formats = sorted(
                    groups.values(),
                    key=lambda f: (f['resolution'], f['fps']),
                    reverse=True
                )
                
                # Sort audio: highest bitrate first
                audio_formats = sorted(
                    raw_audio,
                    key=lambda f: f['bitrate'],
                    reverse=True
                )
                # Deduplicate audio by bitrate (keep first = best codec naturally)
                seen_bitrates = set()
                deduped_audio: List[ParsedAudioFormat] = []
                for af in audio_formats:
                    br_key = round(af['bitrate'])
                    if br_key not in seen_bitrates:
                        seen_bitrates.add(br_key)
                        deduped_audio.append(af)
                audio_formats = deduped_audio
                
                if not video_formats:
                    raise RuntimeError(
                        "No video formats found. This usually means yt-dlp is outdated. "
                        "Run 'pip install -U yt-dlp' to update."
                    )
                
                return {
                    'video_formats': video_formats,
                    'audio_formats': audio_formats,
                    'title': info.get('title', 'Unknown Title'),
                    'duration': info.get('duration', 0),
                    'thumbnail': info.get('thumbnail')
                }
            
        except yt_dlp.utils.DownloadError as e:
            self.logger.error(f"Download error: {e}")
            raise RuntimeError(f"Failed to extract video info: {e}")
        except Exception as e:
            self.logger.error(f"Error fetching video qualities: {e}")
            raise RuntimeError(f"Unexpected error: {e}")

    def download_video(self, url: str, video_format: str, audio_format: Optional[str] = None, container_format: str = 'mp4', progress_hook=None) -> DownloadResult:
        """
        Download YouTube video with specified formats and container
        
        :param url: YouTube video URL
        :param video_format: Video format ID
        :param audio_format: Optional audio format ID
        :param container_format: Container format (mp4, mkv, webm)
        :param progress_hook: Optional callback for download progress (receives yt-dlp progress dict)
        :return: DownloadResult with path and metadata
        """
        if not validate_youtube_url(url):
            raise ValueError(f"Invalid YouTube URL: {url}")
        
        if not video_format:
            raise ValueError("Video format ID cannot be empty")
        
        valid_containers = ['mp4', 'mkv', 'webm']
        if container_format not in valid_containers:
            self.logger.warning(f"Invalid container format: {container_format}. Using mp4 instead.")
            container_format = 'mp4'
        
        ydl_opts = self._base_opts(
            format=f'{video_format}+{audio_format}' if audio_format else video_format,
            outtmpl='%(title)s.%(ext)s',
            writethumbnail=True,
            no_warnings=False,
            merge_output_format=container_format,
        )
        
        if progress_hook:
            ydl_opts['progress_hooks'] = [progress_hook]
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(url, download=True)
                video_filename = ydl.prepare_filename(info_dict)
                
                base_filename = video_filename.rsplit('.', 1)[0]
                video_filename = f"{base_filename}.{container_format}"
                
                if not os.path.exists(video_filename):
                    raise FileNotFoundError(f"Downloaded video file not found: {video_filename}")
                
                base_name = base_filename
                thumbnail_path = next(
                    (f"{base_name}.{ext}" for ext in ['webp', 'jpg', 'png'] 
                    if os.path.exists(f"{base_name}.{ext}"))
                , None)
                
                return DownloadResult(
                    video_path=video_filename,
                    thumbnail_path=thumbnail_path,
                    video_title=info_dict.get('title', os.path.splitext(os.path.basename(video_filename))[0]),
                    duration=info_dict.get('duration', 0)
                )
        
        except Exception as e:
            self.logger.error(f"Download failed: {e}")
            raise RuntimeError(f"Failed to download video: {e}")

    def is_playlist(self, url: str) -> bool:
        """
        Check if the URL is a YouTube playlist with more than one video.
        
        :param url: YouTube URL
        :return: True if playlist
        """
        if not validate_youtube_url(url):
            return False
        
        ydl_opts = self._base_opts(quiet=True, no_warnings=True)
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                entries = info.get('entries', [])
                return bool(entries and len(entries) > 1)
        except Exception:
            return False

    def get_playlist_entries(self, url: str) -> List[Dict[str, str]]:
        """
        Extract flat entries from a YouTube playlist.
        
        :param url: Playlist URL
        :return: List of {'title': str, 'url': str}
        :raises RuntimeError: If extraction fails
        """
        if not validate_youtube_url(url):
            raise ValueError(f"Invalid YouTube URL: {url}")
        
        ydl_opts = self._base_opts(
            quiet=True,
            no_warnings=True,
            extract_flat=True,  # Faster extraction without full video info
        )
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                entries = info.get('entries', [])
                if not entries:
                    raise ValueError("No entries found in the provided URL")
                
                playlist_entries = []
                for entry in entries:
                    if entry and entry.get('url') and entry.get('title'):
                        playlist_entries.append({
                            'title': entry['title'],
                            'url': entry['url']
                        })
                if not playlist_entries:
                    raise ValueError("No valid entries extracted from playlist")
                return playlist_entries
        except yt_dlp.utils.DownloadError as e:
            self.logger.error(f"Playlist extraction error: {e}")
            raise RuntimeError(f"Failed to extract playlist entries: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error extracting playlist: {e}")
            raise RuntimeError(f"Failed to extract playlist: {e}")

    def get_estimated_size(self, url: str, video_format: str, audio_format: Optional[str] = None, container_format: str = 'mp4') -> float:
        """
        Estimate the download size for specified formats in MB.
        
        :param url: Video URL
        :param video_format: Video format ID
        :param audio_format: Optional audio format ID
        :param container_format: Container (not used for estimation)
        :return: Estimated size in MB (approximate)
        """
        if not validate_youtube_url(url):
            raise ValueError(f"Invalid YouTube URL: {url}")
        
        format_spec = f'{video_format}+{audio_format}' if audio_format else video_format
        
        ydl_opts = self._base_opts(
            format=format_spec,
            quiet=True,
            no_warnings=True,
        )
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                total_size_bytes = 0
                for fmt in info.get('formats', []):
                    if fmt.get('format_id') == video_format:
                        total_size_bytes += fmt.get('filesize') or fmt.get('filesize_approx', 0)
                    if audio_format and fmt.get('format_id') == audio_format:
                        total_size_bytes += fmt.get('filesize') or fmt.get('filesize_approx', 0)
                
                return total_size_bytes / (1024 * 1024) if total_size_bytes > 0 else 0
        except Exception as e:
            self.logger.warning(f"Size estimation failed for {url}: {e}")
            return 0  # Don't skip if estimation fails
