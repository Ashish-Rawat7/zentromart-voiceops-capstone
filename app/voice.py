
from __future__ import annotations

import asyncio
import io
import logging
from math import gcd

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from gnani.stt import (
    GnaniSTTStreamClient,
    StreamTranscriptEvent,
    StreamErrorEvent,
)
from gnani.tts import GnaniTTSRealtimeClient, AudioConfig

from app.config import settings

logger = logging.getLogger("zentromart.voice")

STT_SAMPLE_RATE = 16000
STT_CHUNK_SIZE = 1024
STT_FRAME_SECONDS = 0.032
MAX_AUDIO_SECONDS = 120


def _require_api_key() -> str:
    """Get the Gnani API key without logging or exposing it."""
    api_key = settings.gnani_api_key

    if not api_key:
        raise RuntimeError("GNANI_API_KEY is not configured.")

    return api_key


def _wav_to_pcm16k(audio_bytes: bytes) -> bytes:
    """
    Convert uploaded audio into raw mono PCM:
    16 kHz, signed 16-bit little-endian, 1024-byte frames.
    """
    if not audio_bytes:
        raise ValueError("The uploaded audio is empty.")

    try:
        audio, sample_rate = sf.read(
            io.BytesIO(audio_bytes),
            dtype="float32",
            always_2d=True,
        )
    except Exception as exc:
        logger.warning(
            "Audio decoding failed: %s",
            type(exc).__name__,
        )
        raise ValueError(
            "Unable to decode the recording. Please record again."
        ) from exc

    if audio.size == 0 or sample_rate <= 0:
        raise ValueError("The recording contains no usable audio.")

    if not np.isfinite(audio).all():
        raise ValueError("The recording contains invalid audio samples.")

    duration_seconds = len(audio) / sample_rate

    if duration_seconds > MAX_AUDIO_SECONDS:
        raise ValueError(
            f"The recording is too long. Maximum length is "
            f"{MAX_AUDIO_SECONDS} seconds."
        )

    # Convert stereo or multichannel audio to mono.
    mono = audio.mean(axis=1)

    # Resample locally to 16 kHz.
    if sample_rate != STT_SAMPLE_RATE:
        divisor = gcd(int(sample_rate), STT_SAMPLE_RATE)

        mono = resample_poly(
            mono,
            STT_SAMPLE_RATE // divisor,
            int(sample_rate) // divisor,
        )

    if mono.size == 0:
        raise ValueError("The recording contains no usable audio.")

    # Check whether the recording contains meaningful audio.
    rms = float(np.sqrt(np.mean(np.square(mono, dtype=np.float64))))
    peak = float(np.max(np.abs(mono)))

    logger.info(
        "Audio prepared: input_rate=%d, duration=%.2fs, "
        "rms=%.6f, peak=%.6f",
        sample_rate,
        duration_seconds,
        rms,
        peak,
    )

    if peak < 0.001 or rms < 0.0001:
        raise ValueError(
            "The recording appears silent. Check your microphone "
            "and speak clearly while recording."
        )

    # Float audio -> signed 16-bit little-endian PCM.
    pcm = (
        np.clip(mono, -1.0, 1.0) * 32767.0
    ).astype("<i2").tobytes()

    if not pcm:
        raise ValueError("The recording contains no usable audio.")

    # Ensure the final frame is exactly 1024 bytes.
    remainder = len(pcm) % STT_CHUNK_SIZE

    if remainder:
        pcm += b"\x00" * (STT_CHUNK_SIZE - remainder)

    return pcm


