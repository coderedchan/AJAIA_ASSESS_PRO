#!/bin/sh
# Rebuilds relay/static/vendor/tiptap.bundle.js inside a Node container,
# so the app itself never needs Node installed.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
docker run --rm -v "$ROOT/editor-build:/build" -v "$ROOT/relay/static/vendor:/out" -w /build node:22-alpine \
  sh -c "npm install --no-audit --no-fund && npx esbuild entry.js --bundle --format=esm --minify --outfile=/out/tiptap.bundle.js"
