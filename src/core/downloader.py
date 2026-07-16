import os
import shutil
import logging
from typing import Optional, Dict, List, Union
import yt_dlp

from src.models import ParsedVideoFormat, ParsedAudioFormat, VideoInfo, DownloadResult

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

    @staticmethod
    def check_js_runtime() -> bool:
        """Check if a supported JS runtime (node or deno) is installed."""
        return bool(shutil.which('node') or shutil.which('deno'))

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

        
        ydl_opts = self._base_opts(quiet=True, no_warnings=True)
        
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
                            'format_note': fmt.get('format_note', ''),
                        })
                    
                    # Audio-only streams
                    if acodec != 'none' and vcodec == 'none':
                        filesize = fmt.get('filesize') or fmt.get('filesize_approx', 0) or 0
                        size_mb = filesize / (1024 * 1024) if filesize else 0
                        raw_audio.append({
                            'format_id': fmt['format_id'],
                            'bitrate': fmt.get('abr', 0) or 0,
                            'ext': fmt.get('ext', '?'),
                            'acodec': acodec.split('.')[0],
                            'size_mb': round(size_mb, 1),
                            'format_note': fmt.get('format_note', ''),
                        })
                
                # Sort video: highest resolution first, then fps, preferred codec, and KNOWN size over unknown
                codec_priority = {'avc1': 0, 'h264': 0, 'av01': 1, 'vp9': 2, 'vp09': 2}
                video_formats = sorted(
                    raw_video,
                    key=lambda f: (f['resolution'], f['fps'], -codec_priority.get(f['vcodec'], 99), f['size_mb'] > 0, f['size_mb']),
                    reverse=True
                )
                
                # Sort audio: KNOWN bitrate first, then highest bitrate
                audio_formats = sorted(
                    raw_audio,
                    key=lambda f: (f['bitrate'] > 0, f['bitrate']),
                    reverse=True
                )
                
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
            quiet=True,
            no_warnings=True,
            noprogress=True,
            merge_output_format=container_format,
            concurrent_fragment_downloads=10,
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
        Uses flat extraction for instant detection.
        
        :param url: YouTube URL
        :return: True if playlist
        """
        ydl_opts = self._base_opts(quiet=True, no_warnings=True, extract_flat=True)
        
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

    @staticmethod
    def estimate_size(video_formats: list, audio_formats: list, video_format_id: str, audio_format_id: Optional[str] = None) -> float:
        """
        Estimate download size from already-fetched format data.
        No API call needed — uses size_mb from get_video_qualities().
        
        :param video_formats: List of parsed video formats
        :param audio_formats: List of parsed audio formats
        :param video_format_id: Selected video format ID
        :param audio_format_id: Selected audio format ID (optional)
        :return: Estimated size in MB (0 if unknown / not found)
        """
        total_mb = 0.0
        video_known = False
        for vf in video_formats:
            if vf['format_id'] == video_format_id:
                size = vf.get('size_mb', 0) or 0
                if size > 0:
                    total_mb += size
                    video_known = True
                break
        if audio_format_id:
            for af in audio_formats:
                if af['format_id'] == audio_format_id:
                    size = af.get('size_mb', 0) or 0
                    if size > 0:
                        total_mb += size
                    break
        # If video size is unknown, treat whole estimate as unknown
        if not video_known:
            return 0.0
        return total_mb

    @staticmethod
    def match_video_format(
        video_formats: List[ParsedVideoFormat],
        preferred: ParsedVideoFormat,
    ) -> Optional[ParsedVideoFormat]:
        """
        Pick the best video format matching a user preference without re-prompting.
        
        Priority:
          1. Same resolution + fps + codec
          2. Same resolution + fps (any codec)
          3. Same resolution (closest fps, preferred codec)
          4. Closest lower-or-equal resolution
          5. Best available (highest resolution)
        """
        if not video_formats:
            return None

        target_res = preferred['resolution']
        target_fps = preferred.get('fps', 0) or 0
        target_codec = preferred.get('vcodec', '')

        # 1 exact
        for vf in video_formats:
            if (vf['resolution'] == target_res
                    and (vf.get('fps', 0) or 0) == target_fps
                    and vf.get('vcodec') == target_codec):
                return vf

        # 2 same res + fps
        for vf in video_formats:
            if vf['resolution'] == target_res and (vf.get('fps', 0) or 0) == target_fps:
                return vf

        # 3 same res, closest fps then preferred codec
        same_res = [vf for vf in video_formats if vf['resolution'] == target_res]
        if same_res:
            same_res.sort(
                key=lambda f: (
                    abs((f.get('fps', 0) or 0) - target_fps),
                    0 if f.get('vcodec') == target_codec else 1,
                )
            )
            return same_res[0]

        # 4 closest lower-or-equal resolution; if none, closest higher
        lower = [vf for vf in video_formats if vf['resolution'] <= target_res]
        pool = lower if lower else video_formats
        pool = sorted(
            pool,
            key=lambda f: (
                -f['resolution'],
                abs((f.get('fps', 0) or 0) - target_fps),
                0 if f.get('vcodec') == target_codec else 1,
            )
        )
        return pool[0]

    @staticmethod
    def match_audio_format(
        audio_formats: List[ParsedAudioFormat],
        preferred: Optional[ParsedAudioFormat],
    ) -> Optional[ParsedAudioFormat]:
        """
        Pick the best audio format matching a user preference without re-prompting.
        
        Priority:
          1. Same bitrate + codec
          2. Same codec (closest bitrate)
          3. Closest bitrate
          4. Best available (highest bitrate)
        """
        if not audio_formats:
            return None
        if not preferred:
            return audio_formats[0]

        target_br = preferred.get('bitrate', 0) or 0
        target_codec = preferred.get('acodec', '')

        for af in audio_formats:
            if (af.get('bitrate', 0) or 0) == target_br and af.get('acodec') == target_codec:
                return af

        same_codec = [af for af in audio_formats if af.get('acodec') == target_codec]
        if same_codec:
            same_codec.sort(key=lambda f: abs((f.get('bitrate', 0) or 0) - target_br))
            return same_codec[0]

        sorted_by_br = sorted(
            audio_formats,
            key=lambda f: abs((f.get('bitrate', 0) or 0) - target_br)
        )
        return sorted_by_br[0]
