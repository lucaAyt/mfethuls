#!/usr/bin/env bash
# Pull raw data and registry CSV from OneDrive into the Droplet block volume.
# Requires rclone configured with an 'onedrive' remote (see docs/deployment.md).
# Called by POST /sync — also safe to run manually.
set -euo pipefail

REMOTE="${RCLONE_REMOTE:-onedrive}"
SOURCE="${RCLONE_SOURCE_PATH:-Documents/raw}"
DEST="${DATA_ROOT:-/mnt/mfethuls-data}"
REGISTRY_SRC="${RCLONE_REGISTRY_PATH:-Documents/experiments_template.csv}"

echo "[sync] Raw data: ${REMOTE}:${SOURCE}/ → ${DEST}/"
rclone sync "${REMOTE}:${SOURCE}/" "${DEST}/" \
  --exclude "*.tmp" --exclude ".~lock.*" --log-level INFO

echo "[sync] Registry: ${REMOTE}:${REGISTRY_SRC} → ${DEST}/"
rclone copy "${REMOTE}:${REGISTRY_SRC}" "${DEST}/" --log-level INFO

echo "[sync] Done."
