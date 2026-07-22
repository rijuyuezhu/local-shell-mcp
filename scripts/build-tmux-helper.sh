#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "usage: $0 OUTPUT_PATH [linux/amd64|linux/arm64]" >&2
  exit 2
fi

output_path=$1
platform=${2:-}
if [[ -z "$platform" ]]; then
  case "$(uname -m)" in
    x86_64|amd64) platform=linux/amd64 ;;
    aarch64|arm64) platform=linux/arm64 ;;
    *) echo "unsupported Linux architecture: $(uname -m)" >&2; exit 2 ;;
  esac
fi

case "$platform" in
  linux/amd64|linux/arm64) ;;
  *) echo "unsupported helper platform: $platform" >&2; exit 2 ;;
esac

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
tmp_dir=$(mktemp -d)
container_id=
image_tag=
cleanup() {
  if [[ -n "$container_id" ]]; then docker rm -f "$container_id" >/dev/null 2>&1 || true; fi
  if [[ -n "$image_tag" ]]; then docker image rm -f "$image_tag" >/dev/null 2>&1 || true; fi
  rm -rf "$tmp_dir"
}
trap cleanup EXIT

mkdir -p "$(dirname "$output_path")"
if docker buildx version >/dev/null 2>&1; then
  docker buildx build \
    --platform "$platform" \
    --file "$repo_root/scripts/tmux-helper.Dockerfile" \
    --output "type=local,dest=$tmp_dir/out" \
    "$repo_root"
else
  case "$(uname -m):$platform" in
    x86_64:linux/amd64|amd64:linux/amd64|aarch64:linux/arm64|arm64:linux/arm64) ;;
    *)
      echo "Docker Buildx is required to build $platform on $(uname -m)" >&2
      exit 2
      ;;
  esac
  image_tag="local-shell-mcp-tmux-helper:local-$$"
  docker build \
    --file "$repo_root/scripts/tmux-helper.Dockerfile" \
    --tag "$image_tag" \
    "$repo_root"
  container_id=$(docker create "$image_tag" /tmux -V)
  docker cp "$container_id:/tmux" "$tmp_dir/out-tmux"
  mkdir -p "$tmp_dir/out"
  mv "$tmp_dir/out-tmux" "$tmp_dir/out/tmux"
fi

install -m 0755 "$tmp_dir/out/tmux" "$output_path"
"$output_path" -V
