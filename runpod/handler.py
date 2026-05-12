#!/usr/bin/env python3
"""
RunPod Serverless handler for Qwen3-TTS voice cloning.

Accepts:
  {
    "text": "Hello world",              # text to synthesize
    "mode": "clone" | "preset",         # voice cloning or preset speaker
    "ref_audio_b64": "<base64 wav>",    # reference audio for cloning (mode=clone)
    "ref_text": "transcript",           # transcript of reference audio (mode=clone, optional)
    "speaker": "Vivian",                # preset speaker name (mode=preset)
    "language": "english"               # english, chinese, japanese, korean
  }

Returns:
  {
    "audio_b64": "<base64 wav>",
    "sample_rate": 24000,
    "duration_seconds": 2.5
  }
"""

import base64
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

MODEL_DIR = Path("/models")
BASE_MODEL = MODEL_DIR / "Qwen3-TTS-12Hz-0.6B-Base"
CUSTOMVOICE_MODEL = MODEL_DIR / "Qwen3-TTS-12Hz-0.6B-CustomVoice"
BIN_DIR = Path("/app/bin")
TTS_BIN = BIN_DIR / "tts"
VOICE_CLONE_BIN = BIN_DIR / "voice_clone"

# Speakers available in CustomVoice model
SPEAKERS = {
    "vivian", "serena", "ryan", "aiden",
    "uncle_fu", "ono_anna", "sohee", "eric", "dylan"
}

LANGUAGES = {"english", "chinese", "japanese", "korean"}


def handler(job):
    """RunPod handler entry point."""
    job_input = job.get("input", {})
    
    text = job_input.get("text", "").strip()
    if not text:
        return {"error": "No text provided"}
    
    mode = job_input.get("mode", "preset")
    language = job_input.get("language", "english")
    
    if language not in LANGUAGES:
        language = "english"
    
    try:
        if mode == "clone":
            return _handle_clone(job_input, text, language)
        else:
            return _handle_preset(job_input, text, language)
    except Exception as e:
        return {"error": str(e)}


def _handle_preset(job_input, text, language):
    """Generate speech with a preset speaker."""
    speaker = job_input.get("speaker", "Vivian")
    speaker_lower = speaker.lower().replace(" ", "_")
    
    if speaker_lower not in SPEAKERS:
        # Map common names
        name_map = {
            "alloy": "serena", "echo": "ryan", "fable": "vivian",
            "onyx": "eric", "nova": "ono_anna", "shimmer": "sohee",
        }
        speaker_lower = name_map.get(speaker_lower, "vivian")
    
    # Capitalize for the binary (Vivian, Ryan, etc.)
    display_speaker = speaker_lower.replace("_", " ").title().replace(" ", "_")
    
    output_path = "/tmp/output.wav"
    
    cmd = [
        str(TTS_BIN),
        str(CUSTOMVOICE_MODEL),
        text,
        display_speaker,
        language,
    ]
    
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = "/app/libtorch/lib:" + env.get("LD_LIBRARY_PATH", "")
    
    t0 = time.time()
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        cwd="/tmp",
    )
    elapsed = time.time() - t0
    
    if not os.path.exists(output_path):
        return {
            "error": "TTS binary produced no output",
            "stderr": result.stderr[-500:] if result.stderr else "",
        }
    
    return _encode_result(output_path, elapsed)


def _handle_clone(job_input, text, language):
    """Generate speech with voice cloning from reference audio."""
    ref_audio_b64 = job_input.get("ref_audio_b64", "")
    ref_text = job_input.get("ref_text", "").strip()
    
    if not ref_audio_b64:
        return {"error": "No reference audio provided for voice cloning"}
    
    # Decode reference audio
    ref_path = "/tmp/ref_audio.wav"
    try:
        audio_bytes = base64.b64decode(ref_audio_b64)
        with open(ref_path, "wb") as f:
            f.write(audio_bytes)
    except Exception as e:
        return {"error": f"Invalid reference audio: {e}"}
    
    # Resample to 24kHz mono 16-bit if needed
    resampled_path = "/tmp/ref_audio_24k.wav"
    result = subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", ref_path,
            "-ac", "1", "-ar", "24000", "-sample_fmt", "s16",
            resampled_path,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        return {"error": f"Failed to resample audio: {result.stderr}"}
    
    ref_path = resampled_path
    
    output_path = "/tmp/output_voice_clone.wav"
    
    cmd = [
        str(VOICE_CLONE_BIN),
        str(BASE_MODEL),
        ref_path,
        text,
        language,
    ]
    if ref_text:
        cmd.append(ref_text)
    
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = "/app/libtorch/lib:" + env.get("LD_LIBRARY_PATH", "")
    
    t0 = time.time()
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        cwd="/tmp",
    )
    elapsed = time.time() - t0
    
    # voice_clone outputs to output_voice_clone.wav
    if not os.path.exists(output_path):
        return {
            "error": "Voice clone binary produced no output",
            "stderr": result.stderr[-500:] if result.stderr else "",
        }
    
    return _encode_result(output_path, elapsed)


def _encode_result(wav_path, elapsed):
    """Read WAV file and return base64-encoded result."""
    with open(wav_path, "rb") as f:
        audio_bytes = f.read()
    
    # Calculate duration (rough: WAV header + 16-bit samples)
    file_size = len(audio_bytes)
    if file_size > 44:
        data_size = file_size - 44
        duration = data_size / (24000 * 2)  # 16-bit mono = 2 bytes per sample
    else:
        duration = 0
    
    return {
        "audio_b64": base64.b64encode(audio_bytes).decode("utf-8"),
        "sample_rate": 24000,
        "duration_seconds": round(duration, 1),
        "inference_time_seconds": round(elapsed, 1),
    }


# RunPod serverless entry point
if __name__ == "__main__":
    import runpod
    runpod.serverless.start({"handler": handler})
