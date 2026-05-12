#!/bin/bash
# Local Docker build (for testing before GitHub deploy).
# For production, push to GitHub and deploy via RunPod Console → GitHub.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
IMAGE_NAME="qwen3-tts-runpod:0.6B-v1"

echo "=== Building Docker image (this will take 10+ min on first run) ==="
# Build from project root (same context as RunPod GitHub deploy)
docker build -t "$IMAGE_NAME" -f "$SCRIPT_DIR/Dockerfile" "$SCRIPT_DIR/.."

echo ""
echo "=== Image built: $IMAGE_NAME ==="
echo ""
echo "To test locally:"
echo "  docker run --rm $IMAGE_NAME"
echo ""
echo "To deploy to RunPod from GitHub:"
echo "  1. Push this repo to GitHub"
echo "  2. RunPod Console → Serverless → New Endpoint → Deploy from GitHub"
echo "  3. Point to your repo, Dockerfile path: runpod/Dockerfile"
echo "  4. GPU: T4, 0 min replicas, 300s idle timeout, 120s execution timeout"
echo ""
echo "To push to a container registry instead:"
echo "  docker tag $IMAGE_NAME <registry>/$IMAGE_NAME"
echo "  docker push <registry>/$IMAGE_NAME"
