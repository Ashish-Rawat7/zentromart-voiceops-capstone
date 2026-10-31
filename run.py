from __future__ import annotations

import argparse
import base64
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run ZentroMart Support Agent on a folder of WAV recordings."
    )

    parser.add_argument(
        "--input",
        required=True,
        help="Folder containing WAV audio recordings.",
    )

    parser.add_argument(
        "--output",
        default="sample_outputs",
        help="Folder where transcripts, replies, and metadata will be saved.",
    )

    parser.add_argument(
        "--api",
        default="http://127.0.0.1:8000",
        help="Base URL of the running FastAPI backend.",
    )

    parser.add_argument(
        "--language",
        default="en-IN",
        help="Gnani language code, for example en-IN or hi-IN.",
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=180,
        help="HTTP timeout in seconds for each audio file.",
    )

    return parser.parse_args()


def safe_filename(name: str) -> str:
    """Return a filename-safe base name."""
    allowed = set(
        "abcdefghijklmnopqrstuvwxyz"
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "0123456789-_"
    )

    cleaned = "".join(
        character if character in allowed else "_"
        for character in name
    )

    return cleaned.strip("_") or "audio"


def save_json(path: Path, data: dict):
    """Save JSON with UTF-8 encoding."""
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def process_audio_file(
    audio_path: Path,
    output_dir: Path,
    api_url: str,
    language_code: str,
    timeout: int,
):
    """
    Submit one WAV file to /voice/turn and save the returned information.
    """

    output_dir.mkdir(parents=True, exist_ok=True)

    file_stem = safe_filename(audio_path.stem)
    session_id = str(uuid.uuid4())

    result_json_path = output_dir / f"{file_stem}.json"
    transcript_path = output_dir / f"{file_stem}_transcript.txt"
    reply_path = output_dir / f"{file_stem}_reply.txt"

    endpoint = f"{api_url.rstrip('/')}/voice/turn"

    print(f"\nProcessing: {audio_path.name}")

    record = {
        "audio_file": audio_path.name,
        "session_id": session_id,
        "language_code": language_code,
        "processed_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "started",
        "transcript": None,
        "reply": None,
        "sources": [],
        "decision": None,
        "verification_required": None,
        "ticket_created": None,
        "ticket_id": None,
        "audio_error": None,
        "response_audio_file": None,
        "error": None,
    }

    try:
        with audio_path.open("rb") as audio_file:
            files = {
                "audio": (
                    audio_path.name,
                    audio_file,
                    "audio/wav",
                )
            }

            data = {
                "session_id": session_id,
                "language_code": language_code,
            }

            response = requests.post(
                endpoint,
                files=files,
                data=data,
                timeout=timeout,
            )

        record["http_status"] = response.status_code

        if not response.ok:
            try:
                error_details = response.json()
            except ValueError:
                error_details = response.text

            record["status"] = "http_error"
            record["error"] = error_details

            save_json(result_json_path, record)

            print(
                f"  ERROR: API returned HTTP {response.status_code}"
            )
            print(f"  Details: {error_details}")

            return record

        result = response.json()

        # Extract fields returned by the existing /voice/turn endpoint.
        transcript = str(result.get("transcript") or "").strip()
        reply = str(result.get("reply") or "").strip()

        record.update(
            {
                "status": "success",
                "transcript": transcript,
                "reply": reply,
                "sources": result.get("sources") or [],
                "decision": result.get("decision"),
                "verification_required": result.get(
                    "verification_required"
                ),
                "ticket_created": result.get("ticket_created"),
                "ticket_id": result.get("ticket_id"),
                "audio_error": result.get("audio_error"),
            }
        )

        # Save transcript and reply as separate readable text files.
        transcript_path.write_text(
            transcript,
            encoding="utf-8",
        )

        reply_path.write_text(
            reply,
            encoding="utf-8",
        )

        # Decode and save Gnani TTS audio returned by the API.
        audio_base64 = result.get("audio_base64")

        if audio_base64:
            try:
                spoken_audio_bytes = base64.b64decode(
                    audio_base64,
                    validate=True,
                )

                # Current implementation assumes synthesized audio is WAV.
                # Confirm its actual format in app/voice.py before relying
                # on the .wav extension.
                response_audio_path = (
                    output_dir / f"{file_stem}_reply.wav"
                )

                response_audio_path.write_bytes(
                    spoken_audio_bytes
                )

                record["response_audio_file"] = (
                    response_audio_path.name
                )

            except (ValueError, base64.binascii.Error) as exc:
                record["audio_error"] = (
                    f"Could not decode audio_base64: {exc}"
                )

        # Save the complete API result plus our processing metadata.
        save_json(result_json_path, record)

        print("  SUCCESS")
        print(f"  Transcript: {transcript}")
        print(f"  Reply: {reply}")
        print(f"  JSON saved: {result_json_path.name}")

        return record

    except requests.Timeout:
        record["status"] = "timeout"
        record["error"] = (
            f"API request timed out after {timeout} seconds."
        )

        save_json(result_json_path, record)

        print("  ERROR: Request timed out.")

        return record

    except requests.RequestException as exc:
        record["status"] = "request_error"
        record["error"] = str(exc)

        save_json(result_json_path, record)

        print(f"  ERROR: Could not contact API: {exc}")

        return record

    except Exception as exc:
        record["status"] = "unexpected_error"
        record["error"] = f"{type(exc).__name__}: {exc}"

        save_json(result_json_path, record)

        print(f"  ERROR: {type(exc).__name__}: {exc}")

        return record


def main():
    args = parse_args()

    input_dir = Path(args.input).expanduser().resolve()
    output_dir = Path(args.output).expanduser().resolve()

    if not input_dir.exists():
        print(f"Input folder does not exist: {input_dir}")
        sys.exit(1)

    if not input_dir.is_dir():
        print(f"Input path is not a folder: {input_dir}")
        sys.exit(1)

    # Process only WAV files directly inside the specified input folder.
    audio_files = sorted(
        path
        for path in input_dir.iterdir()
        if path.is_file()
        and path.suffix.lower() == ".wav"
    )

    if not audio_files:
        print(f"No WAV files found in: {input_dir}")
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("ZentroMart Support Agent - Audio Batch Runner")
    print("=" * 60)
    print(f"Input folder : {input_dir}")
    print(f"Output folder: {output_dir}")
    print(f"API         : {args.api.rstrip('/')}/voice/turn")
    print(f"Language    : {args.language}")
    print(f"WAV files   : {len(audio_files)}")

    all_results = []

    for audio_path in audio_files:
        record = process_audio_file(
            audio_path=audio_path,
            output_dir=output_dir,
            api_url=args.api,
            language_code=args.language,
            timeout=args.timeout,
        )

        all_results.append(record)

    # Save a summary across all input audio files.
    summary = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_folder": str(input_dir),
        "output_folder": str(output_dir),
        "api": args.api,
        "language_code": args.language,
        "total_files": len(all_results),
        "successful": sum(
            item["status"] == "success"
            for item in all_results
        ),
        "failed": sum(
            item["status"] != "success"
            for item in all_results
        ),
        "results": all_results,
    }

    summary_path = output_dir / "batch_summary.json"
    save_json(summary_path, summary)

    print("\n" + "=" * 60)
    print("Batch processing completed.")
    print(f"Total files : {summary['total_files']}")
    print(f"Successful  : {summary['successful']}")
    print(f"Failed     : {summary['failed']}")
    print(f"Summary    : {summary_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()