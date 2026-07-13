# MailRepo — Linux .deb Packaging Guide (DRAFT)

Adapted from EdgeCase's proven guide (`edgecase/docs/Linux_Packaging_Guide.md`).
Steps marked **[VERIFY]** need confirmation during the first live packaging
session; everything else follows the EdgeCase pattern that already ships.

## Key differences from EdgeCase

1. **Data directory.** MailRepo defaults its data dir to the application
   directory (`core/config.py`), which is root-owned under `/opt`. The
   launcher must export `MAILREPO_DATA_DIR="$HOME/.local/share/mailrepo"`.
   The env hook already exists — no code change needed.
2. **WeasyPrint.** PDF export needs Pango/HarfBuzz system libraries at
   runtime → `Depends:` line (EdgeCase uses reportlab and has no such deps).
3. **PST import.** Shells out to `readpst` → `Depends: pst-utils`.
4. **No pywebview (1.0).** MailRepo launches in the browser; the launcher
   starts waitress and opens the default browser. (Post-1.0: EdgeCase's
   `desktop.py` pywebview pattern is the template if we wrap it.)
5. **Python floor is 3.11** (README). Build the venv on a system matching
   the oldest supported target — a clean Ubuntu 24.04 container (Python
   3.12) — so the shipped venv's glibc/python match. **[VERIFY]**

## Prerequisites

- Ubuntu 24.04 (or container) with `python3-venv`, `dpkg-deb`
- Runtime system libs present for the pip install of weasyprint

## Directory structure

```
packaging/
├── icons/                    # mailrepo-{48,96,128,180,256}x*.png — TO CREATE
└── deb/                      # build dir (gitignored)
    └── mailrepo_1.0.0_amd64/
```

## Build steps

### 1. Package skeleton

```bash
cd ~/Applications/mailrepo/packaging/deb
rm -rf mailrepo_1.0.0_amd64
mkdir -p mailrepo_1.0.0_amd64/DEBIAN
mkdir -p mailrepo_1.0.0_amd64/opt/mailrepo
mkdir -p mailrepo_1.0.0_amd64/usr/bin
mkdir -p mailrepo_1.0.0_amd64/usr/share/applications
mkdir -p mailrepo_1.0.0_amd64/usr/share/icons/hicolor/{48x48,96x96,128x128,180x180,256x256}/apps
```

### 2. Copy application files

```bash
cd ~/Applications/mailrepo
cp -r core web utils archive config main.py requirements.txt LICENSE \
    packaging/deb/mailrepo_1.0.0_amd64/opt/mailrepo/
```

**[VERIFY]** exact directory list against Navigation_Map.md at build time
(exclude tests/, test_files/, docs/, scripts/, data/, backups/).

### 3. Build the venv inside the package

```bash
cd packaging/deb/mailrepo_1.0.0_amd64/opt/mailrepo
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r requirements.txt
```

Note: requirements.txt includes dev tools (pytest, ruff). **[VERIFY]**
whether to split a requirements-runtime.txt first, as EdgeCase did.

### 4. DEBIAN/control

```bash
cat > packaging/deb/mailrepo_1.0.0_amd64/DEBIAN/control << 'CTRL'
Package: mailrepo
Version: 1.0.0
Section: mail
Priority: optional
Architecture: amd64
Depends: libpango-1.0-0, libpangoft2-1.0-0, libharfbuzz0b, libharfbuzz-subset0, pst-utils
Maintainer: Richard Sembera <richard@lightinextension.ca>
Description: MailRepo - Encrypted email archiving for solo practitioners
 Local-first encrypted email archiving (AES-256-GCM, Argon2id,
 SQLCipher) for lawyers, therapists, journalists, and other
 professionals with confidentiality obligations.
CTRL
```

**[VERIFY]** the Depends list against a clean 24.04 container — WeasyPrint's
runtime lib set changes between releases; confirm whether libgdk-pixbuf is
still needed and whether the sqlcipher3 wheel bundles libsqlcipher.

### 5. Launcher

```bash
cat > packaging/deb/mailrepo_1.0.0_amd64/usr/bin/mailrepo << 'LAUNCH'
#!/bin/bash
export MAILREPO_DATA_DIR="$HOME/.local/share/mailrepo"
mkdir -p "$MAILREPO_DATA_DIR"
cd /opt/mailrepo
exec venv/bin/python main.py "$@"
LAUNCH
chmod +x packaging/deb/mailrepo_1.0.0_amd64/usr/bin/mailrepo
```

**[VERIFY]** how main.py opens the browser and binds its port; add
single-instance handling (second launch should open a tab against the
running server, not fail on a bound port).

### 6. Desktop entry

```bash
cat > packaging/deb/mailrepo_1.0.0_amd64/usr/share/applications/mailrepo.desktop << 'DESK'
[Desktop Entry]
Name=MailRepo
Comment=Encrypted email archiving for solo practitioners
Exec=/usr/bin/mailrepo
Icon=mailrepo
Terminal=false
Type=Application
Categories=Office;Network;Email;
Keywords=email;archive;encryption;imap;
DESK
```

### 7. Icons

Copy `packaging/icons/mailrepo-NxN.png` into the hicolor tree (see EdgeCase
guide step 8 for the exact pattern). **TO CREATE:** render the icon set from
the MailRepo logo before the first build.

### 8. Build

```bash
cd ~/Applications/mailrepo/packaging/deb
dpkg-deb --build mailrepo_1.0.0_amd64
```

## Acceptance test (clean 24.04 container)

install → launch from menu → set passphrase → import a small mbox from
test_files/ → search → PDF export (exercises WeasyPrint) → PST import
(exercises pst-utils) → backup now → uninstall leaves ~/.local/share/mailrepo
intact.

## Notes

- `packaging/deb/` gitignored; `packaging/icons/` tracked.
- User data lives in `~/.local/share/mailrepo/` (set by the launcher).
- EdgeCase's PyGObject copy step (its step 4) is **not needed** — that is
  pywebview/GTK only; MailRepo 1.0 has no GTK dependency.
