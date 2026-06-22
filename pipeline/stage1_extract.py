"""
Stage 1: Download audio and extract metadata via yt-dlp.

Output folder: output/{Artist} - {Song Title}/
Can be rerun independently; skips songs where audio already exists.
"""
import asyncio
import logging

import yt_dlp

from config import settings
from models.song import SongResult
from utils.path_utils import song_dir, song_folder_name

logger = logging.getLogger(__name__)


def _extract_artist(info: dict) -> str:
    return (
        info.get("artist")
        or info.get("creator")
        or info.get("uploader")
        or "Unknown Artist"
    )


def _ydl_info_only(url: str) -> dict:
    ydl_opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=False)


def _ydl_download(url: str, out_dir: str) -> dict:
    """Blocking yt-dlp call — always run via run_in_executor."""
    ydl_opts = {
        "format": "bestaudio/best",
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": settings.audio_quality,
        }],
        "outtmpl": f"{out_dir}/audio.%(ext)s",
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=True)


def save_result(song: SongResult) -> None:
    d = song_dir(settings.output_dir, song.artist, song.title)
    d.mkdir(parents=True, exist_ok=True)
    (d / "song.json").write_text(song.model_dump_json(indent=2))


def load_all_results() -> list[SongResult]:
    results = []
    if settings.output_dir.exists():
        for json_path in sorted(settings.output_dir.glob("*/song.json")):
            try:
                results.append(SongResult.model_validate_json(json_path.read_text()))
            except Exception as exc:
                logger.warning(f"Could not load {json_path}: {exc}")
    return results


def _find_cached(video_id: str) -> SongResult | None:
    """Scan output dir for an existing result with this video_id."""
    for s in load_all_results():
        if s.video_id == video_id and s.stage1_done:
            return s
    return None


async def process_url(url: str) -> SongResult:
    url = url.strip()
    loop = asyncio.get_event_loop()

    try:
        info_only = await loop.run_in_executor(None, _ydl_info_only, url)
    except Exception as exc:
        logger.error(f"[stage1] metadata fetch failed {url}: {exc}")
        return SongResult(url=url, error=str(exc))

    video_id: str = info_only["id"]

    cached = _find_cached(video_id)
    if cached:
        logger.info(f"[stage1] skip (cached): [{video_id}]")
        return cached

    # Get artist/title early so we can build the output directory
    title: str = info_only.get("title", "Unknown Title")
    artist: str = _extract_artist(info_only)
    out_dir = song_dir(settings.output_dir, artist, title)
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"[stage1] downloading: {url}")
    try:
        info = await loop.run_in_executor(None, _ydl_download, url, str(out_dir))
    except Exception as exc:
        logger.error(f"[stage1] download failed {url}: {exc}")
        return SongResult(url=url, video_id=video_id, title=title, artist=artist, error=str(exc))

    duration: float | None = info.get("duration")
    audio_path = out_dir / "audio.mp3"

    song = SongResult(
        url=url,
        video_id=video_id,
        title=title,
        artist=artist,
        duration_s=duration,
        audio_path=str(audio_path),
        stage1_done=True,
    )

    save_result(song)
    logger.info(f"[stage1] done: '{title}' by '{artist}' [{video_id}]")
    return song


async def run_stage1(urls: list[str]) -> list[SongResult]:
    sem = asyncio.Semaphore(settings.max_concurrent_downloads)

    async def bounded(url: str) -> SongResult:
        async with sem:
            return await process_url(url)

    return list(await asyncio.gather(*[bounded(u) for u in urls]))
