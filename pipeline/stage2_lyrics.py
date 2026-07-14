"""
Stage 2: Lyrics lookup waterfall.

Sources tried in order, stopping at the first success:

  SYNCED LYRICS (→ SYNCED_CONVERT, direct SRT):
    1. lrclib.net      free, no key required
    2. Musixmatch      requires MUSIXMATCH_API_KEY (paid plan for synced)

  PLAIN LYRICS (→ FORCED_ALIGN, Aeneas alignment needed):
    3. lrclib.net      plain text, already fetched in step 1 — no extra call
    4. Genius          requires GENIUS_API_KEY (free at genius.com/api-clients)
    5. Musixmatch      plain text, already fetched in step 2 — no extra call

  FALLBACK:
    6. ->ASR  (Demucs + Deepgram, implemented in stage 4)

Sources 2, 4, 5 are skipped if the corresponding key is not set in .env.
"""
import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Optional

import httpx
import lyricsgenius

from config import settings
from models.song import LyricsRoute, LyricsStatus, SongResult, TimestampEntry
from pipeline.stage1_extract import load_all_results, save_result

logger = logging.getLogger(__name__)

# YouTube titles often contain "Artist - Song Title (Official Video) [4K]" etc.
# Strip that noise before passing to lyrics APIs.
_YT_NOISE = re.compile(
    r"\s*[\(\[].*?[\)\]]"           # (Official Video), [4K], (Director: ...)
    r"|\s*ft\..*$"                  # ft. Guest Artist
    r"|\s*feat\..*$"
    r"|\s*official\s*(video|audio|lyric.*)?$",
    re.IGNORECASE,
)
_ARTIST_PREFIX = re.compile(r"^[^-]+-\s*")  # "Artist - " prefix


def _clean_for_search(title: str, artist: str) -> tuple[str, str]:
    """Strip YouTube titling cruft so lyrics APIs get a clean song name."""
    clean = _YT_NOISE.sub("", title).strip(" -–—")
    # If title still starts with artist name, strip it ("Lykke Li - I Follow Rivers")
    if artist and clean.lower().startswith(artist.lower()):
        clean = clean[len(artist):].strip(" -–—")
    elif " - " in clean:
        # Generic "Something - Song Title" pattern
        clean = _ARTIST_PREFIX.sub("", clean).strip()
    return clean or title, artist


# ---------------------------------------------------------------------------
# Shared LRC parser
# ---------------------------------------------------------------------------

def _parse_lrc(lrc_body: str) -> list[TimestampEntry]:
    """
    LRC lines: [MM:SS.cc] or [MM:SS.ccc]
    End time = next line's start; last line gets +5 s.
    Blank lines (gaps) are dropped.
    """
    pattern = re.compile(r"\[(\d+):(\d{2})\.(\d{2,3})\](.*)")
    raw = []
    for line in lrc_body.splitlines():
        m = pattern.match(line.strip())
        if not m:
            continue
        mm, ss, frac, text = m.groups()
        ms = (
            int(mm) * 60_000
            + int(ss) * 1_000
            + (int(frac) * 10 if len(frac) == 2 else int(frac))
        )
        raw.append({"start_ms": ms, "text": text.strip()})

    result = []
    for i, entry in enumerate(raw):
        end_ms = raw[i + 1]["start_ms"] if i + 1 < len(raw) else entry["start_ms"] + 5_000
        if entry["text"]:
            result.append(TimestampEntry(
                start_ms=entry["start_ms"],
                end_ms=end_ms,
                text=entry["text"],
            ))
    return result


# ---------------------------------------------------------------------------
# Lookup result container
# ---------------------------------------------------------------------------

@dataclass
class LookupResult:
    source: str
    synced: list[TimestampEntry] | None = None
    plain: str | None = None
    duration_s: Optional[float] = None  # duration of the matched track, per the lyrics source


# ---------------------------------------------------------------------------
# Duration cross-check — catches "found lyrics for the wrong track/version"
# (radio edit vs album version, live version, wrong song entirely, etc.)
# ---------------------------------------------------------------------------

def _classify_duration_mismatch(yt_duration_s: Optional[float], source_duration_s: Optional[float]) -> Optional[str]:
    if not yt_duration_s or not source_duration_s:
        return None
    diff = abs(yt_duration_s - source_duration_s)
    if diff <= 3:
        return None
    if diff <= 10:
        return "low"
    if diff <= 30:
        return "medium"
    return "high"


# ---------------------------------------------------------------------------
# Source 1 & 3: lrclib.net
# ---------------------------------------------------------------------------

def _pick_best_hit(hits: list[dict], target_duration_s: Optional[float]) -> Optional[dict]:
    """lrclib's search endpoint can return several versions of a song (radio edit,
    album version, remix, live...). Blindly taking the first hit risks matching the
    wrong one. Prefer the hit whose duration is closest to the source video's, and
    break close ties in favor of a hit that actually has synced lyrics."""
    if not hits:
        return None
    if not target_duration_s:
        return hits[0]

    def score(hit: dict) -> tuple:
        diff = abs((hit.get("duration") or 0) - target_duration_s)
        has_synced = 0 if hit.get("syncedLyrics") else 1
        return (diff, has_synced)

    return min(hits, key=score)


