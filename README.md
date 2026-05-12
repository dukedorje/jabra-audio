# jabra-audio

Play and record audio through the Jabra SPEAK 510 USB speaker/mic.

## Architecture

```
jabra-audio/
├── README.md
├── mcp-server.py          # MCP server — exposes voice/ears tools
├── scripts/               # Standalone utility scripts
└── notes/                 # Reference material
```

```
                    ┌─────────────────┐
                    │   Hermes Agent   │
                    └────────┬────────┘
                             │ MCP protocol (stdio)
                    ┌────────▼────────┐
                    │  mcp-server.py   │
                    │  (voice & ears)  │
                    └──┬──────────┬───┘
               voice   │          │   ears
           ┌───────────▼─┐   ┌────▼───────────┐
           │  edge-tts    │   │  faster-whisper │
           │  (TTS)       │   │  (STT)          │
           └──────┬───────┘   └────┬────────────┘
                  │                │
           ┌──────▼────────────────▼──────┐
           │     ffmpeg → aplay | parec   │
           └──────────────┬───────────────┘
                          │
                   ┌──────▼──────┐
                   │    Jabra    │
                   │ SPEAK 510   │
                   │    USB      │
                   └─────────────┘
```

## Device

- **Model:** Jabra SPEAK 510 USB
- **ALSA card:** `hw:3,0` (playback + capture)
- **PipeWire:** sink `alsa_output.usb-0b0e_Jabra_SPEAK_510_USB_...`, source `alsa_input.usb-0b0e_Jabra_SPEAK_510_USB_...`
- **Audio system:** PipeWire

## MCP Tools

Registered as `mcp_jabra_*` when Hermes restarts:

| Tool | Description |
|------|-------------|
| `voice_speak(text)` | TTS text → Jabra speaker |
| `voice_play(path)` | Play audio file → Jabra speaker |
| `voice_stop()` | Stop current playback |
| `ears_listen(secs)` | Record mic → STT → return text |
| `ears_status()` | Check Jabra connectivity |

## Skills

Two Hermes skills document usage:
- `voice` — speaking through the Jabra speaker
- `ears` — listening through the Jabra microphone

## Dependencies

All in Hermes venv (`~/.hermes/hermes-agent/venv/`):
- `mcp` 1.27.0 — MCP protocol
- `fastmcp` 3.2.3 — MCP helpers
- `edge-tts` 7.2.8 — text-to-speech (Microsoft free API)
- `faster-whisper` 1.2.1 — speech-to-text (local, offline)
- System: `ffmpeg`, `aplay`, `parec` (PipeWire)

## Quick test (manual)

```bash
# Speak
python -m edge_tts --voice en-US-JennyNeural --text "hello" --write-media /tmp/t.mp3
ffmpeg -loglevel quiet -i /tmp/t.mp3 -f wav -ac 2 -ar 48000 - | aplay -D hw:3,0 -q

# Listen
parec --device <jabra-source> --format=s16le --rate=16000 --channels=1 --file-format=wav /tmp/r.wav
python -c "from faster_whisper import WhisperModel; m=WhisperModel('base','cpu','int8'); print([s.text for s in m.transcribe('/tmp/r.wav')[0]])"
```

## Startup

The MCP server is auto-started by Hermes on gateway restart (see `mcp_servers` in `~/.hermes/config.yaml`). After restart, tools appear as `mcp_jabra_voice_*` and `mcp_jabra_ears_*`.
