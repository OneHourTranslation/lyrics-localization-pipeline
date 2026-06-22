"""Stage 4: Vocal separation (Demucs) + ASR (Deepgram) (stub — not yet implemented)."""
import logging
from models.song import SongResult

logger = logging.getLogger(__name__)


async def run_stage4(songs: list[SongResult]) -> list[SongResult]:
    raise NotImplementedError("Stage 4 (Demucs + Deepgram ASR) not yet implemented")
