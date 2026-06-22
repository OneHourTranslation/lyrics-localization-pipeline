"""
Musixmatch API diagnostic — run this first to confirm your key works
and to capture real response shapes.

Usage:
    python test_musixmatch.py YOUR_API_KEY

Tests against "Sunflower" by Post Malone (well-indexed, has synced lyrics
on paid plans). Prints full raw JSON for each endpoint so you can paste
it back for review.
"""
import json
import sys
import urllib.request

API_KEY = sys.argv[1] if len(sys.argv) > 1 else ""
BASE = "https://api.musixmatch.com/ws/1.1"

TEST_TITLE = "Sunflower"
TEST_ARTIST = "Post Malone"


def get(path: str, params: dict) -> dict:
    params["apikey"] = API_KEY
    qs = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
    url = f"{BASE}/{path}?{qs}"
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read())


import urllib.parse  # noqa: E402 (needed after get() definition)


def main() -> None:
    if not API_KEY:
        print("Usage: python test_musixmatch.py YOUR_API_KEY")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"1. track.search  —  '{TEST_TITLE}' by '{TEST_ARTIST}'")
    print("="*60)
    search_resp = get("track.search", {
        "q_track": TEST_TITLE,
        "q_artist": TEST_ARTIST,
        "s_track_rating": "desc",
        "page_size": "1",
        "f_has_lyrics": "1",
    })
    print(json.dumps(search_resp, indent=2))

    track_list = search_resp.get("message", {}).get("body", {}).get("track_list", [])
    if not track_list:
        print("\nNo tracks found — check your API key and try again.")
        return

    track = track_list[0]["track"]
    track_id = track["track_id"]
    print(f"\nFound: track_id={track_id}  has_subtitles={track.get('has_subtitles')}  has_lyrics={track.get('has_lyrics')}")

    print(f"\n{'='*60}")
    print(f"2. track.subtitle.get  —  track_id={track_id}")
    print("="*60)
    subtitle_resp = get("track.subtitle.get", {"track_id": track_id})
    print(json.dumps(subtitle_resp, indent=2))

    print(f"\n{'='*60}")
    print(f"3. track.lyrics.get  —  track_id={track_id}")
    print("="*60)
    lyrics_resp = get("track.lyrics.get", {"track_id": track_id})
    print(json.dumps(lyrics_resp, indent=2))


if __name__ == "__main__":
    main()
