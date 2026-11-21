#!/usr/bin/env bash
# Build a Debian package for mcmgr (pure Python).
#
#   ./packaging/deb/build-deb.sh                 # -> dist/mcmgr_<version>_all.deb
#   ARCH=arm64 ./packaging/deb/build-deb.sh      # -> dist/mcmgr_<version>_arm64.deb
#   OUT=/tmp/deb ./packaging/deb/build-deb.sh    # -> /tmp/deb/...
#   SKIP_STAMP=1 ./packaging/deb/build-deb.sh    # reuse the existing build stamp
#
# ARCH may be all (default), amd64, arm64 or armhf.  The package is pure
# Python, so every architecture can be produced on any host; the field only
# declares where dpkg is allowed to install it.  Use ARCH=all for a single
# package that works on every architecture.
#
# The package installs:
#   /usr/bin/mcmgr                      wrapper (python3 -m mcmgr)
#   /usr/lib/mcmgr/mcmgr/               the Python package
#   /usr/share/doc/mcmgr/               README, changelog, copyright
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="${OUT:-$ROOT/dist}"
ARCH="${ARCH:-all}"
MAINTAINER="${MAINTAINER:-heaway <heaway@localhost>}"

case "$ARCH" in
  all|amd64|arm64|armhf) ;;
  *)
    echo "build-deb: unsupported ARCH '$ARCH' (use all, amd64, arm64 or armhf)" >&2
    exit 2
    ;;
esac

version="$(cd "$ROOT" && python3 -c 'import mcmgr; print(mcmgr.__version__)')"
package="mcmgr_${version}_${ARCH}.deb"

if [[ "${SKIP_STAMP:-0}" != "1" ]]; then
  python3 "$ROOT/tools/stamp_build.py" >/dev/null
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
stage="$work/stage"

install -d "$stage/DEBIAN" \
  "$stage/usr/bin" \
  "$stage/usr/lib/mcmgr" \
  "$stage/usr/share/doc/mcmgr"

# Python package (drop caches so the .deb stays deterministic).
cp -a "$ROOT/mcmgr" "$stage/usr/lib/mcmgr/"
find "$stage/usr/lib/mcmgr" -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$stage/usr/lib/mcmgr" -name '*.pyc' -delete
# Sources may live in a tree with restrictive umasks; the package must be readable.
find "$stage/usr/lib/mcmgr" -type f -exec chmod 0644 {} +
find "$stage/usr/lib/mcmgr" -type d -exec chmod 0755 {} +

install -m 0755 "$ROOT/packaging/deb/mcmgr-launcher" "$stage/usr/bin/mcmgr"
install -m 0644 "$ROOT/README.md" "$stage/usr/share/doc/mcmgr/README.md"
install -m 0644 "$ROOT/packaging/deb/copyright" "$stage/usr/share/doc/mcmgr/copyright"

# Debian changelog, derived from the current version.
{
  printf 'mcmgr (%s) unstable; urgency=medium\n\n' "$version"
  printf '  * Release %s.\n\n' "$version"
  printf ' -- %s  %s\n' "$MAINTAINER" "$(date -R)"
} | gzip -9n > "$stage/usr/share/doc/mcmgr/changelog.Debian.gz"
chmod 0644 "$stage/usr/share/doc/mcmgr/changelog.Debian.gz"

installed_size="$(du -sk "$stage/usr" | cut -f1)"
sed -e "s/@VERSION@/$version/g" \
    -e "s/@ARCH@/$ARCH/g" \
    -e "s/@MAINTAINER@/$MAINTAINER/g" \
    -e "s/@INSTALLED_SIZE@/$installed_size/g" \
    "$ROOT/packaging/deb/control.in" > "$stage/DEBIAN/control"

mkdir -p "$OUT"
dpkg-deb --root-owner-group -Zxz --build "$stage" "$OUT/$package" >/dev/null

echo "built: $OUT/$package"
dpkg-deb --info "$OUT/$package" | sed -n '1,14p'
echo
sha256sum "$OUT/$package"
