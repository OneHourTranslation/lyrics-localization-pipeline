from enum import Enum
from typing import Optional
from pydantic import BaseModel


class LyricsStatus(str, Enum):
    SYNCED = "synced"
    PLAIN = "plain"
    NOT_FOUND = "not_found"
    ERROR = "error"


class LyricsRoute(str, Enum):
    SYNCED_CONVERT = "synced_convert"   # has timestamps → direct SRT
    FORCED_ALIGN = "forced_align"        # plain text → Aeneas
    ASR = "asr"                          # nothing found → Demucs + Deepgram


class TimestampEntry(BaseModel):
    start_ms: int
    end_ms: int
    text: str


class SongResult(BaseModel):
    url: str
    video_id: str = ""
    title: str = ""
    artist: str = ""
    duration_s: Optional[float] = None
    audio_path: Optional[str] = None

    lyrics_status: Optional[LyricsStatus] = None
    lyrics_source: Optional[str] = None        # "lrclib" | "genius" | "musixmatch"
    musixmatch_track_id: Optional[int] = None  # set if Musixmatch was queried
    lyrics: Optional[str] = None
    timestamps: Optional[list[TimestampEntry]] = None
    timestamps_available: bool = False

    routing: Optional[LyricsRoute] = None
    stage1_done: bool = False
    stage2_done: bool = False
    stage3_done: bool = False
    en_srt_path: Optional[str] = None
    rejected_sources: list[str] = []
    review: dict[str, str] = {}
    error: Optional[str] = None
