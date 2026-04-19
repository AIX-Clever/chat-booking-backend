#!/bin/bash

# Configuration
SOURCE_DIR="./shared"
TARGET_DIR="../chat-booking-layers/layer/python/shared"

# Check if target directory exists
if [ ! -d "$TARGET_DIR" ]; then
    echo "Error: Target directory $TARGET_DIR does not exist."
    echo "Make sure chat-booking-layers is cloned in the same parent directory as chat-booking-backend."
    exit 1
fi

echo "Syncing shared modules from backend to layers..."

# Create target directory if it doesn't exist (layer/python/shared)
mkdir -p "$TARGET_DIR"

# Copy all contents from shared to target
# -r: recursive
# -v: verbose
# -p: preserve attributes
cp -rp "$SOURCE_DIR"/* "$TARGET_DIR/"

# Ensure all __init__.py files are created in both sides if missing
find "$SOURCE_DIR" -type d -not -path "*/.*" -not -path "*/__pycache__*" | while read dir; do
    if [ ! -f "$dir/__init__.py" ]; then
        echo "Adding missing __init__.py to $dir"
        touch "$dir/__init__.py"
    fi
done

# Repeat for target to be safe
find "$TARGET_DIR" -type d -not -path "*/.*" -not -path "*/__pycache__*" | while read dir; do
    if [ ! -f "$dir/__init__.py" ]; then
        echo "Adding missing __init__.py to $dir"
        touch "$dir/__init__.py"
    fi
done

echo "Sync complete! Don't forget to push changes in chat-booking-layers if needed."
