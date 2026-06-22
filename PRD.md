# PRD — Automated Lyrics Localization Pipeline

## Overview

An automated pipeline that takes YouTube music video URLs as input and produces timestamped subtitle files (SRT) in English and 6 target languages. The pipeline is designed to process thousands of songs in batch, with human validation checkpoints at each stage where automated results cannot be fully trusted.

---

## Problem

Localizing song lyrics for international audiences requires:
1. Finding accurate, time-synced lyrics
2. Translating them into multiple languages
3. Mapping the original timestamps to each translation

Doing this manually per song is expensive and slow. This pipeline automates every step — but several steps (forced alignment, ASR, translation) produce results that need human review before proceeding.

---

## Goals

- Accept a plain text file of YouTube URLs (one per line) as the only required input
- Produce one English SRT and six localized SRTs per song
- Handle the full quality spectrum: synced lyrics → plain lyrics → ASR fallback
- Be rerunnable — each stage saves its output so failed or rejected songs can be reprocessed without re-running the whole pipeline
- Include human review steps wherever automated output is unreliable
- Process thousands of URLs efficiently using async concurrency

---

## Non-Goals

- Video editing or muxing subtitles into video files
- Building a public-facing UI (the review tool is internal/local only)
- Real-time / streaming processing
- Supporting non-music audio (podcasts, speeches)

---

## Validation Model

Each song in `song.json` carries a `review_status` field per stage:

| Value | Meaning |
|---|---|
| `pending` | Stage ran, not yet reviewed |
| `approved` | Human confirmed output is correct |
| `fixed` | Human edited the output, approved after fix |
| `rejected` | Output is unusable, song needs to be reprocessed |

The pipeline only advances a song to the next stage if its current stage is `approved` or `fixed`. Songs marked `rejected` are requeued for reprocessing (or escalated to a harder fallback path).

Review is done by opening the relevant file (SRT, lyrics text, or translation), editing if needed, then running:
```bash
python review.py approve "Artist - Song Title" --stage 2
python review.py reject  "Artist - Song Title" --stage 2 --reason "wrong song matched"
```

---

## Pipeline Architecture

Each stage is independently runnable via `python main.py urls.txt --stage N`.

---

### Stage 1 — Audio Extraction
**Input:** YouTube URL  
**Output:** `output/Artist - Song Title/audio.mp3`, `song.json`  
**Validation required:** No — download either succeeds or fails with a clear error.

- Downloads audio at 128kbps MP3 using yt-dlp
- Extracts title, artist, duration from video metadata
- Names the output folder `Artist - Song Title` (strips YouTube noise like "Official Video", "ft. Guest")
- Skips re-download if audio already exists on disk (cache by video ID)
- **Failure modes:** 403 Forbidden (age-restricted or region-locked video), private video, deleted video → logged and skipped

---

### Stage 2 — Lyrics Lookup (Waterfall)
**Input:** `song.json` with title + artist  
**Output:** Updated `song.json` with lyrics, timestamps (if available), source, and routing decision  
**Validation required:** Yes — wrong song can be matched, lyrics can be truncated or missing verses.

Tries sources in order, stops at first success:

| Priority | Source | Type | Requires |
|---|---|---|---|
| 1 | lrclib.net | Synced (LRC) | No key |
| 2 | Musixmatch | Synced (LRC) | Paid API key |
| 3 | lrclib.net | Plain text | No key (same call) |
| 4 | Genius | Plain text | Free API key |
| 5 | Musixmatch | Plain text | Paid API key (same call) |
| 6 | — | Not found → ASR route | — |

Each song is tagged with:
- `lyrics_source` — which service found the lyrics
- `lyrics_status` — `synced` / `plain` / `not_found` / `error`
- `routing` — which downstream path to take

**What to review:** Open `song.json` and check the `lyrics` field. Verify it matches the actual song, is complete, and has no truncation notices (Musixmatch free tier clips at 30%). If wrong: edit the lyrics directly and mark `fixed`, or reject and let the pipeline try the next source.

**Failure modes:** Wrong song matched (title ambiguity), lyrics truncated (API tier limit), lyrics in wrong language, instrumental track flagged as having lyrics.

---

### Stage 3a — English SRT (Synced Convert)
**Input:** `song.json` with `routing = synced_convert`  
**Output:** `output/Artist - Song Title/en.srt`  
**Validation required:** Light — direct conversion is mechanical, but timing can be off if the LRC source was for a different version of the song.

Converts LRC timestamp entries directly to SRT format.

