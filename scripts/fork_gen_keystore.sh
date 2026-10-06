#!/usr/bin/env bash
# Create the release signing keystore for this fork and print the GitHub
# secrets that have to be configured.
#
# Usage:
#   scripts/fork_gen_keystore.sh [output-dir]
#
# Then (once per machine):
#   gh secret set FORK_KEYSTORE_B64          --body "$(base64 -w0 fork-keys/fork-release.jks)"
#   gh secret set FORK_KEYSTORE_PASSWORD     --body "$STORE_PASS"
#   gh secret set FORK_KEY_ALIAS             --body "$ALIAS"
#   gh secret set FORK_KEY_PASSWORD          --body "$STORE_PASS"
#
# Keep fork-keys/ private: it is what lets an installed fork build be updated.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${1:-fork-keys}"
ALIAS="${FORK_KEY_ALIAS:-fork-release}"
STORE_PASS="${FORK_KEYSTORE_PASSWORD:-$(head -c 32 /dev/urandom | base64 | tr -d '/+=' | cut -c1-24)}"
KEY_PASS="${FORK_KEY_PASSWORD:-$STORE_PASS}"
KEYSTORE="$OUT_DIR/fork-release.jks"
# the DN ends up in every signature block, so it must not name upstream
PROJECT_NAME="$(awk -F= '/^PROJECT_NAME=/{print $2}' "$ROOT/fork/fork.env" 2>/dev/null | tr -d '[:space:]')"
DN="${FORK_KEY_DN:-CN=${PROJECT_NAME:-release} release, OU=release, O=${PROJECT_NAME:-fork}, C=CN}"

KEYTOOL="$(command -v keytool || true)"
if [ -z "$KEYTOOL" ] && [ -n "${JAVA_HOME:-}" ] && [ -x "$JAVA_HOME/bin/keytool" ]; then
    KEYTOOL="$JAVA_HOME/bin/keytool"
fi
if [ -z "$KEYTOOL" ]; then
    echo "keytool not found: install a JDK 21 or export JAVA_HOME" >&2
    exit 1
fi

mkdir -p "$OUT_DIR"
if [ -f "$KEYSTORE" ]; then
    echo "$KEYSTORE already exists, refusing to overwrite it" >&2
    exit 1
fi

"$KEYTOOL" -genkeypair \
    -keystore "$KEYSTORE" \
    -storetype JKS \
    -alias "$ALIAS" \
    -keyalg RSA \
    -keysize 4096 \
    -validity 10950 \
    -storepass "$STORE_PASS" \
    -keypass "$KEY_PASS" \
    -dname "$DN" \
    -noprompt

cat <<EOF

keystore : $KEYSTORE
subject  : $DN
alias    : $ALIAS
password : $STORE_PASS  (used for both storePassword and keyPassword)

configure the repository secrets with:

  gh secret set FORK_KEYSTORE_B64      --body "\$(base64 -w0 $KEYSTORE)"
  gh secret set FORK_KEYSTORE_PASSWORD --body "$STORE_PASS"
  gh secret set FORK_KEY_ALIAS         --body "$ALIAS"
  gh secret set FORK_KEY_PASSWORD      --body "$KEY_PASS"

back $KEYSTORE up somewhere safe and do not commit it.
EOF
