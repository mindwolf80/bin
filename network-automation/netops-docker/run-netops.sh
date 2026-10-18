#!/bin/bash
# Run the NetOps Alpine container (GHCR) with proxy auto-detection
# Always pull the latest tag before running

IMAGE="ghcr.io/mindwolf80/netops-alpine:latest"
WORKDIR="${WORKDIR:-/srv/netops}"

# Prompt for proxies if unset
[ -z "$HTTP_PROXY" ]  && read -rp "Enter HTTP proxy (or blank): "  HTTP_PROXY
[ -z "$HTTPS_PROXY" ] && read -rp "Enter HTTPS proxy (or blank): " HTTPS_PROXY
if [ -z "$NO_PROXY" ]; then
  read -rp "Enter NO_PROXY [default: localhost,127.0.0.1,10.0.0.0/8,*.company.com]: " NO_PROXY
  NO_PROXY=${NO_PROXY:-localhost,127.0.0.1,10.0.0.0/8,*.company.com}
fi

echo -e "\nUsing proxies:\n  HTTP_PROXY=$HTTP_PROXY\n  HTTPS_PROXY=$HTTPS_PROXY\n  NO_PROXY=$NO_PROXY\n"

# Ensure workspace
mkdir -p "$WORKDIR"/{scripts,data/outputs}

# Make sure Docker is present
command -v docker >/dev/null 2>&1 || { echo "Docker not found."; exit 1; }

# Always pull the latest tag
echo "Pulling $IMAGE ..."
docker pull "$IMAGE" || { echo "Pull failed."; exit 1; }

# Run container with bind mount and proxies
exec docker run --rm -it --pull=always \
  -e HTTP_PROXY="$HTTP_PROXY" \
  -e HTTPS_PROXY="$HTTPS_PROXY" \
  -e NO_PROXY="$NO_PROXY" \
  -v "$WORKDIR":/work \
  "$IMAGE" \
  bash