async def transcribe_audio(
    audio_bytes: bytes,
    language_code: str | None = None,
) -> str:
    """
    Transcribe an uploaded recording using Gnani's WebSocket STT.

    Uses the explicit connect -> send_audio -> close flow so the
    final transcript events can be collected when the stream closes.
    """
    api_key = _require_api_key()
    language = language_code or settings.voice_stt_language

    pcm = _wav_to_pcm16k(audio_bytes)

    client = GnaniSTTStreamClient(
        api_key=api_key,
        language_code=language,
        sample_rate=STT_SAMPLE_RATE,
    )

    connection_open = False

    try:
        # Establish the WebSocket connection.
        config = await client.connect()
        connection_open = True

        logger.info(
            "Gnani STT connected: sample_rate=%s, language=%s",
            getattr(config, "sample_rate", STT_SAMPLE_RATE),
            language,
        )

        # Send raw PCM frames at real-time cadence.
        for offset in range(0, len(pcm), STT_CHUNK_SIZE):
            chunk = pcm[offset : offset + STT_CHUNK_SIZE]

            if len(chunk) != STT_CHUNK_SIZE:
                raise RuntimeError(
                    "Internal audio framing error: invalid PCM frame size."
                )

            await client.send_audio(chunk)
            await asyncio.sleep(STT_FRAME_SECONDS)

        # Send 0.5 seconds of silence to help Gnani detect the end
        # of the spoken utterance.
        silence_frame = b"\x00" * STT_CHUNK_SIZE

        for _ in range(16):
            await client.send_audio(silence_frame)
            await asyncio.sleep(STT_FRAME_SECONDS)

        # Give the receiver time to collect transcript events
        # before closing the WebSocket.
        await asyncio.sleep(3.0)

        # Close/finalize the stream and collect its final events.
        events = await client.close()
        connection_open = False

        if events is None:
            events = []

        event_types = [
            type(event).__name__
            for event in events
        ]

        logger.info(
            "Gnani STT finalized: event_count=%d, event_types=%s",
            len(events),
            event_types,
        )

        segments: list[str] = []
        server_errors: list[str] = []

        for event in events:
            if isinstance(event, StreamTranscriptEvent):
                event_text = getattr(event, "text", None)

                if isinstance(event_text, str) and event_text.strip():
                    segments.append(event_text.strip())

            elif isinstance(event, StreamErrorEvent):
                # Log the error type and a safe, concise message.
                message = getattr(event, "message", None)
                if isinstance(message, str) and message.strip():
                    server_errors.append(message.strip())

        transcript = " ".join(segments).strip()

        logger.info(
            "Gnani STT transcript events: count=%d",
            len(segments),
        )

        if transcript:
            return transcript

        if server_errors:
            logger.error(
                "Gnani STT server reported an error: %s",
                "; ".join(server_errors)[:500],
            )
            raise RuntimeError(
                "Gnani speech recognition returned an error. "
                "Check the FastAPI terminal for details."
            )

        logger.warning(
            "Gnani STT returned no transcript: event_count=%d, language=%s",
            len(events),
            language,
        )

        raise ValueError(
            "I couldn't understand the recording. Please speak clearly, "
            "record a few seconds of speech, and try again."
        )

    except (ValueError, RuntimeError):
        raise

    except Exception as exc:
        logger.exception(
            "Gnani STT request failed: exception_type=%s",
            type(exc).__name__,
        )

        raise RuntimeError(
            "Speech recognition is temporarily unavailable. "
            "Check the FastAPI terminal for the detailed error."
        ) from None

    finally:
        # Clean up if processing failed before the normal close.
        if connection_open:
            try:
                await client.close()
            except Exception:
                logger.warning(
                    "Could not cleanly close the Gnani STT connection."
                )


async def synthesize_reply(text: str) -> bytes:
    """Generate a WAV speech response using Gnani's WebSocket TTS."""
    api_key = _require_api_key()
    text = text.strip()

    if not text:
        raise ValueError("Cannot generate speech from an empty reply.")

    try:
        async with GnaniTTSRealtimeClient(
            api_key=api_key,
        ) as client:
            audio = await client.synthesize_and_collect(
                text,
                voice=settings.voice_tts_name,
                model=settings.voice_tts_model,
                language=settings.voice_tts_language,
                audio_config=AudioConfig(
                    sample_rate=24000,
                    encoding="linear_pcm",
                    num_channels=1,
                    sample_width=2,
                    container="wav",
                ),
            )

        if not audio:
            raise RuntimeError("Gnani returned no speech audio.")

        return audio

    except ValueError:
        raise

    except Exception as exc:
        logger.exception(
            "Gnani TTS request failed: exception_type=%s",
            type(exc).__name__,
        )

        raise RuntimeError(
            "Speech generation is temporarily unavailable. "
            "Check the FastAPI terminal for the detailed error."
        ) from None
