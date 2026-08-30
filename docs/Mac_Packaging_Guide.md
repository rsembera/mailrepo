# MailRepo — macOS .dmg Packaging Guide

> Status (Session 88): first py2app build succeeds and launches. Remaining
> work is the WeasyPrint dylib pass, the desktop-shell frontend fixes, then
> sign/notarize/DMG. See "Where things stand" at the bottom.

Adapted from EdgeCase's proven guide (`edgecase/docs/Mac_Packaging_Guide.md`).
The signing/notarization/DMG pipeline transfers verbatim — Rick's Developer ID
certificate, Team ID, and notarytool workflow already exist and work.

## Signing credentials (existing, from EdgeCase)

- **Certificate:** `Developer ID Application: RICHARD L SEMBERA (2GKBD5N2AH)`
- **Team ID:** `2GKBD5N2AH`
- **Apple ID:** `rsembera@ncf.ca`
- **Keychain profile to create (one-time):** `MailRepo Notarization`

```bash
xcrun notarytool store-credentials "MailRepo Notarization" \
    --apple-id "rsembera@ncf.ca" --team-id "2GKBD5N2AH"
```

## Key differences from EdgeCase

1. **WeasyPrint dylibs — the hard part, now fully mapped.** WeasyPrint
   loads pango & co. via `cffi.dlopen` *by bare name* at import time, so
   py2app's link-dependency scan never sees them and the first build
   shipped none. Running the bundled interpreter with
   `DYLD_PRINT_LIBRARIES=1` produced the complete list — **17 Homebrew
   dylibs**, all in `/opt/homebrew/Cellar/...`:

   `libpango-1.0.0`, `libpangoft2-1.0.0`, `libgobject-2.0.0`,
   `libglib-2.0.0`, `libgio-2.0.0`, `libgmodule-2.0.0`,
   `libharfbuzz.0`, `libharfbuzz-subset.0`, `libfontconfig.1`,
   `libfreetype.6`, `libfribidi.0`, `libthai.0`, `libdatrie.1`,
   `libgraphite2.3`, `libpng16.16`, `libpcre2-8.0`, `libintl.8`

   Plan: copy these into `Contents/Frameworks`, rewrite every `/opt/homebrew`
   reference among them to `@loader_path/<name>` with `install_name_tool`,
   sign each one, and have `launcher.py` pre-load them from that folder with
   `ctypes.CDLL` (absolute path, RTLD_GLOBAL) *before* `weasyprint` is
   imported — dyld then satisfies WeasyPrint's by-name `dlopen` from the
   already-loaded images. No `DYLD_*` environment variables: the hardened
   runtime strips them.
2. **PST import.** `readpst` is bundled (decided Session 87). Same
   pass as above: it needs libgsf, two glib libs and libintl, which
   overlap the list above.
3. **sqlcipher3 — solved for free.** The venv's `sqlcipher3` wheel is
   statically linked (`otool -L` shows only libSystem). It bundled on the
   first build and reports cipher 4.12.0 from inside the .app.
