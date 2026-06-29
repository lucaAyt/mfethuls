#!/usr/bin/env bash
# Bootstrap a fresh Ubuntu 24.04 Droplet for mfethuls cloud deployment.
# Run as root: bash scripts/vm_setup.sh
set -euo pipefail

echo "=== mfethuls VM Setup ==="
echo

# ── Docker ────────────────────────────────────────────────────────────────────
echo "Installing Docker..."
apt-get update -qq
apt-get install -y -qq ca-certificates curl gnupg

install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
    > /etc/apt/sources.list.d/docker.list

apt-get update -qq
apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin

docker run --rm hello-world > /dev/null 2>&1 && echo "Docker OK"

# ── Tailscale ─────────────────────────────────────────────────────────────────
echo "Installing Tailscale..."
curl -fsSL https://tailscale.com/install.sh | sh
echo "Tailscale installed. Run 'tailscale up' after this script to join the tailnet."

# ── Data volume ───────────────────────────────────────────────────────────────
echo "Setting up data directory..."
DATA_DIR=/mnt/mfethuls-data

# Check whether a block volume is attached and not yet mounted
DEVICE=$(lsblk -rno NAME,MOUNTPOINT | awk '$2=="" && $1!="sda" && $1!="sr0" {print "/dev/"$1; exit}')
if [ -n "$DEVICE" ] && [ -b "$DEVICE" ]; then
    echo "Found unformatted device: $DEVICE"
    echo "Formatting and mounting at $DATA_DIR..."
    mkfs.ext4 -F "$DEVICE"
    mkdir -p "$DATA_DIR"
    mount "$DEVICE" "$DATA_DIR"
    echo "$DEVICE $DATA_DIR ext4 defaults,nofail 0 2" >> /etc/fstab
    echo "Block volume mounted at $DATA_DIR (persists across reboots)"
else
    echo "No unformatted block volume found — using local directory at $DATA_DIR."
    echo "Attach a DO Volume before running this script if you want persistent block storage."
    mkdir -p "$DATA_DIR"
fi

mkdir -p "$DATA_DIR/DSC"
mkdir -p "$DATA_DIR/TGA"
mkdir -p "$DATA_DIR/NMR"
mkdir -p "$DATA_DIR/UV_Vis"
mkdir -p "$DATA_DIR/FTIR"
mkdir -p "$DATA_DIR/SEC"
mkdir -p "$DATA_DIR/Rheology"
mkdir -p "$DATA_DIR/DMA"

# ── Done ──────────────────────────────────────────────────────────────────────
echo
echo "=== Setup complete ==="
echo
echo "Next steps:"
echo "  1. tailscale up                         # join the lab tailnet"
echo "  2. cd /opt && git clone <repo> mfethuls"
echo "  3. cd /opt/mfethuls"
echo "  4. cp env_example .env && nano .env      # fill in credentials"
echo "  5. docker compose up --build -d"
echo "  6. curl http://localhost:8000/health      # should return {\"status\": \"ok\"}"
echo
echo "Then rsync your data:"
echo "  rsync -avz /local/data/ root@<tailscale-ip>:$DATA_DIR/"
