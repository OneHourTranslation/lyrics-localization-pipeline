"""Stage 5: translation into target languages via BLEND (stub — not yet implemented).

Submitted through BLEND, which integrates with EasyTranslate for LLM translation +
quality estimation (QE). Lines EasyTranslate's QE flags as uncertain are returned
to us for a human post-editor (PE) to fix before the localized SRT is finalized.
"""
import logging
from models.song import SongResult

logger = logging.getLogger(__name__)


async def run_stage5(songs: list[SongResult]) -> list[SongResult]:
    raise NotImplementedError("Stage 5 (BLEND / EasyTranslate translation) not yet implemented")