4. **pywebview, not browser + menu bar.** Decided Session 88: Joe User
   expects a native-looking window. `launcher.py` is the entry point;
   `main.py` stays the CLI. pywebview 6.2.1 on Cocoa handles `<a download>`
   and attachment responses natively (`ALLOW_DOWNLOADS`). It does **not**
   handle `window.print()` or `window.open('', '_blank')` — the two
   print-email paths and inline attachment viewing need a desktop-mode
   route in JS (detect `window.pywebview`; likely "export to PDF and open
   in Preview" plus an `open_file` bridge like EdgeCase's). Frontend work,
   next session, tested against the built .app.
5. **Data directory — decided.** `~/Library/Application Support/MailRepo/`,
   one level *below* `backup_locations.json`, which `Config.get_state_path()`
   already keeps at the top of that folder. Deleting the app touches
   neither. `launcher.py` sets `MAILREPO_DATA_DIR` before any import;
   an explicit value in the environment wins.

## Assets

- `assets/icon.icns` — **done** (Session 88), rendered from
  `web/static/assets/icon.svg` with Inkscape at 16–1024px, `iconutil`.
- `packaging/icons/hicolor/` — the Linux set, cut at the same time.
- `packaging/dmg_background.png` — still to create ("drag to Applications").
- `setup_app.py` — **done**; see its maintenance note.

## setup_app.py notes

- First-party code is declared as **packages** (`core`, `web`, `utils`),
  never as an enumerated module list — EdgeCase's list rotted silently.
  `archive/`, `data/`, `config/`, `backups/` are user data, not packages.
- `tests/test_packaging_manifest.py` imports the app for real and fails on
  any undeclared third-party package. It caught `_argon2_cffi_bindings`
  and `Cryptodome` (pyzipper's AES backend) on its first two runs. When a
  new dependency is added, this test is what says so.
- No pyproject.toml rename: `setup_app.py` clears `install_requires`
  before py2app's check (EdgeCase's later trick).
- Build: `./venv/bin/python setup_app.py py2app` — about one minute,
  147 MB .app before the dylib pass.

## Build → sign → notarize → DMG

Follow EdgeCase's guide steps verbatim with names swapped:

1. `./venv/bin/python setup_app.py py2app`
2. Dylib pass (to be scripted): copy the 17 WeasyPrint dylibs + readpst's
   into `Contents/Frameworks`, `install_name_tool` rewrite, then:
3. Sign every `.so`/`.dylib` individually first (CRITICAL — notarization
   fails otherwise), then the bundle with `--deep --options runtime`:

```bash
find "dist/MailRepo.app" -type f \( -name "*.so" -o -name "*.dylib" \) | while read -r f; do
    codesign --force --options runtime --timestamp \
        --sign "Developer ID Application: RICHARD L SEMBERA (2GKBD5N2AH)" "$f"
done
codesign --force --options runtime --timestamp \
    --sign "Developer ID Application: RICHARD L SEMBERA (2GKBD5N2AH)" \
    --deep "dist/MailRepo.app"
codesign --verify --deep --strict "dist/MailRepo.app"
spctl --assess --type exec "dist/MailRepo.app"
```

4. Notarize (5–15 min) and staple:

```bash
cd dist
ditto -c -k --keepParent "MailRepo.app" "MailRepo.zip"
xcrun notarytool submit "MailRepo.zip" --keychain-profile "MailRepo Notarization" --wait
xcrun stapler staple "MailRepo.app"
rm MailRepo.zip
```

5. DMG:

```bash
mkdir dmg_temp && cp -R "MailRepo.app" dmg_temp/
ln -s /Applications dmg_temp/Applications
cp ../packaging/dmg_background.png dmg_temp/.background.png
hdiutil create -volname "MailRepo" -srcfolder dmg_temp -ov -format UDZO "MailRepo-1.0.0.dmg"
rm -rf dmg_temp
```

## Acceptance test (clean macOS user account)

mount DMG → drag to Applications → first launch passes Gatekeeper with no
warning (notarization stapled) → set passphrase → import small mbox →
search → PDF export (the WeasyPrint dylib test) → backup → quit; confirm
data lands in `~/Library/Application Support/MailRepo`.

## Troubleshooting

Carry over EdgeCase's section as-is: "invalid signature" ⇒ a binary was
missed in the individual-signing pass; "developer cannot be verified" ⇒
ticket not stapled; py2app build failure ⇒ pyproject.toml not renamed or a
module missing from `includes`.


## Testing the bundled interpreter directly

The .app's `Contents/MacOS/python` does not set `sys.path`; give it the
bundle's own path to exercise packages exactly as the app will:

```bash
cd dist/MailRepo.app/Contents
L=$PWD/Resources/lib
DYLD_PRINT_LIBRARIES=1 PYTHONPATH="$L/python314.zip:$L/python3.14:$L/python3.14/lib-dynload" \
  ./MacOS/python -S -c "import weasyprint; weasyprint.HTML(string='<p>x</p>').write_pdf('/tmp/t.pdf')" \
  2>&1 | grep /opt/homebrew
```

Any `/opt/homebrew` line is a library that would be missing on a clean Mac.
The goal state is zero lines.

To smoke-test the launcher without touching the real archive:

```bash
MAILREPO_DATA_DIR=/tmp/mr_smoke MAILREPO_STATE_DIR=/tmp/mr_smoke_state \
  ./dist/MailRepo.app/Contents/MacOS/MailRepo
```

## Where things stand (end of Session 88)

Done: icon.icns, setup_app.py + manifest test, launcher.py, first build
launches and serves, sqlcipher3 and argon2 verified inside the bundle,
WeasyPrint dylib list captured.

Next: (1) the dylib bundling script + launcher pre-load, verified with
the zero-`/opt/homebrew` test above; (2) desktop-mode JS for print and
inline attachment view; (3) dmg_background.png; (4) sign → notarize →
DMG per the steps above; (5) clean-account acceptance test.
