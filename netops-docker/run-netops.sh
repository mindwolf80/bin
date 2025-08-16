#!/bin/bash
# Run the NetOps Alpine container with proxy auto-detection
IMAGE="netops-alpine:1.0"
WORKDIR="/srv/netops"

[ -z "$HTTP_PROXY" ] && read -rp "Enter HTTP proxy (or blank): " HTTP_PROXY
[ -z "$HTTPS_PROXY" ] && read -rp "Enter HTTPS proxy (or blank): " HTTPS_PROXY
if [ -z "$NO_PROXY" ]; then
  read -rp "Enter NO_PROXY [default: localhost,127.0.0.1,10.0.0.0/8,*.company.com]: " NO_PROXY
  NO_PROXY=${NO_PROXY:-localhost,127.0.0.1,10.0.0.0/8,*.company.com}
fi

echo
echo "Using proxies:"
echo "  HTTP_PROXY=$HTTP_PROXY"
echo "  HTTPS_PROXY=$HTTPS_PROXY"
echo "  NO_PROXY=$NO_PROXY"
echo

mkdir -p "$WORKDIR"/{scripts,data/outputs}

docker run --rm -it \
  -e HTTP_PROXY="$HTTP_PROXY" \
  -e HTTPS_PROXY="$HTTPS_PROXY" \
  -e NO_PROXY="$NO_PROXY" \
  -v "$WORKDIR":/work \
  "$IMAGE" \
  /bin/bash