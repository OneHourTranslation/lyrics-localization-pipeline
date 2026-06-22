import re
from pathlib import Path

_YT_NOISE = re.compile(
    r"\s*[\(\[].*?[\)\]]"
    r"|\s*ft\..*$"
    r"|\s*feat\..*$"
    r"|\s*official\s*(video|audio|lyric.*)?$",
    re.IGNORECASE,
)
_ARTIST_PREFIX = re.compile(r"^[^-]+-\s*")
_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def clean_song_title(title: str, artist: str = "") -> str:
    t = _YT_NOISE.sub("", title).strip(" -–—")
    if artist and t.lower().startswith(artist.lower()):
        t = t[len(artist):].strip(" -–—")
    elif " - " in t:
        t = _ARTIST_PREFIX.sub("", t).strip()
    return t or title


def song_folder_name(artist: str, title: str) -> str:
    """Return a clean, filesystem-safe folder name: 'Artist - Song Title'."""
    clean = clean_song_title(title, artist)
    name = f"{artist} - {clean}" if artist and artist != "Unknown Artist" else clean
    name = _UNSAFE_CHARS.sub("", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:120] or "unknown"


def song_dir(output_root: Path, artist: str, title: str) -> Path:
    return output_root / song_folder_name(artist, title)
