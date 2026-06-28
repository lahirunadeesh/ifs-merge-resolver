#!/usr/bin/env bash
# Build IFS Merge Conflict Resolver into a standalone app.
# Run from the project root: bash build.sh

set -e

echo "==> Installing dependencies..."
pip3 install -r requirements.txt pyinstaller

echo "==> Cleaning previous build..."
rm -rf build dist

echo "==> Running PyInstaller..."
pyinstaller build.spec

echo ""
echo "==> Build complete!"
echo "    Mac app : dist/IFSMergeResolver.app"
echo "    Folder  : dist/IFSMergeResolver/"
echo ""
echo "To run: open dist/IFSMergeResolver.app"
