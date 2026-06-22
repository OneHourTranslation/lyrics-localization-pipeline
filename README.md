# Lyrics Localization Pipeline

Automated pipeline that takes YouTube music video URLs and produces timestamped SRT subtitle files in English and multiple target languages. Includes a browser-based review tool so non-technical team members can validate and correct output at each stage.

---

## What it does

| Stage | What happens |
|---|---|
| 1 — Audio extraction | Downloads audio from YouTube as MP3 via yt-dlp |
| 2 — Lyrics lookup | Fetches synced or plain lyrics (lrclib → Genius → Musixmatch waterfall) |
| 3 — English SRT | Converts synced timestamps to SRT format |
| 3b — Forced alignment | *(pending)* Aligns plain lyrics to audio using Aeneas |
| 4 — ASR fallback | *(pending)* Vocal separation + speech recognition via Demucs + Deepgram |
| 5 — Translation | *(pending)* Translates English SRT to target languages via DeepL |
| Review | Browser tool to validate and fix output at each stage |

---

## Prerequisites

**Python 3.11+** — [python.org/downloads](https://www.python.org/downloads/)

**FFmpeg** — required by yt-dlp for audio conversion

- **Windows:** `winget install ffmpeg` or download from [ffmpeg.org](https://ffmpeg.org/download.html) and add to PATH
- **macOS:** `brew install ffmpeg`
- **Linux:** `sudo apt install ffmpeg` (Ubuntu/Debian) or `sudo dnf install ffmpeg` (Fedora)

---

## Setup

```bash
# 1. Clone the repo
git clone <repo-url>
cd <repo-folder>

# 2. Create and activate a virtual environment (recommended)
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure API keys
cp .env.example .env
# Open .env and fill in the keys you have (all are optional — see notes below)
```

### API keys

| Key | Where to get it | Required? |
|---|---|---|
| `GENIUS_API_KEY` | [genius.com/api-clients](https://genius.com/api-clients) — free | Optional (plain lyrics fallback) |
| `MUSIXMATCH_API_KEY` | musixmatch.com — paid plan | Optional (synced lyrics) |
| `DEEPGRAM_API_KEY` | deepgram.com | Optional (ASR stage, not yet built) |
| `DEEPL_API_KEY` | deepl.com | Optional (translation stage, not yet built) |

lrclib.net is always tried first and needs no key.

---

## Running the pipeline

Create a plain text file with one YouTube URL per line (lines starting with `#` are ignored):

```
https://www.youtube.com/watch?v=...
https://www.youtube.com/watch?v=...
# this line is a comment
```

```bash
# Run all implemented stages (1–3)
python main.py urls.txt

# Run a single stage only
python main.py urls.txt --stage 1   # audio only
python main.py urls.txt --stage 2   # lyrics only (requires stage 1 output)
python main.py urls.txt --stage 3   # SRT only (requires stage 2 output)

# Verbose logging
python main.py urls.txt --verbose
```

Output is written to `output/Artist - Song Title/`:

```
output/
└── Lykke Li - I Follow Rivers/
    ├── audio.mp3
    ├── song.json      ← full metadata + pipeline state + review status
    └── en.srt         ← English subtitles
```

---

## Review tool

A local web app for validating and correcting pipeline output. Works in any browser.

```bash
python review.py serve
# Opens at http://localhost:8080
```

Share the **Network URL** printed at startup with colleagues on the same Wi-Fi.  
For remote access: `ngrok http 8080`

### Dashboard
Overview of all processed songs with colour-coded review status per stage.

### Stage 2 — Lyrics review
Edit the lyrics text, then Approve or Reject. Rejecting flags the current source so the next pipeline run automatically tries the next one in the waterfall.

### Stage 3 — SRT timing review
Audio player + editable subtitle blocks.

- **Full song / One segment toggle** — Full song plays straight through; One segment plays only the clicked line then stops
- **Play / Pause button** — always visible
- **▶ button (audio paused)** — seeks to that line and plays
- **● button (audio playing)** — snaps that line's start timestamp and the previous line's end timestamp to the current playback position (live retiming)
- **Save Changes** → writes back to `en.srt`

### CLI shortcuts

```bash
python review.py status                                          # show review queue
python review.py approve "Lykke Li - I Follow Rivers" --stage 2
python review.py reject  "Lykke Li - I Follow Rivers" --stage 2 --reason "wrong song"
```

---

## Tech stack

| Component | Library |
|---|---|
| Audio download | yt-dlp |
| Async HTTP | httpx |
| Lyrics (synced) | lrclib.net (no key needed) |
| Lyrics (plain) | lyricsgenius |
| Data models | Pydantic v2 |
| Config | pydantic-settings |
| Review web server | FastAPI + Jinja2 + uvicorn |

---

## Contributing

1. Never commit `.env` — it contains real API keys
2. Never commit the `output/` folder — it contains client audio and lyrics
3. Test with at least one synced and one plain-lyrics song before opening a PR
