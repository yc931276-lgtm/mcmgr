#!/usr/bin/env bash
# Build the architecture-neutral package plus explicit ARM variants.
#
#   ./packaging/deb/build-all.sh                 # all, arm64, armhf
#   ARCHES="all arm64" ./packaging/deb/build-all.sh
#   OUT=/tmp/deb ./packaging/deb/build-all.sh
#
# All packages contain the same pure-Python payload; only the Architecture
# control field (and therefore the installability) differs.  The build stamp
# is taken once so every artifact reports the same build time.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ARCHES="${ARCHES:-all arm64 armhf}"

python3 "$ROOT/tools/stamp_build.py" >/dev/null

for arch in $ARCHES; do
  ARCH="$arch" SKIP_STAMP=1 "$ROOT/packaging/deb/build-deb.sh"
done