async def _lrclib_lookup(client: httpx.AsyncClient, song: SongResult) -> Optional[LookupResult]:
    """
    One call returns both syncedLyrics (LRC) and plainLyrics.
    Tries exact duration match first, falls back to search.
    """
    params = {"track_name": song.title, "artist_name": song.artist}

    data = None

    # Exact match requires duration
    if song.duration_s:
        try:
            resp = await client.get(
                "https://lrclib.net/api/get",
                params={**params, "duration": str(int(song.duration_s))},
            )
            if resp.status_code == 200:
                data = resp.json()
        except Exception:
            pass

    # Search fallback
    if data is None:
        try:
            resp = await client.get("https://lrclib.net/api/search", params=params)
            if resp.status_code == 200:
                hits = resp.json()
                data = _pick_best_hit(hits, song.duration_s)
        except Exception as exc:
            logger.debug(f"lrclib error: {exc}")
            return None

    if data is None:
        return None

    if data.get("instrumental"):
        logger.debug(f"lrclib: instrumental track, no lyrics")
        return None

    synced_raw: str = data.get("syncedLyrics") or ""
    plain_raw: str = data.get("plainLyrics") or ""

    synced = _parse_lrc(synced_raw) if synced_raw else None
    plain = plain_raw.strip() or None

    if not synced and not plain:
        return None

    return LookupResult(source="lrclib", synced=synced, plain=plain, duration_s=data.get("duration"))


# ---------------------------------------------------------------------------
# Source 2 & 5: Musixmatch
# ---------------------------------------------------------------------------

_MM_BASE = "https://api.musixmatch.com/ws/1.1"
_FREE_TIER_NOTICE = re.compile(
    r"\*+\s*This Lyrics is NOT for Commercial use\s*\*+.*",
    re.DOTALL | re.IGNORECASE,
)


def _mm_ok(data: dict) -> bool:
    return data["message"]["header"]["status_code"] == 200


async def _musixmatch_lookup(client: httpx.AsyncClient, song: SongResult) -> Optional[LookupResult]:
    """Search track, then attempt subtitle (synced) and/or plain lyrics."""
    try:
        resp = await client.get(
            f"{_MM_BASE}/track.search",
            params={
                "q_track": song.title,
                "q_artist": song.artist,
                "apikey": settings.musixmatch_api_key,
                "s_track_rating": "desc",
                "page_size": "1",
                "f_has_lyrics": "1",
            },
        )
        resp.raise_for_status()
        data = resp.json()

        if not _mm_ok(data):
            return None

        track_list = data["message"]["body"].get("track_list", [])
        if not track_list:
            return None

        track = track_list[0]["track"]
        track_id = int(track["track_id"])
        song.musixmatch_track_id = track_id
        duration_s = track.get("track_length")

        synced = None
        plain = None

        if track.get("has_subtitles"):
            synced = await _mm_synced(client, track_id)

        if track.get("has_lyrics") and not synced:
            plain = await _mm_plain(client, track_id)

        if not synced and not plain:
            return None

        return LookupResult(source="musixmatch", synced=synced, plain=plain, duration_s=duration_s)

    except Exception as exc:
        logger.debug(f"Musixmatch error: {exc}")
        return None


