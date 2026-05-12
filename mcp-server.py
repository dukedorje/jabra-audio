#!/usr/bin/env python3
"""
Voice & Ears MCP server — Jabra SPEAK 510 USB
==============================================
Exposes semantic audio tools so Hermes can speak and hear through the Jabra
without touching ALSA/PipeWire commands directly.

voice_speak(text)   → TTS → play on Jabra (edge-tts, fast/free)
voice_clone(text, ref_audio, ref_text?) → voice cloning → RunPod GPU
voice_play(path)    → play audio file on Jabra
voice_stop()        → kill current playback
ears_listen(secs)   → record mic → STT → return text
ears_status()       → check if Jabra is connected

Default device: Jabra SPEAK 510 USB (ALSA hw:3,0)
"""

import asyncio
import base64
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# ── Configuration ───────────────────────────────────────────────────────────

# RunPod Serverless (optional — for fast GPU voice cloning)
RUNPOD_ENDPOINT_ID = os.environ.get("RUNPOD_ENDPOINT_ID", "")
RUNPOD_API_KEY = os.environ.get("RUNPOD_API_KEY", "")
RUNPOD_URL = (
    f"https://{RUNPOD_ENDPOINT_ID}.api.runpod.ai/v2/runsync"
    if RUNPOD_ENDPOINT_ID
    else ""
)

# Load from env file if present
_ENV_FILE = Path.home() / ".hermes" / "jabra-runpod.env"
if _ENV_FILE.exists():
    for line in _ENV_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            os.environ[key] = val
            if key == "RUNPOD_ENDPOINT_ID":
                RUNPOD_ENDPOINT_ID = val
                RUNPOD_URL = f"https://{val}.api.runpod.ai/v2/runsync"
            elif key == "RUNPOD_API_KEY":
                RUNPOD_API_KEY = val

JABRA_DEVICE = "hw:3,0"
JABRA_DEVICE_NAME = "Jabra SPEAK 510 USB"

# PipeWire names (monitored for status checks)
PW_SINK = "alsa_output.usb-0b0e_Jabra_SPEAK_510_USB"
PW_SOURCE = "alsa_input.usb-0b0e_Jabra_SPEAK_510_USB"

# edge-tts voice
TTS_VOICE = "en-US-JennyNeural"  # clear female US English

# faster-whisper model (tiny = fast, base = better accuracy)
WHISPER_MODEL = "base"

# ── Playback management ─────────────────────────────────────────────────────

_playback_proc: subprocess.Popen | None = None
_playback_lock = threading.Lock()


def _is_jabra_present() -> bool:
    """Check if Jabra is connected via aplay -l."""
    try:
        result = subprocess.run(
            ["aplay", "-l"], capture_output=True, text=True, timeout=5
        )
        return "Jabra" in result.stdout
    except Exception:
        return False


