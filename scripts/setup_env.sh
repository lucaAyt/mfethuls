#!/bin/bash
echo "=== mfethuls First-Run Setup ==="
echo
echo "Please enter the paths below. These will be saved to .env in this folder."
echo

read -rp "Path to raw instrument data folder: " DATA_PATH
if [ -z "$DATA_PATH" ]; then
    echo "PATH_TO_DATA is required."
    exit 1
fi

read -rp "Path to registry CSV file: " REGISTRY_PATH
if [ -z "$REGISTRY_PATH" ]; then
    echo "PATH_TO_REGISTRY is required."
    exit 1
fi

read -rp "Path for processed storage [./mfethuls_storage]: " STORAGE_PATH
STORAGE_PATH="${STORAGE_PATH:-./mfethuls_storage}"

cat > .env << EOF
PATH_TO_DATA=$DATA_PATH
PATH_TO_REGISTRY=$REGISTRY_PATH
PATH_TO_LOCAL_STORAGE=$STORAGE_PATH
EOF

echo
echo "Configuration saved to .env"
