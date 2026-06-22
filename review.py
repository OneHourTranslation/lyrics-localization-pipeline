"""
Review tool — web server + CLI for the lyrics localization pipeline.

Usage:
  python review.py serve [--host 0.0.0.0] [--port 8080]
  python review.py status
  python review.py approve "Artist - Song Title" --stage 2
  python review.py reject  "Artist - Song Title" --stage 2 [--reason "..."]
"""
import argparse
import json
import sys
from pathlib import Path

OUTPUT_DIR = Path("output")


def _find_by_folder(name: str) -> tuple[dict | None, Path | None]:
    p = OUTPUT_DIR / name / "song.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8")), p
    # case-insensitive fallback
    for jp in OUTPUT_DIR.glob("*/song.json"):
        if jp.parent.name.lower() == name.lower():
            return json.loads(jp.read_text(encoding="utf-8")), jp
    return None, None


def _save(data: dict, path: Path) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ── commands ──────────────────────────────────────────────────────────────────

def cmd_serve(host: str, port: int) -> None:
    import socket
    try:
        ip = socket.gethostbyname(socket.gethostname())
    except Exception:
        ip = "your-ip"

    print(f"\n  Lyrics Review Tool")
    print(f"  {'-' * 34}")
    print(f"  Local:   http://localhost:{port}")
    print(f"  Network: http://{ip}:{port}")
    print(f"\n  Share the Network URL with collaborators on the same Wi-Fi.")
    print(f"  For remote access: ngrok http {port}\n")

    import uvicorn
    uvicorn.run("review_app.app:app", host=host, port=port, reload=False)


def cmd_status() -> None:
    songs = []
    for p in sorted(OUTPUT_DIR.glob("*/song.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        review = data.get("review") or {}
        songs.append((p.parent.name, data, review))

    if not songs:
        print("No songs found in output/")
        return

    print(f"\n{'SONG':<46} {'STAGE 2':<12} {'STAGE 3'}")
    print("-" * 72)
    for name, data, review in songs:
        s2 = review.get("stage2", "pending" if data.get("stage2_done") else "—")
        s3 = review.get("stage3", "pending" if data.get("stage3_done") else "—")
        print(f"{name[:45]:<46} {s2:<12} {s3}")

    pending = sum(
        1 for _, d, r in songs
        if (d.get("stage2_done") and r.get("stage2", "pending") == "pending")
        or (d.get("stage3_done") and r.get("stage3", "pending") == "pending")
    )
    print(f"\n{pending} item(s) pending review.")
    if pending:
        print("Run `python review.py serve` to open the browser tool.\n")


def cmd_approve(folder: str, stage: int) -> None:
    data, path = _find_by_folder(folder)
    if not data:
        print(f"Song not found: {folder!r}", file=sys.stderr)
        sys.exit(1)
    review = data.get("review") or {}
    review[f"stage{stage}"] = "approved"
    data["review"] = review
    _save(data, path)
    print(f"Approved: {folder!r} — stage {stage}")


def cmd_reject(folder: str, stage: int, reason: str) -> None:
    data, path = _find_by_folder(folder)
    if not data:
        print(f"Song not found: {folder!r}", file=sys.stderr)
        sys.exit(1)
    review = data.get("review") or {}
    review[f"stage{stage}"] = "rejected"
    if reason:
        review[f"stage{stage}_reason"] = reason
    data["review"] = review
    if stage == 2:
        source = data.get("lyrics_source")
        if source:
            rs = data.get("rejected_sources") or []
            if source not in rs:
                rs.append(source)
            data["rejected_sources"] = rs
        data["stage2_done"] = False
        data["stage3_done"] = False
    _save(data, path)
    print(f"Rejected: {folder!r} — stage {stage}" + (f" ({reason})" if reason else ""))


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(description="Lyrics pipeline review tool")
    sub = p.add_subparsers(dest="cmd")

    ps = sub.add_parser("serve", help="Start review web server")
    ps.add_argument("--host", default="0.0.0.0")
    ps.add_argument("--port", type=int, default=8080)

    sub.add_parser("status", help="Print review queue")

    pa = sub.add_parser("approve", help="Approve a stage for a song")
    pa.add_argument("folder", help="Folder name, e.g. 'Lykke Li - I Follow Rivers'")
    pa.add_argument("--stage", type=int, required=True)

    pr = sub.add_parser("reject", help="Reject a stage for a song")
    pr.add_argument("folder")
    pr.add_argument("--stage", type=int, required=True)
    pr.add_argument("--reason", default="")

    args = p.parse_args()
    if   args.cmd == "serve":   cmd_serve(args.host, args.port)
    elif args.cmd == "status":  cmd_status()
    elif args.cmd == "approve": cmd_approve(args.folder, args.stage)
    elif args.cmd == "reject":  cmd_reject(args.folder, args.stage, args.reason)
    else: p.print_help()


if __name__ == "__main__":
    main()
