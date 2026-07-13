# MailRepo — macOS .dmg Packaging Guide (DRAFT)

Adapted from EdgeCase's proven guide (`edgecase/docs/Mac_Packaging_Guide.md`).
The signing/notarization/DMG pipeline transfers verbatim — Rick's Developer ID
certificate, Team ID, and notarytool workflow already exist and work. Steps
marked **[VERIFY]** need confirmation during the first live packaging session.

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

1. **WeasyPrint dylibs — the hard part.** Pango, HarfBuzz, cairo, and
   friends come from Homebrew and must be bundled into the .app with
   correct rpaths. EdgeCase has no precedent for this (reportlab is pure
   Python + Pillow). Expect this to consume most of the iteration time.
   **[VERIFY]** whether py2app picks the dylibs up automatically or needs
   an explicit frameworks list + `install_name_tool` pass.
2. **PST import.** `readpst` is a subprocess, not a Python package.
   Options: bundle the binary (+ its dylibs) in Resources, or degrade
   gracefully with a "install libpst via Homebrew" message on macOS.
   **[DECIDE]** — graceful degradation is the cheaper 1.0 answer.
3. **sqlcipher3.** EdgeCase's macOS venv builds `sqlcipher3` from source
   against a local libsqlcipher (see its requirements.txt notes) rather
   than using wheels. Follow the same recipe; the resulting .so gets
   signed like everything else.
4. **No pywebview (1.0).** The app entry point is `main.py` (waitress +
   browser), not a desktop.py. py2app wraps it the same way. Post-1.0
   pywebview would change the entry point only.
5. **Data directory.** Set `MAILREPO_DATA_DIR` to
   `~/Library/Application Support/MailRepo` in the app's launch env
   (py2app `LSEnvironment` in the plist, or a shim in main). **[VERIFY]**

## Assets — TO CREATE before first build

- `assets/icon.icns` (from the MailRepo logo)
- `packaging/dmg_background.png` ("drag to Applications" arrow)
- `setup_app.py` (py2app config; copy EdgeCase's and adapt)

## setup_app.py checklist (EdgeCase lessons, carried over)

- py2app does **not** auto-detect modules: `includes` must list every
  `core.*`, `web.*`, `utils.*`, `archive.*` module or packaged users hit
  ImportError at launch. Generate the list from Navigation_Map.md.
- `packages` must include `'argon2'` and `'_argon2_cffi_bindings'`
  (EdgeCase hit this exact ImportError) plus `'weasyprint'` and its pure-
  Python deps. **[VERIFY]** the full list by launching the built .app from
  Terminal and reading tracebacks.
- Rename `pyproject.toml` → `.bak` before building (py2app conflict),
  restore after. Same quirk as EdgeCase.

## Build → sign → notarize → DMG

Follow EdgeCase's guide steps verbatim with names swapped:

1. `mv pyproject.toml pyproject.toml.bak`
2. `python setup_app.py py2app`
3. `mv pyproject.toml.bak pyproject.toml`
4. Sign every `.so`/`.dylib` individually first (CRITICAL — notarization
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

5. Notarize (5–15 min) and staple:

```bash
cd dist
ditto -c -k --keepParent "MailRepo.app" "MailRepo.zip"
xcrun notarytool submit "MailRepo.zip" --keychain-profile "MailRepo Notarization" --wait
xcrun stapler staple "MailRepo.app"
rm MailRepo.zip
```

6. DMG:

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