def _get_jabra_source_name() -> str:
    """Get the exact PipeWire source name for the Jabra mic."""
    try:
        result = subprocess.run(
            ["pactl", "list", "short", "sources"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.splitlines():
            if "Jabra" in line and ".monitor" not in line:
                return line.split("\t")[1]  # second column is the name
    except Exception:
        pass
    return PW_SOURCE  # fallback


def _stop_playback():
    """Kill any active playback process."""
    global _playback_proc
    with _playback_lock:
        if _playback_proc and _playback_proc.poll() is None:
            _playback_proc.terminate()
            try:
                _playback_proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                _playback_proc.kill()
            _playback_proc = None


def _play_audio_file(path: str) -> str:
    """Play an audio file through the Jabra. Blocks until done.
    Pipeline: ffmpeg decode → convert to stereo 48kHz s16le → aplay to Jabra.
    """
    global _playback_proc
    _stop_playback()

    if not os.path.exists(path):
        return f"File not found: {path}"

    if not _is_jabra_present():
        return "Jabra device not connected"

    try:
        with _playback_lock:
            # ffmpeg decodes any format, converts to Jabra-compatible WAV,
            # pipes to aplay which outputs to the Jabra ALSA device
            _playback_proc = subprocess.Popen(
                [
                    "ffmpeg",
                    "-loglevel", "quiet",
                    "-i", path,
                    "-f", "wav",
                    "-ac", "2",
                    "-ar", "48000",
                    "pipe:1",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            aplay_proc = subprocess.Popen(
                ["aplay", "-D", JABRA_DEVICE, "-q"],
                stdin=_playback_proc.stdout,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            _playback_proc.stdout.close()
            # Wait for ffmpeg to finish, then aplay
            _playback_proc.wait(timeout=300)
            aplay_proc.wait(timeout=30)
            _playback_proc = None
        return "Playback complete"
    except subprocess.TimeoutExpired:
        _stop_playback()
        return "Playback timed out"
    except FileNotFoundError as e:
        return f"Required tool not found: {e}"
    except Exception as e:
        _stop_playback()
        return f"Playback error: {e}"


async def _tts_and_play(text: str) -> str:
    """Generate TTS audio with edge-tts and play through Jabra."""
    if not text.strip():
        return "No text to speak"

    if not _is_jabra_present():
        return "Jabra device not connected"

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        tmp_path = f.name

    try:
        # Generate TTS
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "edge_tts",
            "--voice", TTS_VOICE,
            "--text", text,
            "--write-media", tmp_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            err = stderr.decode()[:200]
            return f"TTS generation failed: {err}"

        # Play through Jabra (blocking, run in thread)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _play_audio_file, tmp_path)
        return result

    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


async def _voice_clone_via_runpod(
    text: str, ref_audio_path: str, ref_text: str = ""
) -> str:
    """Clone a voice from reference audio using RunPod GPU (Qwen3-TTS).

    Returns base64-encoded WAV audio or an error string.
    """
    if not RUNPOD_URL or not RUNPOD_API_KEY:
        return (
            "RunPod not configured. Set RUNPOD_ENDPOINT_ID and RUNPOD_API_KEY "
            "in ~/.hermes/jabra-runpod.env"
        )

    if not os.path.exists(ref_audio_path):
        return f"Reference audio not found: {ref_audio_path}"

    # Read and base64-encode the reference audio
    loop = asyncio.get_running_loop()

    def _read_ref():
        with open(ref_audio_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    ref_audio_b64 = await loop.run_in_executor(None, _read_ref)

    payload = {
        "input": {
            "text": text,
            "mode": "clone",
            "ref_audio_b64": ref_audio_b64,
            "language": "english",
        }
    }
    if ref_text:
        payload["input"]["ref_text"] = ref_text

    headers = {
        "Authorization": f"Bearer {RUNPOD_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        import urllib.request

        req = urllib.request.Request(
            RUNPOD_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        def _do_request():
            return urllib.request.urlopen(req, timeout=10)

        resp = await loop.run_in_executor(None, _do_request)
        result = json.loads(resp.read().decode("utf-8"))

        if result.get("status") == "COMPLETED":
            output = result.get("output", {})
            audio_b64 = output.get("audio_b64", "")
            duration = output.get("duration_seconds", 0)
            inf_time = output.get("inference_time_seconds", 0)

            if not audio_b64:
                return f"RunPod returned no audio: {output.get('error', 'unknown')}"

            # Write decoded audio to temp file and play through Jabra
            audio_bytes = base64.b64decode(audio_b64)
            with tempfile.NamedTemporaryFile(
                suffix=".wav", delete=False
            ) as f:
                tmp_path = f.name
                f.write(audio_bytes)

            try:
                result_msg = await loop.run_in_executor(
                    None, _play_audio_file, tmp_path
                )
                return (
                    f"Voice clone OK ({duration}s audio, "
                    f"{inf_time}s GPU inference). {result_msg}"
                )
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        else:
            error = result.get("error", result.get("status", "unknown error"))
            return f"RunPod failed: {error}"

    except Exception as e:
        return f"RunPod request failed: {e}"


async def _voice_clone_local_fallback(
    text: str, ref_audio_path: str, ref_text: str = ""
) -> str:
    """Voice cloning using local Qwen3-TTS CPU binary (slow, fallback only)."""
    QWEN_BIN = "/home/dorje/projects/jabra-audio/qwen3_tts_rs/voice_clone"
    QWEN_MODEL = (
        "/home/dorje/projects/jabra-audio/qwen3_tts_rs/models/"
        "Qwen3-TTS-12Hz-0.6B-Base"
    )
    QWEN_LIBTORCH = (
        "/home/dorje/projects/jabra-audio/qwen3_tts_rs/libtorch/lib"
    )

    if not os.path.exists(QWEN_BIN):
        return "Local Qwen3-TTS not installed"

    if not os.path.exists(ref_audio_path):
        return f"Reference audio not found: {ref_audio_path}"

    # Resample reference audio to 24kHz mono
    resampled = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    resampled.close()
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-loglevel", "quiet",
            "-i", ref_audio_path,
            "-ac", "1", "-ar", "24000", "-sample_fmt", "s16",
            resampled.name,
        )
        await proc.wait()

        output_wav = "/tmp/output_voice_clone.wav"  # qwen3 default output
        cmd = [QWEN_BIN, QWEN_MODEL, resampled.name, text, "english"]
        if ref_text:
            cmd.append(ref_text)

        env = os.environ.copy()
        env["LD_LIBRARY_PATH"] = QWEN_LIBTORCH + ":" + env.get(
            "LD_LIBRARY_PATH", ""
        )

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=300
        )

        if os.path.exists(output_wav):
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                None, _play_audio_file, output_wav
            )
        else:
            err = stderr.decode()[-300:] if stderr else "no output"
            return f"Local voice clone failed: {err}"
    finally:
        try:
            os.unlink(resampled.name)
        except OSError:
            pass


async def _stt_from_mic(duration_seconds: int) -> str:
    """Record from Jabra mic and transcribe with faster-whisper."""
    if not _is_jabra_present():
        return "Jabra device not connected"

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav_path = f.name

    try:
        # Record from Jabra mic using parec (PipeWire)
        source = _get_jabra_source_name()
        proc = await asyncio.create_subprocess_exec(
            "parec",
            "--device", source,
            "--format=s16le",
            "--rate=16000",
            "--channels=1",
            "--file-format=wav",
            wav_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            await asyncio.wait_for(proc.wait(), timeout=duration_seconds + 5)
        except asyncio.TimeoutError:
            proc.terminate()
            await proc.wait()

        # Check if we got actual audio data
        if os.path.getsize(wav_path) < 1000:
            return "[silence]"

        # Transcribe with faster-whisper (run in thread to avoid blocking)
        loop = asyncio.get_running_loop()

        def _transcribe():
            from faster_whisper import WhisperModel
            model = WhisperModel(
                WHISPER_MODEL,
                device="cpu",
                compute_type="int8",
                cpu_threads=2,
            )
            segments, _ = model.transcribe(wav_path, beam_size=5)
            parts = [seg.text.strip() for seg in segments if seg.text.strip()]
            return " ".join(parts) if parts else "[unintelligible]"

        return await loop.run_in_executor(None, _transcribe)

    finally:
        try:
            os.unlink(wav_path)
        except OSError:
            pass


def _device_status() -> str:
    """Return detailed Jabra status."""
    lines = []
    present = _is_jabra_present()
    lines.append(f"Jabra SPEAK 510 USB: {'CONNECTED' if present else 'NOT FOUND'}")

    if present:
        # Check PipeWire sink/source state
        try:
            result = subprocess.run(
                ["pactl", "list", "short", "sinks"],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.splitlines():
                if "Jabra" in line:
                    parts = line.split("\t")
                    state = parts[-1] if len(parts) > 3 else "unknown"
                    lines.append(f"  Speaker (sink): {state}")
                    break
        except Exception:
            pass

        try:
            result = subprocess.run(
                ["pactl", "list", "short", "sources"],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.splitlines():
                if "Jabra" in line and ".monitor" not in line:
                    parts = line.split("\t")
                    state = parts[-1] if len(parts) > 3 else "unknown"
                    lines.append(f"  Microphone (source): {state}")
                    break
        except Exception:
            pass

    return "\n".join(lines)


# ── MCP Server ──────────────────────────────────────────────────────────────

app = Server("jabra-voice-ears")


@app.list_tools()
async def list_tools():
    return [
        Tool(
            name="voice_speak",
            description=(
                "Speak text aloud through the Jabra SPEAK 510 USB speaker. "
                "Uses Microsoft edge-tts for natural-sounding speech synthesis."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The text to speak aloud",
                    },
                },
                "required": ["text"],
            },
        ),
        Tool(
            name="voice_clone",
            description=(
                "Clone a voice from reference audio and speak text in that voice. "
                "Sends reference audio to RunPod GPU (fast Qwen3-TTS inference). "
                "Requires RunPod configured in ~/.hermes/jabra-runpod.env. "
                "Falls back to slow local CPU if RunPod unavailable."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The text to speak in the cloned voice",
                    },
                    "ref_audio": {
                        "type": "string",
                        "description": (
                            "Absolute path to a short WAV/MP3 reference audio clip "
                            "of the target voice (3-10 seconds recommended)"
                        ),
                    },
                    "ref_text": {
                        "type": "string",
                        "description": (
                            "Optional transcript of what is said in the reference audio. "
                            "Providing this improves cloning quality (ICL mode)."
                        ),
                    },
                },
                "required": ["text", "ref_audio"],
            },
        ),
        Tool(
            name="voice_play",
            description=(
                "Play an audio file (WAV, MP3, OGG, etc.) through the "
                "Jabra SPEAK 510 USB speaker."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute path to the audio file",
                    },
                },
                "required": ["path"],
            },
        ),
        Tool(
            name="voice_stop",
            description="Stop any audio currently playing through the Jabra speaker.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="ears_listen",
            description=(
                "Listen through the Jabra SPEAK 510 USB microphone and "
                "transcribe what is heard. Returns the recognized text."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "duration_seconds": {
                        "type": "integer",
                        "description": "How many seconds to listen (default: 5, max: 60)",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 60,
                    },
                },
            },
        ),
        Tool(
            name="ears_status",
            description=(
                "Check whether the Jabra SPEAK 510 USB is connected "
                "and report its speaker/mic state."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list:
    if name == "voice_speak":
        text = arguments.get("text", "")
        result = await _tts_and_play(text)
        return [TextContent(type="text", text=result)]

    elif name == "voice_clone":
        text = arguments.get("text", "")
        ref_audio = arguments.get("ref_audio", "")
        ref_text = arguments.get("ref_text", "")
        # Try RunPod first, fall back to local CPU
        result = await _voice_clone_via_runpod(text, ref_audio, ref_text)
        if "RunPod not configured" in result or "RunPod request failed" in result:
            result = await _voice_clone_local_fallback(text, ref_audio, ref_text)
        return [TextContent(type="text", text=result)]

    elif name == "voice_play":
        path = arguments.get("path", "")
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _play_audio_file, path)
        return [TextContent(type="text", text=result)]

    elif name == "voice_stop":
        loop = asyncio.get_running_loop()
        loop.run_in_executor(None, _stop_playback)
        return [TextContent(type="text", text="Playback stopped")]

    elif name == "ears_listen":
        duration = arguments.get("duration_seconds", 5)
        duration = max(1, min(60, duration))
        result = await _stt_from_mic(duration)
        return [TextContent(type="text", text=result)]

    elif name == "ears_status":
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _device_status)
        return [TextContent(type="text", text=result)]

    else:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
