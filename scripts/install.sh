#!/usr/bin/env bash
# Install hermes-clinepass into the local Hermes plugins directory.
set -euo pipefail

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
DEST="$HERMES_HOME/plugins/model-providers/clinepass"
REPO_URL="${HERMES_CLINEPASS_URL:-https://github.com/Adolanium/hermes-clinepass.git}"
TMP="$(mktemp -d)"

cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

echo "Installing ClinePass plugin -> $DEST"
git clone --depth 1 "$REPO_URL" "$TMP/hermes-clinepass"
mkdir -p "$(dirname "$DEST")"
rm -rf "$DEST"
cp -R "$TMP/hermes-clinepass/clinepass" "$DEST"

echo
echo "Done."
echo
echo "Next:"
echo "  1. Add CLINE_API_KEY to $HERMES_HOME/.env"
echo "  2. hermes chat -q \"hi\" --provider clinepass -m cline-pass/kimi-k3"
echo
