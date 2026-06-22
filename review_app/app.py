"""
FastAPI review server for the lyrics localization pipeline.
Start with: python review.py serve
"""
import json
import re
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

_HERE = Path(__file__).parent
TEMPLATES_DIR = _HERE / "templates"
OUTPUT_DIR = Path("output")

app = FastAPI(title="Lyrics Review Tool", docs_url=None, redoc_url=None)
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ── data helpers ─────────────────────────────────────────────────────────────

def _all_songs() -> list[dict]:
    songs = []
    for p in sorted(OUTPUT_DIR.glob("*/song.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            data["_folder"] = p.parent.name
            data["_json_path"] = str(p)
            review = data.get("review") or {}
            data["_s2"] = review.get("stage2", "pending" if data.get("stage2_done") else "na")
            data["_s3"] = review.get("stage3", "pending" if data.get("stage3_done") else "na")
            songs.append(data)
        except Exception:
            pass
    return songs


def _find_song(video_id: str) -> tuple[dict | None, Path | None]:
    for p in OUTPUT_DIR.glob("*/song.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if data.get("video_id") == video_id:
                data["_folder"] = p.parent.name
                return data, p
        except Exception:
            pass
    return None, None


def _save_song(data: dict, path: Path) -> None:
    clean = {k: v for k, v in data.items() if not k.startswith("_")}
    path.write_text(json.dumps(clean, indent=2, ensure_ascii=False), encoding="utf-8")


# ── SRT helpers ───────────────────────────────────────────────────────────────

def _ts_to_ms(ts: str) -> int:
    h, m, rest = ts.split(":")
    s, ms = rest.split(",")
    return int(h) * 3_600_000 + int(m) * 60_000 + int(s) * 1_000 + int(ms)


def _parse_srt(content: str) -> list[dict]:
    blocks = []
    for raw in re.split(r"\n\s*\n", content.strip()):
        raw = raw.strip()
        if not raw:
            continue
        lines = raw.split("\n")
        if len(lines) < 3:
            continue
        try:
            idx = int(lines[0].strip())
            m = re.match(r"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})", lines[1].strip())
            if not m:
                continue
            start, end = m.group(1), m.group(2)
            blocks.append({
                "index": idx,
                "start": start,
                "end": end,
                "text": "\n".join(lines[2:]).strip(),
                "start_ms": _ts_to_ms(start),
                "end_ms": _ts_to_ms(end),
            })
        except (ValueError, IndexError):
            continue
    return blocks


def _blocks_to_srt(blocks: list[dict]) -> str:
    return "\n".join(
        f"{i}\n{b['start']} --> {b['end']}\n{b['text']}\n"
        for i, b in enumerate(blocks, 1)
    )


# ── routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(request, "dashboard.html", {"songs": _all_songs()})


@app.get("/review/{video_id}", response_class=HTMLResponse)
async def review_page(request: Request, video_id: str, stage: int = 2):
    song, _ = _find_song(video_id)
    if not song:
        raise HTTPException(404, "Song not found")

    review = song.get("review") or {}
    srt_blocks: list[dict] = []

    if stage == 3 and song.get("en_srt_path"):
        srt_path = Path(song["en_srt_path"])
        if srt_path.exists():
            srt_blocks = _parse_srt(srt_path.read_text(encoding="utf-8"))

    return templates.TemplateResponse(request, "review.html", {
        "song": song,
        "stage": stage,
        "review": review,
        "status": review.get(f"stage{stage}", "pending"),
        "srt_blocks": srt_blocks,
    })


@app.get("/audio/{video_id}")
async def serve_audio(video_id: str):
    song, _ = _find_song(video_id)
    if not song:
        raise HTTPException(404)
    path = Path(song.get("audio_path", ""))
    if not path.exists():
        raise HTTPException(404, "Audio file missing")
    return FileResponse(str(path), media_type="audio/mpeg")


@app.post("/review/{video_id}/save")
async def save_edits(request: Request, video_id: str, stage: int = Form(...)):
    song, json_path = _find_song(video_id)
    if not song:
        raise HTTPException(404)

    form = await request.form()

    if stage == 2:
        song["lyrics"] = form.get("lyrics", "")

    elif stage == 3:
        blocks, i = [], 1
        while f"text_{i}" in form:
            blocks.append({
                "start": form.get(f"start_{i}", ""),
                "end":   form.get(f"end_{i}",   ""),
                "text":  form.get(f"text_{i}",  ""),
            })
            i += 1
        if blocks and song.get("en_srt_path"):
            Path(song["en_srt_path"]).write_text(_blocks_to_srt(blocks), encoding="utf-8")

    review = song.get("review") or {}
    review[f"stage{stage}"] = "fixed"
    song["review"] = review
    _save_song(song, json_path)
    return RedirectResponse(f"/review/{video_id}?stage={stage}&saved=1", status_code=303)


@app.post("/review/{video_id}/approve")
async def approve(video_id: str, stage: int = Form(...)):
    song, json_path = _find_song(video_id)
    if not song:
        raise HTTPException(404)
    review = song.get("review") or {}
    review[f"stage{stage}"] = "approved"
    song["review"] = review
    _save_song(song, json_path)
    return RedirectResponse("/?msg=approved", status_code=303)


@app.post("/review/{video_id}/reject")
async def reject(video_id: str, stage: int = Form(...), reason: str = Form("")):
    song, json_path = _find_song(video_id)
    if not song:
        raise HTTPException(404)

    review = song.get("review") or {}
    review[f"stage{stage}"] = "rejected"
    if reason.strip():
        review[f"stage{stage}_reason"] = reason.strip()
    song["review"] = review

    if stage == 2:
        source = song.get("lyrics_source")
        if source:
            rs = song.get("rejected_sources") or []
            if source not in rs:
                rs.append(source)
            song["rejected_sources"] = rs
        song["stage2_done"] = False
        song["stage3_done"] = False

    _save_song(song, json_path)
    return RedirectResponse("/?msg=rejected", status_code=303)
