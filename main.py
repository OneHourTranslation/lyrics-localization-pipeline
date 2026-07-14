"""
CLI entry point.

Usage:
  python main.py urls.txt              # run all implemented stages (1-3)
  python main.py urls.txt --stage 1    # download audio only
  python main.py urls.txt --stage 2    # re-run lyrics lookup from existing JSONs
  python main.py urls.txt --stage 3    # re-run SRT generation from existing JSONs
  python main.py urls.txt --verbose    # DEBUG logging
"""
import argparse
import asyncio
import logging
import sys
from pathlib import Path

from config import settings
from models.song import LyricsRoute, LyricsStatus
from pipeline.stage1_extract import load_all_results, run_stage1
from pipeline.stage2_lyrics import run_stage2
from pipeline.stage3_srt import run_stage3
from utils.logging_setup import configure_logging

logger = logging.getLogger(__name__)


def _print_summary(songs: list) -> None:
    width = 98
    logger.info("=" * width)
    logger.info(f"{'VIDEO ID':<14} {'TITLE':<26} {'SOURCE':<10} {'STATUS':<10} {'ROUTING':<16} {'SRT':<8} {'DUR CHECK'}")
    logger.info("-" * width)
    for s in songs:
        title = (s.title or "")[:24]
        source = (s.lyrics_source or "-")[:8]
        status = s.lyrics_status.value if s.lyrics_status else "-"
        route = s.routing.value if s.routing else "-"
        srt = "en.srt" if s.stage3_done else "-"
        dur = f"⚠ {s.duration_mismatch}" if s.duration_mismatch else "ok"
        logger.info(f"{s.video_id:<14} {title:<26} {source:<10} {status:<10} {route:<16} {srt:<8} {dur}")
    logger.info("=" * width)

    sources: dict[str, int] = {}
    statuses: dict[str, int] = {}
    routes: dict[str, int] = {}
    mismatches: dict[str, int] = {}
    for s in songs:
        k = s.lyrics_source or "none"
        sources[k] = sources.get(k, 0) + 1
        k = s.lyrics_status.value if s.lyrics_status else "error"
        statuses[k] = statuses.get(k, 0) + 1
        k = s.routing.value if s.routing else "none"
        routes[k] = routes.get(k, 0) + 1
        if s.duration_mismatch:
            mismatches[s.duration_mismatch] = mismatches.get(s.duration_mismatch, 0) + 1

    logger.info(f"Sources:  {sources}")
    logger.info(f"Status:   {statuses}")
    logger.info(f"Routing:  {routes}")
    srt_done = sum(1 for s in songs if s.stage3_done)
    logger.info(f"SRT files written: {srt_done}/{len(songs)}")
    if mismatches:
        logger.warning(f"Duration mismatches (review needed): {mismatches}")


async def run(urls_file: Path, stage: int) -> None:
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    urls = [u.strip() for u in urls_file.read_text(encoding="utf-8").splitlines()
            if u.strip() and not u.strip().startswith("#")]
    logger.info(f"Loaded {len(urls)} URL(s) from {urls_file}")

    if stage == 1:
        songs = await run_stage1(urls)
        logger.info(f"Stage 1 complete: {sum(s.stage1_done for s in songs)}/{len(songs)} succeeded")

    elif stage == 2:
        all_results = load_all_results()
        ready = [s for s in all_results if s.stage1_done and not s.error]
        logger.info(f"Stage 2 standalone: {len(ready)} songs ready")
        if not ready:
            logger.error("No stage-1 results found. Run stage 1 first.")
            sys.exit(1)
        songs = await run_stage2(ready)
        _print_summary(songs)

    elif stage == 3:
        all_results = load_all_results()
        ready = [s for s in all_results if s.stage2_done and not s.error]
        logger.info(f"Stage 3 standalone: {len(ready)} songs ready")
        if not ready:
            logger.error("No stage-2 results found. Run stage 2 first.")
            sys.exit(1)
        songs = await run_stage3(ready)
        _print_summary(songs)

    else:  # full pipeline
        songs = await run_stage1(urls)
        logger.info(f"Stage 1 complete: {sum(s.stage1_done for s in songs)}/{len(songs)} succeeded")

        ready = [s for s in songs if s.stage1_done and not s.error]
        songs = await run_stage2(ready)

        ready = [s for s in songs if s.stage2_done]
        songs = await run_stage3(ready)
        _print_summary(songs)


def main() -> None:
    parser = argparse.ArgumentParser(description="Lyrics pipeline — stages 1-3")
    parser.add_argument("urls_file", type=Path, help="Text file with one YouTube URL per line")
    parser.add_argument(
        "--stage", type=int, choices=[1, 2, 3], default=0,
        help="Run a single stage only (0 = run all implemented stages)",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable DEBUG logging")
    args = parser.parse_args()

    configure_logging(logging.DEBUG if args.verbose else logging.INFO)

    if not args.urls_file.exists():
        print(f"File not found: {args.urls_file}", file=sys.stderr)
        sys.exit(1)

    asyncio.run(run(args.urls_file, args.stage))


if __name__ == "__main__":
    main()
