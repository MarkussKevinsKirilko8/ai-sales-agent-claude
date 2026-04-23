import logging
import tempfile

from app.config.settings import settings

logger = logging.getLogger(__name__)


async def transcribe_voice(file_bytes: bytes) -> str | None:
    """Transcribe voice message bytes using OpenAI Whisper."""
    if not settings.openai_api_key:
        logger.warning("No OpenAI API key — voice transcription unavailable")
        return None

    try:
        import openai
        client = openai.AsyncOpenAI(api_key=settings.openai_api_key)

        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=True) as tmp:
            tmp.write(file_bytes)
            tmp.flush()

            with open(tmp.name, "rb") as audio_file:
                transcript = await client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                )

        return transcript.text
    except Exception as e:
        logger.error(f"Whisper transcription failed: {e}")
        return None