from typing import Optional, Dict, TypedDict, List, Union
from dataclasses import dataclass

class VideoFormat(TypedDict):
    format_id: str
    resolution: int
    fps: int
    ext: str
    size_mb: float

class AudioFormat(TypedDict):
    format_id: str
    bitrate: float
    ext: str

class VideoInfo(TypedDict):
    video_formats: Dict[str, str]
    audio_formats: Dict[str, str]
    title: str
    duration: int
    thumbnail: Optional[str]

@dataclass
class DownloadResult:
    video_path: str
    thumbnail_path: Optional[str]
    video_title: str
    duration: int
