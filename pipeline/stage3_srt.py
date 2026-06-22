"""
Stage 3: Generate English SRT from synced timestamps.

Only processes songs with routing=SYNCED_CONVERT.
Songs on FORCED_ALIGN or ASR routes are skipped here and handled later.
"""
import logging

from config import settings
from models.song import LyricsRoute, SongResult, TimestampEntry
from pipeline.stage1_extract import save_result
from utils.path_utils import song_dir

logger = logging.getLogger(__name__)


def ms_to_srt(ms: int) -> str:
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, millis = divmod(rem, 1_000)
    return f"{h:02d}:{m:02d}:{s:02d},{millis:03d}"


def timestamps_to_srt(entries: list[TimestampEntry]) -> str:
    blocks = []
    for i, e in enumerate(entries, 1):
        blocks.append(f"{i}\n{ms_to_srt(e.start_ms)} --> {ms_to_srt(e.end_ms)}\n{e.text}\n")
    return "\n".join(blocks)


def process_song(song: SongResult) -> SongResult:
    if song.routing != LyricsRoute.SYNCED_CONVERT:
        logger.info(f"[stage3] skip (routing={song.routing}) [{song.video_id}]")
        return song

    if not song.timestamps:
        logger.warning(f"[stage3] no timestamps to convert [{song.video_id}]")
        return song

    srt_content = timestamps_to_srt(song.timestamps)
    srt_path = song_dir(settings.output_dir, song.artist, song.title) / "en.srt"
    srt_path.write_text(srt_content, encoding="utf-8")

    song.en_srt_path = str(srt_path)
    song.stage3_done = True
    save_result(song)
    logger.info(f"[stage3] {len(song.timestamps)} lines -> en.srt  [{song.video_id}]")
    return song


async def run_stage3(songs: list[SongResult]) -> list[SongResult]:
    return [process_song(s) for s in songs]
