# Qwen3-TTS RunPod Serverless

Voice cloning via Qwen3-TTS on RunPod GPU.

## Deploy (GitHub method)

1. Push this directory to a GitHub repo
2. In RunPod Console → Serverless → New Endpoint:
   - **Deploy from:** GitHub
   - **Repository:** your-username/your-repo
   - **Dockerfile path:** runpod/Dockerfile
   - **GPU:** T4 (16GB) — or A10G for faster inference
   - **Min replicas:** 0 (scale to zero, no idle cost)
   - **Max replicas:** 1
   - **Idle timeout:** 300s
   - **Execution timeout:** 120s
3. Copy the Endpoint ID
4. Fill in `~/.hermes/jabra-runpod.env`:
   ```
   RUNPOD_ENDPOINT_ID=your-endpoint-id
   RUNPOD_API_KEY=rk_your-api-key
   ```

First build takes ~10 min (downloads models). Subsequent cold starts: ~30s.

## API

The handler accepts `{"input": {...}}` — see `handler.py` for the full schema.

## Test locally (optional)

```bash
docker build -t qwen3-tts-runpod .
docker run --rm -p 8080:8080 qwen3-tts-runpod
```
