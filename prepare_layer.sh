#!/bin/bash
set -e

# Create layer directory structure
# Lambda layers for Python need to be in a 'python' directory to be importable
echo "Preparing shared layer..."
rm -rf shared_layer
mkdir -p shared_layer/python/shared

# Copy shared code
# We explicitly copy contents to avoid nesting shared/shared
cp -r shared/* shared_layer/python/shared/

# Create an __init__.py if it doesn't exist in the root of the layer (it should exist in shared/)
# But we need to make sure 'shared' is treated as a package
touch shared_layer/python/shared/__init__.py

echo "Shared layer prepared in shared_layer/python/shared"