**What to review:** Open `en.srt` and spot-check a few timestamps against the audio (play in VLC). Check that lyrics start and end at the right moments. Minor timing fixes can be made directly in the SRT file.

**Failure modes:** LRC was for a different album version or live recording (different timing), LRC timestamps shifted by a constant offset, missing intro/outro lines.

---

### Stage 3b — Forced Alignment *(not yet built)*
**Input:** `song.json` with `routing = forced_align` + `audio.mp3`  
**Output:** `en.srt` with timestamps derived from alignment  
**Validation required:** Yes — Aeneas alignment is unreliable on songs with heavy production, background vocals, or non-standard phrasing.

Uses Aeneas to align plain lyrics text against the audio and generate timestamps.

**What to review:** Play the SRT against the audio in VLC. Forced alignment commonly drifts on choruses and bridges. Expect to manually correct 20–40% of timestamps on complex songs.

**Failure modes:** Aeneas crashes on certain audio formats, alignment drifts mid-song, repeated sections (chorus) confuse the aligner.

---

### Stage 4 — ASR Fallback *(not yet built)*
**Input:** `song.json` with `routing = asr` + `audio.mp3`  
**Output:** `en.srt` generated from speech recognition  
**Validation required:** Yes, heavily — ASR on music is noisy. Expect word errors, missed lines, and hallucinated text. Every ASR output must be human-reviewed and corrected before proceeding.

- Separates vocals from music using Demucs
- Runs Deepgram ASR on the isolated vocal track
- Produces a timestamped transcript as a draft SRT

**What to review:** Treat ASR output as a first draft only. Correct lyrics against a known source (manual search, official release, etc.) and adjust timestamps where needed. Mark `fixed` only when lyrics and timing are both verified.

**Failure modes:** Heavily produced vocals surviving Demucs separation, non-English lyrics misidentified, homophones and slang misheard, backing vocals transcribed as lead vocal.

---

### Stage 5 — Translation *(not yet built)*
**Input:** `en.srt`  
**Output:** One draft translated SRT per target language  
**Validation required:** Yes — machine translation handles literal meaning but loses rhyme, meter, idiom, and cultural references. All translations need native-speaker review.

- Translates each subtitle line via DeepL API
- Preserves subtitle boundaries (does not merge or split lines)
- Target languages: TBD (6 languages to be confirmed)

**What to review:** Each translated SRT should be reviewed by a native speaker or professional translator. Key concerns: lines that are too long to read in the allotted time, idioms that translated literally but sound unnatural, culturally specific references. Corrections are made directly in the translated SRT file.

**Failure modes:** DeepL splits a multi-part phrase across subtitle boundaries, translating each fragment out of context. Some languages produce significantly longer text than English, causing subtitles to overflow their display window.

---

### Stage 6 — Localized SRT Output *(not yet built)*
**Input:** Approved English timestamps + approved translated text  
**Output:** `{lang_code}.srt` per language  
**Validation required:** Light — final check that timestamps are preserved correctly and files are well-formed.

- Maps English timestamps directly to translated lines
- Writes standard SRT files for each language
- Final output: `en.srt`, `{lang1}.srt` … `{lang6}.srt` per song

**What to review:** Open each localized SRT in a player and confirm timing feels natural for the translated text. Reading speed varies by language — some lines may need the display time extended manually.

---

## Output Structure

```
output/
└── Artist - Song Title/
    ├── audio.mp3
    ├── song.json        ← full metadata + pipeline state + review status
    ├── en.srt           ← English subtitles (approved before translation)
    ├── fr.srt           ← French
    ├── de.srt           ← German
    └── ...              ← one file per target language
```

---

## song.json Schema

```json
{
  "url": "https://youtube.com/watch?v=...",
  "video_id": "abc123",
  "title": "Song Title (Official Video)",
  "artist": "Artist Name",
  "duration_s": 214.0,
  "audio_path": "output/Artist - Song Title/audio.mp3",
  "lyrics_status": "synced",
  "lyrics_source": "lrclib",
  "lyrics": "full lyrics text",
  "timestamps": [
    { "start_ms": 8740, "end_ms": 11920, "text": "First line" }
  ],
  "timestamps_available": true,
  "routing": "synced_convert",
  "stage1_done": true,
  "stage2_done": true,
  "stage3_done": true,
  "en_srt_path": "output/Artist - Song Title/en.srt",
  "review": {
    "stage2": "approved",
    "stage3": "pending",
    "stage5_fr": "fixed",
    "stage5_de": "pending"
  },
  "error": null
}
```

