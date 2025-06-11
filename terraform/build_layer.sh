#!/bin/bash
set -e

# This script prepares the Python dependencies for the Lambda layer.

# Output zip file for the layer
OUTPUT_FILE="dependencies.zip"
# Directory where dependencies will be installed, following Lambda's expected structure
LAYER_DIR="python"

# Clean up previous build artifacts
rm -rf ${LAYER_DIR} ${OUTPUT_FILE}

# Create the directory structure for the layer
mkdir -p ${LAYER_DIR}

echo "Installing dependencies from ../camp_sync/requirements.txt..."

# Install packages from requirements.txt into the python directory
pip install \
    --platform manylinux2014_x86_64 \
    --target "${LAYER_DIR}" \
    --implementation cp \
    --python-version 3.9 \
    --only-binary=:all: \
    -r ../camp_sync/requirements.txt

echo "Creating zip file for the Lambda layer..."

# Zip the dependencies
zip -r ${OUTPUT_FILE} ${LAYER_DIR}

echo "Cleaning up temporary directory..."
rm -rf ${LAYER_DIR}

echo "Lambda layer zip file created successfully: ${OUTPUT_FILE}" 