async def _mm_synced(client: httpx.AsyncClient, track_id: int) -> Optional[list[TimestampEntry]]:
    try:
        resp = await client.get(
            f"{_MM_BASE}/track.subtitle.get",
            params={"track_id": str(track_id), "apikey": settings.musixmatch_api_key},
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        if not _mm_ok(data):
            return None
        body = data["message"]["body"].get("subtitle", {}).get("subtitle_body", "")
        entries = _parse_lrc(body) if body else []
        return entries or None
    except Exception:
        return None


async def _mm_plain(client: httpx.AsyncClient, track_id: int) -> Optional[str]:
    try:
        resp = await client.get(
            f"{_MM_BASE}/track.lyrics.get",
            params={"track_id": str(track_id), "apikey": settings.musixmatch_api_key},
        )
        if resp.status_code != 200:
            return None
        data = resp.json()
        if not _mm_ok(data):
            return None
        raw = data["message"]["body"].get("lyrics", {}).get("lyrics_body", "")
        cleaned = _FREE_TIER_NOTICE.sub("", raw).strip()
        return cleaned or None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Source 4: Genius (via lyricsgenius — handles scraping internally)
# ---------------------------------------------------------------------------

def _genius_fetch_blocking(title: str, artist: str) -> Optional[str]:
    """Synchronous lyricsgenius call — always run via run_in_executor."""
    genius = lyricsgenius.Genius(
        settings.genius_api_key,
        remove_section_headers=True,
        skip_non_songs=True,
        retries=2,
    )
    song = genius.search_song(title, artist)
    if not song:
        return None
    # lyricsgenius prepends "SongTitle Lyrics\n" — strip it
    lyrics = re.sub(r"^.*?\n", "", song.lyrics, count=1).strip()
    return lyrics or None


async def _genius_lookup(client: httpx.AsyncClient, song: SongResult) -> Optional[LookupResult]:
    try:
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(None, _genius_fetch_blocking, song.title, song.artist)
        return LookupResult(source="genius", plain=text) if text else None
    except Exception as exc:
        logger.debug(f"Genius error: {exc}")
        return None


# ---------------------------------------------------------------------------
# Waterfall
# ---------------------------------------------------------------------------

def _apply_duration_check(song: SongResult, result: LookupResult) -> None:
    song.lyrics_source_duration_s = result.duration_s
    song.duration_mismatch = _classify_duration_mismatch(song.duration_s, result.duration_s)
    if song.duration_mismatch:
        logger.warning(
            f"[stage2] duration mismatch ({song.duration_mismatch}): "
            f"YouTube {song.duration_s:.0f}s vs {result.source} {result.duration_s:.0f}s "
            f"— review needed [{song.video_id}]"
        )


def _apply_synced(song: SongResult, result: LookupResult) -> None:
    song.lyrics_status = LyricsStatus.SYNCED
    song.lyrics_source = result.source
    song.timestamps = result.synced
    song.timestamps_available = True
    song.lyrics = "\n".join(e.text for e in result.synced)
    song.routing = LyricsRoute.SYNCED_CONVERT
    _apply_duration_check(song, result)
    logger.info(
        f"[stage2] synced ({len(result.synced)} lines) via {result.source} "
        f"→ direct SRT  [{song.video_id}]"
    )


def _apply_plain(song: SongResult, result: LookupResult) -> None:
    song.lyrics_status = LyricsStatus.PLAIN
    song.lyrics_source = result.source
    song.lyrics = result.plain
    song.timestamps_available = False
    song.routing = LyricsRoute.FORCED_ALIGN
    _apply_duration_check(song, result)
    logger.info(
        f"[stage2] plain lyrics via {result.source} "
        f"-> forced alignment  [{song.video_id}]"
    )


async def _waterfall(client: httpx.AsyncClient, song: SongResult) -> None:
    clean_title, clean_artist = _clean_for_search(song.title, song.artist)
    if clean_title != song.title:
        logger.info(f"[stage2] cleaned title: '{song.title}' -> '{clean_title}'")

    # Build a search-friendly copy without mutating the stored song
    search = song.model_copy(update={"title": clean_title, "artist": clean_artist})

    _has_mm_key = bool(settings.musixmatch_api_key) and settings.musixmatch_api_key != "your_key_here"
    _has_genius_key = bool(settings.genius_api_key) and settings.genius_api_key != "your_key_here"

    # ── SYNCED PASS ──────────────────────────────────────────────────────────

    # 1. lrclib.net (free, always tried)
    lrc = await _lrclib_lookup(client, search)
    if lrc and lrc.synced:
        _apply_synced(song, lrc)
        return

    # 2. Musixmatch synced (optional)
    mm = None
    if _has_mm_key:
        mm = await _musixmatch_lookup(client, search)
        if mm and mm.synced:
            _apply_synced(song, mm)
            return

    # ── PLAIN PASS ───────────────────────────────────────────────────────────

    # 3. lrclib.net plain (already fetched above — no extra HTTP call)
    if lrc and lrc.plain:
        _apply_plain(song, lrc)
        return

    # 4. Genius plain (optional)
    if _has_genius_key:
        genius = await _genius_lookup(client, search)
        if genius and genius.plain:
            _apply_plain(song, genius)
            return

    # 5. Musixmatch plain (already fetched above — no extra HTTP call)
    if mm and mm.plain:
        _apply_plain(song, mm)
        return

    # ── FALLBACK ─────────────────────────────────────────────────────────────

    song.lyrics_status = LyricsStatus.NOT_FOUND
    song.routing = LyricsRoute.ASR
    logger.info(f"[stage2] no lyrics found anywhere -> ASR  [{song.video_id}]")


async def process_song(client: httpx.AsyncClient, song: SongResult) -> SongResult:
    logger.info(f"[stage2] '{song.title}' by '{song.artist}'")
    try:
        await _waterfall(client, song)
    except Exception as exc:
        logger.error(f"[stage2] unexpected error [{song.video_id}]: {exc}")
        song.lyrics_status = LyricsStatus.ERROR
        song.routing = LyricsRoute.ASR
        song.error = str(exc)
    finally:
        song.stage2_done = True
        save_result(song)
    return song


async def run_stage2(songs: list[SongResult]) -> list[SongResult]:
    sem = asyncio.Semaphore(settings.max_concurrent_api_calls)

    async with httpx.AsyncClient(timeout=30.0) as client:
        async def bounded(song: SongResult) -> SongResult:
            async with sem:
                return await process_song(client, song)

        return list(await asyncio.gather(*[bounded(s) for s in songs]))
