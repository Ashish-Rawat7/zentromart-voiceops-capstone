from __future__ import annotations

import base64
import logging
import os
import re
import uuid
from typing import Any

import requests
import streamlit as st
from dotenv import load_dotenv

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
load_dotenv()

API_BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
VOICE_LANGUAGE_DEFAULT = os.getenv("VOICE_LANGUAGE", "en-IN")
API_CONNECT_TIMEOUT = 5
API_READ_TIMEOUT = 120
MAX_AUDIO_BYTES = 10 * 1024 * 1024  # Keep in sync with FastAPI's 10 MB limit.

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("zentromart.frontend")

st.set_page_config(
    page_title="ZentroMart | Customer Support",
    page_icon="🛍️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# -----------------------------------------------------------------------------
# Styling: fixed, high-contrast palette independent of OS/browser dark mode.
# -----------------------------------------------------------------------------
st.markdown(
    """
    <style>
    :root { color-scheme: light; }
    .stApp { background: #f4f7fb !important; color: #17233f !important; }
    [data-testid="stHeader"] { background: #f4f7fb !important; }
    [data-testid="stMainBlockContainer"] {
        max-width: 1180px; width: 100%;
        padding: 1.5rem clamp(1rem, 3vw, 2.5rem) 3rem;
    }
    [data-testid="stSidebar"] {
        background: #ffffff !important;
        border-right: 1px solid #e2e8f0;
    }
    [data-testid="stSidebar"] * { color: #253451; }
    h1, h2, h3, h4, h5, h6 { color: #17233f !important; }
    [data-testid="stMarkdownContainer"] p,
    [data-testid="stMarkdownContainer"] li,
    [data-testid="stMarkdownContainer"] strong,
    [data-testid="stMarkdownContainer"] em { color: #253451; }
    [data-testid="stCaptionContainer"],
    [data-testid="stCaptionContainer"] p { color: #64748b !important; }

    .zm-hero {
        background: linear-gradient(125deg, #111c3a 0%, #24529a 100%);
        color: #ffffff !important; padding: 1.6rem 1.8rem;
        border-radius: 18px; margin-bottom: 1rem;
        box-shadow: 0 8px 24px rgba(20, 40, 80, .12);
    }
    .zm-hero h1 { color: #ffffff !important; font-size: clamp(1.5rem, 3vw, 2.1rem); margin: 0 0 .55rem; }
    .zm-hero p { color: #e5edff !important; margin: 0; line-height: 1.65; }
    .zm-card {
        background: #ffffff !important; border: 1px solid #e2e8f0;
        border-radius: 14px; padding: 1rem 1.1rem; margin-bottom: .7rem;
        min-width: 0; overflow-wrap: anywhere;
    }
    .zm-card-label { color: #64748b !important; font-size: .84rem; margin-bottom: .25rem; }
    .zm-card-value { color: #17233f !important; font-size: 1rem; font-weight: 700; }
    [data-testid="stChatMessage"] {
        background: #ffffff !important; border: 1px solid #e2e8f0 !important;
        border-radius: 14px; padding: .8rem; margin-bottom: .7rem;
    }
    [data-testid="stChatMessage"] p,
    [data-testid="stChatMessage"] li,
    [data-testid="stChatMessage"] strong { color: #253451 !important; overflow-wrap: anywhere; }
    [data-testid="stChatInput"] { background: #ffffff !important; }
    [data-testid="stChatInput"] textarea,
    [data-testid="stTextInput"] input,
    [data-testid="stTextArea"] textarea {
        background: #ffffff !important; color: #17233f !important;
        caret-color: #17233f !important; border-color: #cbd5e1 !important;
    }
    [data-testid="stChatInput"] textarea::placeholder,
    [data-testid="stTextInput"] input::placeholder,
    [data-testid="stTextArea"] textarea::placeholder { color: #64748b !important; opacity: 1 !important; }
    [data-testid="stSelectbox"] > div > div,
    [data-testid="stMultiSelect"] > div > div {
        background: #ffffff !important; color: #17233f !important; border-color: #cbd5e1 !important;
    }
    [data-testid="stForm"] { background: #ffffff !important; border: 1px solid #e2e8f0 !important; border-radius: 12px; padding: 1rem; }
    [data-testid="stBaseButton-secondary"] { background: #ffffff !important; color: #253451 !important; border-color: #cbd5e1 !important; }
    [data-testid="stBaseButton-primary"] { background: #2457c5 !important; color: #ffffff !important; border-color: #2457c5 !important; }
    [data-testid="stBaseButton-primary"] * { color: #ffffff !important; }
    [data-testid="stBaseButton"] { border-radius: 10px; font-weight: 600; min-height: 2.6rem; }
    [data-testid="stAlert"] { border-radius: 12px; }
    [data-testid="stAudioInput"], [data-testid="stAudio"] { max-width: 100%; }
    [data-testid="stAudioInput"] > div { max-width: 100%; }
    hr { border-color: #e2e8f0 !important; }
    .zm-footer { text-align: center; color: #64748b !important; font-size: .82rem; padding-top: 1.5rem; }
    @media (max-width: 700px) {
        [data-testid="stMainBlockContainer"] { padding: 1rem .75rem 2rem; }
        .zm-hero { padding: 1.2rem; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# -----------------------------------------------------------------------------
# Session state
# -----------------------------------------------------------------------------
if "session_id" not in st.session_state:
    # UUID hex and hyphens satisfy the backend's session ID validator.
    st.session_state.session_id = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []
if "api_status" not in st.session_state:
    st.session_state.api_status = "Not checked"
if "last_voice_error" not in st.session_state:
    st.session_state.last_voice_error = None
if "voice_recording_id" not in st.session_state:
    st.session_state.voice_recording_id = 0

# -----------------------------------------------------------------------------
# API helpers
# -----------------------------------------------------------------------------
def _response_detail(response: requests.Response, fallback: str) -> str:
    try:
        body = response.json()
        detail = body.get("detail", fallback) if isinstance(body, dict) else fallback
        if isinstance(detail, (dict, list)):
            return str(detail)
        return str(detail)
    except (ValueError, requests.RequestException):
        return fallback


def api_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        response = requests.post(
            f"{API_BASE_URL}{path}",
            json=payload,
            timeout=(API_CONNECT_TIMEOUT, API_READ_TIMEOUT),
        )
    except requests.Timeout as exc:
        raise RuntimeError("The support API timed out. Please try again.") from exc
    except requests.ConnectionError as exc:
        raise RuntimeError("Cannot connect to FastAPI. Check that the backend is running.") from exc

    if not response.ok:
        raise RuntimeError(_response_detail(response, f"Request failed (HTTP {response.status_code})."))
    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError("The API returned an invalid JSON response.") from exc
    if not isinstance(data, dict):
        raise RuntimeError("The API returned an unexpected response format.")
    return data


def api_get(path: str) -> dict[str, Any]:
    try:
        response = requests.get(
            f"{API_BASE_URL}{path}",
            timeout=(API_CONNECT_TIMEOUT, 15),
        )
    except requests.Timeout as exc:
        raise RuntimeError("The API health check timed out.") from exc
    except requests.ConnectionError as exc:
        raise RuntimeError("Cannot connect to FastAPI. Start the backend first.") from exc

    if not response.ok:
        raise RuntimeError(_response_detail(response, f"Health check failed (HTTP {response.status_code})."))
    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError("The health endpoint returned invalid JSON.") from exc
    if not isinstance(data, dict):
        raise RuntimeError("The health endpoint returned an unexpected response format.")
    return data


def api_voice_post(audio_bytes: bytes, language_code: str) -> dict[str, Any]:
    if not audio_bytes:
        raise RuntimeError("The recording is empty. Record your question and try again.")
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise RuntimeError("The recording exceeds the 10 MB upload limit. Please record a shorter clip.")

    # Streamlit's audio_input returns a WAV recording. The API expects multipart form data.
    files = {"audio": ("recording.wav", audio_bytes, "audio/wav")}
    form_data = {
        "session_id": st.session_state.session_id,
        "language_code": language_code,
    }
    try:
        response = requests.post(
            f"{API_BASE_URL}/voice/turn",
            files=files,
            data=form_data,
            timeout=(API_CONNECT_TIMEOUT, API_READ_TIMEOUT),
        )
    except requests.Timeout as exc:
        raise RuntimeError("Voice processing timed out. Try a shorter recording.") from exc
    except requests.ConnectionError as exc:
        raise RuntimeError("Cannot connect to FastAPI. Check the backend terminal.") from exc

    if not response.ok:
        detail = _response_detail(response, f"Voice request failed (HTTP {response.status_code}).")
        raise RuntimeError(f"{detail} (HTTP {response.status_code})")

    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError("The voice API returned an invalid JSON response.") from exc
    if not isinstance(data, dict):
        raise RuntimeError("The voice API returned an unexpected response format.")
    return data

# -----------------------------------------------------------------------------
# Privacy / audio helpers
# -----------------------------------------------------------------------------
def redact_verification_message(text: str) -> str:
    """Hide likely standalone phone suffixes or pincodes in visible chat history."""
    if re.fullmatch(
        r"\s*(?:last four digits|pincode|pin|digits|"
        r"आख़िरी चार अंक|आखिरी चार अंक)?\s*[:=]?\s*\d{4,6}\s*",
        text,
        re.IGNORECASE,
    ):
        return "[Verification value submitted]"

    if re.search(
        r"(?i)(last four digits|pincode|digits|"
        r"आख़िरी चार अंक|आखिरी चार अंक).{0,20}\d{4,6}",
        text,
    ):
        return re.sub(r"\d{4,6}", "[REDACTED]", text)
    return text



def render_message_audio(audio_b64: str) -> None:
    """Decode and play the assistant's WAV response, reporting invalid audio safely."""
    if not audio_b64:
        st.caption("No audio was returned for this response.")
        return

    try:
        audio_bytes = base64.b64decode(audio_b64, validate=True)
    except (ValueError, TypeError):
        logger.exception("Invalid base64 audio returned by the voice API")
        st.warning("The assistant returned audio that could not be decoded.")
        return

    if not audio_bytes:
        st.warning("The assistant returned empty audio.")
        return

    # The backend is configured to return WAV audio. Validate the container
    # before handing it to Streamlit's browser audio player.
    if (
        len(audio_bytes) < 12
        or audio_bytes[:4] != b"RIFF"
        or audio_bytes[8:12] != b"WAVE"
    ):
        logger.error(
            "Assistant audio is not a valid WAV container (received %s bytes)",
            len(audio_bytes),
        )
        st.warning("Audio was generated, but it is not a valid WAV file.")
        return

    try:
        st.audio(audio_bytes, format="audio/wav")
    except Exception:
        logger.exception("Streamlit could not render assistant audio")
        st.warning("The reply is available as text, but audio playback failed.")

# -----------------------------------------------------------------------------
# Header
# -----------------------------------------------------------------------------
st.markdown(
    """
    <div class="zm-hero">
      <h1>🛍️ ZentroMart Support</h1>
      <p>Your shopping support assistant. Ask about orders, delivery, returns,
      refunds, products, and store policies using text or voice.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

c1, c2, c3 = st.columns(3)
with c1:
    st.markdown('<div class="zm-card"><div class="zm-card-label">Support channel</div><div class="zm-card-value">Text + Voice</div></div>', unsafe_allow_html=True)
with c2:
    st.markdown('<div class="zm-card"><div class="zm-card-label">Speech provider</div><div class="zm-card-value">Gnani STT / TTS</div></div>', unsafe_allow_html=True)
with c3:
    st.markdown('<div class="zm-card"><div class="zm-card-label">Conversation</div><div class="zm-card-value">Active session</div></div>', unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# Conversation - full width, no cramped right-hand panel
# -----------------------------------------------------------------------------
st.markdown("### 💬 Your conversation")
st.caption("Use text chat or record a voice message. Both use the same support session.")

if not st.session_state.messages:
    with st.chat_message("assistant", avatar="🛍️"):
        st.markdown(
            "Hello! Welcome to ZentroMart Support. 👋\n\n"
            "I can help with order status, delivery, returns, refunds, products, and store policies.\n\n"
            "**How can I help you today?**"
        )

for message in st.session_state.messages:
    role = message.get("role", "assistant")
    avatar = "🛍️" if role == "assistant" else "👤"
    with st.chat_message(role, avatar=avatar):
        st.markdown(message.get("content", ""))
        sources = message.get("sources") or []
        if sources:
            st.caption("Sources: " + ", ".join(str(source) for source in sources))
        if message.get("audio_base64"):
            render_message_audio(message["audio_base64"])
        if message.get("audio_error"):
            st.caption(str(message["audio_error"]))

# Voice input section
with st.container(border=True):
    st.markdown("### 🎙️ Talk to your support assistant")
    st.caption("Record a clear, short question. Wait for the recording preview, then send it.")
    voice_language = st.selectbox(
        "Speech recognition language",
        options=["en-IN", "hi-IN"],
        index=0 if VOICE_LANGUAGE_DEFAULT not in {"en-IN", "hi-IN"} else ["en-IN", "hi-IN"].index(VOICE_LANGUAGE_DEFAULT),
        format_func=lambda code: "English (India)" if code == "en-IN" else "Hindi (India)",
        key="voice_language",
    )
    voice_recording = st.audio_input(
        "Record your question",
        sample_rate=16000,
        key=f"zentromart_voice_recording_{st.session_state.voice_recording_id}",
    )
    voice_col1, voice_col2 = st.columns([1, 2])
    with voice_col1:
        send_voice = st.button(
            "🎤 Send voice message",
            type="primary",
            use_container_width=True,
            disabled=voice_recording is None,
            key="send_voice_message",
        )
    with voice_col2:
        if voice_recording is not None:
            st.caption(f"Recording ready · {len(voice_recording.getvalue()) / 1024:.0f} KB")

if send_voice and voice_recording is not None:
    try:
        audio_bytes = voice_recording.getvalue()
        with st.spinner("Recognizing speech and preparing your reply..."):
            result = api_voice_post(audio_bytes, voice_language)

        transcript = str(result.get("transcript") or "").strip()
        reply = str(result.get("reply") or "").strip()
        sources = result.get("sources") or []
        audio_b64 = result.get("audio_base64")
        audio_error = result.get("audio_error")

        if not transcript:
            raise RuntimeError("No speech was recognized. Try speaking closer to the microphone.")
        if not reply:
            raise RuntimeError("The support assistant returned an empty reply.")

        st.session_state.messages.append({
            "role": "user",
            "content": redact_verification_message(transcript),
        })
        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": reply,
            "sources": sources,
        }
        if isinstance(audio_b64, str) and audio_b64:
            assistant_message["audio_base64"] = audio_b64
        if audio_error:
            assistant_message["audio_error"] = str(audio_error)
        st.session_state.messages.append(assistant_message)
        st.session_state.last_voice_error = None

        # Give the browser a fresh recording widget after the submitted recording
        # has been processed, so it does not try to reuse an old preview Blob URL.
        st.session_state.voice_recording_id += 1
        st.rerun()
    except RuntimeError as exc:
        st.session_state.last_voice_error = str(exc)
        logger.exception("Voice request failed")
        st.error(f"Voice support error: {exc}")

    except requests.RequestException as exc:
        logger.exception("HTTP error during voice request")
        st.error(f"Network error during voice request: {exc}")

    except Exception as exc:
        logger.exception("Unexpected error while processing voice input")
        st.error(
            f"Unexpected voice interface error: {type(exc).__name__}: {exc}"
        )


# Text input is outside forms so Enter submits naturally.
prompt = st.chat_input("Ask about an order, return, refund, delivery, or product…")
if prompt:
    st.session_state.messages.append({
        "role": "user",
        "content": redact_verification_message(prompt),
    })
    try:
        with st.spinner("Preparing your response..."):
            result = api_post("/chat", {
                "session_id": st.session_state.session_id,
                "message": prompt,
            })
        reply = str(result.get("reply") or "I'm sorry, I couldn't prepare a response.")
        sources = result.get("sources") or []
    except RuntimeError as exc:
        reply = "I'm unable to reach support right now. Please try again in a moment."
        sources = []
        st.error(str(exc))
    except requests.RequestException:
        logger.exception("Unexpected HTTP error during chat request")
        reply = "I'm unable to reach support right now. Please try again in a moment."
        sources = []
        st.error("Network error while contacting support. Check that FastAPI is running.")

    st.session_state.messages.append({
        "role": "assistant",
        "content": reply,
        "sources": sources,
    })
    st.rerun()

# -----------------------------------------------------------------------------
# Sidebar: order verification, ticket creation, health
# -----------------------------------------------------------------------------
with st.sidebar:
    st.markdown("## 🛍️ ZentroMart")
    st.caption("Customer support control panel")
    st.divider()

    st.markdown("### 📦 Order verification")
    st.caption("Enter the 8-digit order ID to begin verification.")
    with st.form("order_start_form"):
        order_id = st.text_input("8-digit order ID", max_chars=16, placeholder="Enter order ID")
        start_clicked = st.form_submit_button("Start verification", use_container_width=True)
    if start_clicked:
        try:
            result = api_post("/orders/start", {
                "session_id": st.session_state.session_id,
                "order_id": order_id.strip(),
            })
            st.success(str(result.get("message", "Verification started.")))
        except RuntimeError as exc:
            st.error(str(exc))
        except requests.RequestException:
            st.error("Network error while starting verification.")

    with st.form("order_verify_form", clear_on_submit=True):
        method = st.selectbox(
            "Verification method",
            ["phone_suffix", "delivery_pincode"],
            format_func=lambda value: "Registered phone — last 4 digits" if value == "phone_suffix" else "Delivery pincode — 6 digits",
        )
        proof = st.text_input("Verification value", max_chars=6, type="password", placeholder="Enter requested digits")
        verify_clicked = st.form_submit_button("Verify order", use_container_width=True)
    if verify_clicked:
        try:
            result = api_post("/orders/verify", {
                "session_id": st.session_state.session_id,
                "verification_type": method,
                "verification_value": proof.strip(),
            })
            if result.get("verified"):
                st.success(str(result.get("message", "Order verified.")))
            else:
                st.error(str(result.get("message", "Verification failed.")))
        except RuntimeError as exc:
            st.error(str(exc))
        except requests.RequestException:
            st.error("Network error while verifying the order.")

    st.divider()
    st.markdown("### 🎫 Support ticket")
    with st.form("ticket_form", clear_on_submit=True):
        subject = st.text_input("Subject", max_chars=200, placeholder="Brief issue title")
        category = st.selectbox("Category", ["general", "delivery", "returns", "refund", "payment", "account", "product", "safety"])
        description = st.text_area("Describe the issue", max_chars=2500, height=110, placeholder="Explain what happened…")
        ticket_order_id = st.text_input("Related order ID (optional)", max_chars=16)
        ticket_clicked = st.form_submit_button("Submit ticket", use_container_width=True)
    if ticket_clicked:
        try:
            result = api_post("/tickets", {
                "session_id": st.session_state.session_id,
                "subject": subject,
                "description": description,
                "category": category,
                "order_id": ticket_order_id.strip() or None,
            })
            if result.get("created"):
                st.success(f"Ticket created: {result.get('ticket_id', 'Created')}")
            else:
                st.error(str(result.get("message", "Ticket was not created.")))
        except RuntimeError as exc:
            st.error(str(exc))
        except requests.RequestException:
            st.error("Network error while creating the ticket.")

    st.divider()
    st.markdown("### ⚙️ Backend status")
    if st.button("Check API health", use_container_width=True):
        try:
            health = api_get("/health")
            if health.get("status") == "ok":
                st.session_state.api_status = "Connected"
                st.success("FastAPI is reachable.")
            else:
                st.session_state.api_status = "Check required"
                st.warning("API responded; check the health details.")
            st.write("Dataset:", "Available" if health.get("dataset_available") else "Missing files")
            missing = health.get("dataset_missing_files") or []
            if missing:
                st.write("Missing files:", missing)
            st.write("Gemini:", "Enabled" if health.get("gemini_enabled") else "Disabled — rules/fallback active")
        except RuntimeError as exc:
            st.session_state.api_status = "Disconnected"
            st.error(str(exc))
        except requests.RequestException:
            st.session_state.api_status = "Disconnected"
            st.error("API not reachable. Start FastAPI in another terminal.")

    st.caption(f"API status: {st.session_state.api_status}")
    st.divider()
    if st.button("🗑️ Clear visible conversation", use_container_width=True):
        # This only clears the local display, not the backend SQLite session.
        st.session_state.messages = []
        st.rerun()
    st.caption("Local capstone interface · Synthetic dataset · SQLite storage")

st.markdown(
    '<div class="zm-footer">ZentroMart Customer Support · AI-assisted, policy-grounded help</div>',
    unsafe_allow_html=True,
)
