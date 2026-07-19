from typing import Optional, TypedDict, List
from dataclasses import dataclass

class ParsedVideoFormat(TypedDict):
    format_id: str
    resolution: int     # e.g. 1080
    fps: int            # e.g. 30
    ext: str            # e.g. "mp4"
    vcodec: str         # e.g. "avc1" or "vp9"
    size_mb: float      # estimated size, 0 if unknown
    format_note: str
    dynamic_range: str  # e.g. "SDR", "HDR10", "DV", "HLG"
    is_progressive: bool  # True if stream contains both video and audio

class ParsedAudioFormat(TypedDict):
    format_id: str
    bitrate: float      # kbps
    ext: str
    acodec: str         # e.g. "opus" or "mp4a"
    size_mb: float      # estimated size, 0 if unknown
    format_note: str

class VideoInfo(TypedDict):
    video_formats: List[ParsedVideoFormat]
    audio_formats: List[ParsedAudioFormat]
    title: str
    duration: int
    thumbnail: Optional[str]

@dataclass
class DownloadResult:
    video_path: str
    thumbnail_path: Optional[str]
    video_title: str
    duration: int

