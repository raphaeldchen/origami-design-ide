#!/usr/bin/env bash
#
# build_linter.sh — fetch Oriedita and compile the headless validator wrapper.
#
# Oriedita has no validation CLI, so we compile OrieditaValidator.java against
# Oriedita's prebuilt shaded release jar (which bundles origami.*, the fold.io
# FOLD parser, tinylog, and jakarta annotations — everything the wrapper links).
#
# Idempotent: the jar is downloaded only if missing. Re-run any time.
#
# Requires: a JDK on PATH (javac). Tested with Temurin 17.
#   ./build_linter.sh

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ORIEDITA_VERSION="1.1.3"
JAR_DIR="${HERE}/oriedita"
JAR="${JAR_DIR}/oriedita-${ORIEDITA_VERSION}.jar"
JAR_URL="https://github.com/oriedita/oriedita/releases/download/v${ORIEDITA_VERSION}/oriedita-${ORIEDITA_VERSION}.jar"

mkdir -p "${JAR_DIR}"

if [[ ! -f "${JAR}" ]]; then
    echo "Downloading Oriedita ${ORIEDITA_VERSION} (~15 MB)..."
    curl -fSL -o "${JAR}" "${JAR_URL}"
else
    echo "Oriedita jar already present: ${JAR}"
fi

# Sanity-check the jar contains the classes we link against. Capture the listing
# first so grep closing the pipe early can't trip `set -o pipefail` (SIGPIPE).
JAR_LISTING="$(unzip -l "${JAR}" 2>/dev/null || true)"
if ! grep -q "origami/crease_pattern/worker/foldlineset/Check4.class" <<<"${JAR_LISTING}"; then
    echo "ERROR: ${JAR} does not contain the expected Oriedita classes." >&2
    exit 1
fi

echo "Compiling OrieditaValidator.java..."
javac -cp "${JAR}" -d "${HERE}" "${HERE}/OrieditaValidator.java"

echo "Done. Built ${HERE}/OrieditaValidator.class"
echo "Smoke test:  java -cp \"${JAR}:${HERE}\" OrieditaValidator some.fold"
