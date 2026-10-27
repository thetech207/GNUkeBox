#!/bin/sh
# Build the GNUkeBox .deb package. Usage: ./build-deb.sh [version]
# Needs nothing but dpkg-deb (installed on every Debian system).
set -e
cd "$(dirname "$0")"

VERSION="${1:-1.0~rc1-1}"
PKG="gnukebox_${VERSION}_all"
ROOT="build/$PKG"

rm -rf build "${PKG}.deb"
mkdir -p "$ROOT/DEBIAN" \
         "$ROOT/usr/bin" \
         "$ROOT/usr/share/gnukebox" \
         "$ROOT/usr/share/applications" \
         "$ROOT/usr/share/icons/hicolor/scalable/apps"

sed "s/@VERSION@/$VERSION/" packaging/control > "$ROOT/DEBIAN/control"
cp packaging/postinst packaging/postrm "$ROOT/DEBIAN/"
chmod 755 "$ROOT/DEBIAN/postinst" "$ROOT/DEBIAN/postrm"

cat > "$ROOT/usr/bin/gnukebox" <<'EOF'
#!/bin/sh
exec python3 /usr/share/gnukebox/gnukebox.py "$@"
EOF
chmod 755 "$ROOT/usr/bin/gnukebox"

cp gnukebox.py library.py "$ROOT/usr/share/gnukebox/"
chmod 644 "$ROOT/usr/share/gnukebox/"*.py
cp packaging/GNUkeBox.desktop "$ROOT/usr/share/applications/"
cp icon.svg "$ROOT/usr/share/icons/hicolor/scalable/apps/gnukebox.svg"

dpkg-deb --root-owner-group --build "$ROOT" "${PKG}.deb"
echo "Built ${PKG}.deb"
