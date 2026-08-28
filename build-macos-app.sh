#!/usr/bin/env bash
# Build a native macOS bundle for Access Log Analyzer.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="Access Log Analyzer"
APP_BUNDLE="$PROJECT_DIR/dist/$APP_NAME.app"

cd "$PROJECT_DIR"

uv run pyinstaller \
  --noconfirm \
  --windowed \
  --name "$APP_NAME" \
  --icon "AppIcon.icns" \
  --add-data "app-logo.png:." \
  app.py

printf '\nBuilt native app bundle:\n%s\n' "$APP_BUNDLE"
printf 'Install it with:\ncp -R "%s" /Applications/\n' "$APP_BUNDLE"