---

## API Keys & Configuration

Configured via `.env` file. All lyrics source keys are optional — the pipeline uses whichever are available.

| Variable | Required | Purpose |
|---|---|---|
| `GENIUS_API_KEY` | Optional | Genius plain lyrics fallback |
| `MUSIXMATCH_API_KEY` | Optional | Synced + plain lyrics (paid plan) |
| `DEEPGRAM_API_KEY` | Optional | ASR on isolated vocals (stage 4) |
| `DEEPL_API_KEY` | Optional | Translation into 6 languages (stage 5) |

lrclib.net requires no key and is always tried first.

---

## CLI Usage

```bash
# Pipeline
python main.py urls.txt              # run all implemented stages
python main.py urls.txt --stage 1    # download audio only
python main.py urls.txt --stage 2    # re-run lyrics lookup from cached results
python main.py urls.txt --stage 3    # re-run SRT generation from cached results
python main.py urls.txt --verbose    # enable DEBUG logging

# Review tool
python review.py serve               # start web review tool at http://localhost:8080
python review.py serve --port 9000   # custom port
python review.py status              # show pending review queue in terminal
python review.py approve "Artist - Song Title" --stage 2
python review.py reject  "Artist - Song Title" --stage 2 --reason "wrong song matched"
```

---

## Review Web Tool

A local FastAPI server that lets reviewers validate each pipeline stage in the browser.

**Start:** `python review.py serve` from the project folder.  
Opens at `http://localhost:8080`. Share the Network URL printed at startup with collaborators on the same Wi-Fi. For remote access: `ngrok http 8080`.

### Dashboard
Table of all songs with colour-coded status badges per stage (pending / approved / fixed / rejected). Click **Lyrics** or **SRT timing** to open the review page.

### Stage 2 — Lyrics review
- Editable textarea with the full lyrics text
- **Save Changes** → writes back to `song.json`, marks stage as `fixed`
- **Approve** → marks `approved`, returns to dashboard
- **Reject** → modal for optional reason; flags current source in `rejected_sources`; clears `stage2_done` so the next `--stage 2` run skips it and tries the next waterfall source

### Stage 3 — English SRT review
- HTML5 audio player (streamed from `audio.mp3`)
- Each subtitle block shows editable start/end timestamps (`HH:MM:SS,mmm`) + editable text
- Blocks auto-highlight and auto-scroll as the audio plays

**Playback controls bar** (above the subtitle list):
- **Full song / One segment toggle** — Full song plays straight through; One segment plays only the clicked line then stops automatically, useful for checking a single tricky line repeatedly
- **Play / Pause button** — visible at all times, no need to reach the native browser audio controls

**▶ / ● seek button on each block** — dual-mode depending on audio state:
- Audio *paused*: click ▶ → seeks to that line's start and plays (One segment mode will stop at the line's end)
- Audio *playing*: buttons turn orange ●; click ● the instant you hear a line start → snaps that line's `start` timestamp and the previous line's `end` timestamp to the current playback position simultaneously; both inputs flash green to confirm

- **Save Changes** → writes all edited timestamps and text back to `en.srt`, marks stage as `fixed`
- **Approve / Reject** work the same as stage 2

---

## Tech Stack

| Component | Library |
|---|---|
| Audio download | yt-dlp |
| Async HTTP | httpx |
| Lyrics (synced) | lrclib.net API |
| Lyrics (plain fallback) | lyricsgenius |
| Forced alignment | Aeneas *(pending)* |
| Vocal separation | Demucs *(pending)* |
| ASR | Deepgram *(pending)* |
| Translation | DeepL *(pending)* |
| Data models | Pydantic v2 |
| Config | pydantic-settings + python-dotenv |
| Review web server | FastAPI + Jinja2 + uvicorn |

---

## Current Status

| Stage | Status |
|---|---|
| Stage 1 — Audio extraction | ✅ Complete |
| Stage 2 — Lyrics waterfall | ✅ Complete |
| Stage 3a — English SRT (synced) | ✅ Complete |
| Stage 3b — Forced alignment (Aeneas) | ⬜ Not started |
| Stage 4 — ASR (Demucs + Deepgram) | ⬜ Not started |
| Stage 5 — Translation (DeepL) | ⬜ Not started |
| Stage 6 — Localized SRT output | ⬜ Not started |
| Review web tool + CLI (`review.py`) | ✅ Complete |

Tested on 3 songs — all received synced lyrics from lrclib.net and produced valid `en.srt` files.
