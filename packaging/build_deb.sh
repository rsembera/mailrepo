#!/bin/bash
# Build the MailRepo .deb. Run from anywhere on a Debian Trixie box.
# Usage: packaging/build_deb.sh 1.0.0
#
# Adapted from EdgeCase's build_deb.sh, including its GTK/PyGObject
# steps: MailRepo on Linux uses the same pywebview window as the Mac
# (launcher.py) — Rick's ruling during the Session 88 .deb build,
# superseding the guide's earlier browser-tab plan, for cross-platform
# consistency. Target ruling (Session 87): Debian Trixie natively,
# Python 3.13 floor, Ubuntu is not a target.
set -euo pipefail

VERSION="${1:?usage: build_deb.sh VERSION}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PKG="mailrepo_${VERSION}_amd64"
STAGE="$REPO/packaging/deb/$PKG"
APP="$STAGE/opt/mailrepo"

echo "== Staging $PKG"
rm -rf "$STAGE"
mkdir -p "$STAGE/DEBIAN" "$APP" "$STAGE/usr/bin" "$STAGE/usr/share/applications"

# Icon set rendered from icon.svg in Session 88 (same source as the .icns)
for s in 16 32 48 64 128 256 512; do
    mkdir -p "$STAGE/usr/share/icons/hicolor/${s}x${s}/apps"
    cp "$REPO/packaging/icons/hicolor/${s}x${s}/apps/mailrepo.png" \
       "$STAGE/usr/share/icons/hicolor/${s}x${s}/apps/mailrepo.png"
done
mkdir -p "$STAGE/usr/share/icons/hicolor/scalable/apps"
cp "$REPO/packaging/icons/hicolor/scalable/apps/mailrepo.svg" \
   "$STAGE/usr/share/icons/hicolor/scalable/apps/mailrepo.svg"

echo "== Copying application"
cd "$REPO"
# First-party code only — archive/, data/, config/, backups/ are user
# data; tests/, docs/, scripts/, packaging/ are not runtime.
cp -r core web utils main.py launcher.py LICENSE README.md "$APP/"
find "$APP" -name __pycache__ -type d -prune -exec rm -rf {} +

echo "== Building venv (runtime deps only)"
# The runtime set is assembled here rather than trusting requirements.txt
# sections (waitress sits under "Development" there but is the server).
# sqlcipher3 -> sqlcipher3-wheels on Linux: same module, prebuilt wheel
# bundling libsqlcipher, so the build needs no compiler (EdgeCase trick).
cat > /tmp/mailrepo-requirements-runtime.txt << 'REQS'
flask>=3.0.0
cryptography>=42.0.0
argon2-cffi>=23.0.0
sqlcipher3-wheels
Pillow>=10.0.0
waitress>=2.1.0
weasyprint>=60.0
pypdf>=4.0
pyzipper>=0.3
pywebview
REQS
python3 -m venv "$APP/venv"
"$APP/venv/bin/pip" install -q --upgrade pip
"$APP/venv/bin/pip" install -q -r /tmp/mailrepo-requirements-runtime.txt
rm /tmp/mailrepo-requirements-runtime.txt

echo "== Copying PyGObject from system (pywebview's GTK bridge; EdgeCase step)"
PYVER="$(python3 -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
cp -r /usr/lib/python3/dist-packages/gi "$APP/venv/lib/python$PYVER/site-packages/"

echo "== Smoke import from the staged tree"
( cd "$APP" && venv/bin/python -c "
import gi, webview
import sqlcipher3, argon2, cryptography, waitress, weasyprint
import web.app
c = sqlcipher3.connect(':memory:'); c.execute('pragma key=\"x\"')
print('imports ok, cipher', c.execute('pragma cipher_version').fetchone()[0])" )

echo "== Control, launcher, desktop entry"
INSTALLED_SIZE=$(du -sk "$STAGE" | cut -f1)
cat > "$STAGE/DEBIAN/control" << CTRL_EOF
Package: mailrepo
Version: $VERSION
Section: mail
Priority: optional
Architecture: amd64
Installed-Size: $INSTALLED_SIZE
Depends: python3 (>= 3.13), python3-gi, gir1.2-gtk-3.0, gir1.2-webkit2-4.1, libpango-1.0-0, libpangoft2-1.0-0, libharfbuzz0b, libharfbuzz-subset0, pst-utils, xdg-utils
Maintainer: Richard Sembera <richard@lightinextension.ca>
Homepage: https://mailrepo.ca
Description: Local-first encrypted email archiving
 Local-first encrypted email archiving (AES-256-GCM, Argon2id,
 SQLCipher, full-text search) for lawyers, therapists, journalists,
 and other solo practitioners with confidentiality obligations.
CTRL_EOF

cat > "$STAGE/usr/bin/mailrepo" << 'LAUNCH_EOF'
#!/bin/bash
# MailRepo launcher: the pywebview desktop shell (launcher.py), same as
# the Mac build. Data dir defaults to XDG (launcher.py sets it); the
# launcher itself refuses a second instance with a native dialog.
cd /opt/mailrepo
exec venv/bin/python launcher.py "$@"
LAUNCH_EOF
chmod 755 "$STAGE/usr/bin/mailrepo"

cat > "$STAGE/usr/share/applications/mailrepo.desktop" << 'DESK_EOF'
[Desktop Entry]
Name=MailRepo
Comment=Encrypted email archiving for solo practitioners
Exec=/usr/bin/mailrepo
Icon=mailrepo
Terminal=false
Type=Application
Categories=Office;Network;Email;
Keywords=email;archive;encryption;imap;
DESK_EOF

echo "== Building .deb"
cd "$REPO/packaging/deb"
dpkg-deb --build --root-owner-group "$PKG"
ls -la "$PKG.deb"
echo "== Done: packaging/deb/$PKG.deb"
