"""
py2app build script for MailRepo
Creates a standalone macOS .app bundle

Run with: python setup_app.py py2app

MAINTENANCE NOTE
----------------
First-party code is declared as PACKAGES, not as an enumerated list of
modules. EdgeCase learned this the hard way: an enumerated list silently
rots as modules are added and split, and a packaged build ships without
them. Declaring the packages means new modules are picked up automatically.

tests/test_packaging_manifest.py asserts that everything actually imported
by the running app is covered by the declarations below, so this file
cannot drift out of date without a test failing.
"""

from setuptools import setup

APP = ['launcher.py']  # desktop shell; `python main.py` stays the CLI entry point
APP_NAME = 'MailRepo'
APP_VERSION = '1.0.0'

# Third-party runtime dependencies.
#
# argon2 (argon2-cffi) is load-bearing and easy to miss: it is a CFFI
# extension rather than pure Python, and without it a packaged build fails
# at LOGIN — the first moment a key is derived — rather than at startup.
#
# weasyprint and its pure-Python tree (cssselect2, tinycss2, tinyhtml5,
# pydyf, pyphen, fontTools) are the PDF export path. The native side
# (pango, harfbuzz, fontconfig, ...) is NOT covered here: those are
# Homebrew dylibs loaded through cffi at runtime and are bundled by a
# separate pass — see docs/Mac_Packaging_Guide.md.
THIRD_PARTY_PACKAGES = [
    'flask',
    'jinja2',
    'markupsafe',
    'werkzeug',
    'itsdangerous',
    'blinker',
    'click',
    'waitress',
    'webview',
    'sqlcipher3',
    'cryptography',
    'argon2',
    '_argon2_cffi_bindings',
    'cffi',
    'PIL',
    'weasyprint',
    'cssselect2',
    'tinycss2',
    'tinyhtml5',
    'webencodings',
    'pydyf',
    'pyphen',
    'fontTools',
    'pypdf',
    'pyzipper',
    'Cryptodome',  # pycryptodomex: pyzipper's AES backend for encrypted zip exports
]

# First-party packages. Everything under these is bundled, so blueprint
# submodules and the crypto/migration modules are covered without being
# named individually. NOTE: archive/, data/, config/ and backups/ in the
# repo are USER DATA directories, not packages — they must never appear
# here or in resources.
FIRST_PARTY_PACKAGES = [
    'core',
    'web',
    'utils',
]

OPTIONS = {
    'argv_emulation': False,
    'iconfile': 'assets/icon.icns',
    'plist': {
        'CFBundleName': APP_NAME,
        'CFBundleDisplayName': APP_NAME,
        'CFBundleIdentifier': 'ca.mailrepo.app',
        'CFBundleVersion': APP_VERSION,
        'CFBundleShortVersionString': APP_VERSION,
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '11.0',
        'NSRequiresAquaSystemAppearance': False,
    },
    'packages': THIRD_PARTY_PACKAGES + FIRST_PARTY_PACKAGES,
    'includes': [
        # CFFI's compiled backend: cffi is a package above, but the backend
        # is a bare extension module beside it and modulegraph can miss it.
        '_cffi_backend',
        # Imported lazily from inside functions (to avoid circular imports
        # or to keep startup fast), so static analysis can miss them even
        # though the packages above are bundled.
        'core.crypto_migration_v3',
        'core.password_change',
        'core.pending_commit',
        'core.pdf_export',
        'core.sync_cache',
        'utils.backup',
    ],
    'excludes': [
        'tkinter',
        'PyQt5',
        'PyQt6',
        'pytest',
        'ruff',
    ],
    # No 'resources' entry: py2app copies web/templates and web/static
    # inside the `web` package itself (which is what Flask serves), so a
    # resources entry only produced a second, unused copy.
}

# Guarded so the manifest above can be imported and inspected (by
# tests/test_packaging_manifest.py) without invoking setuptools, which would
# exit the interpreter. py2app runs this file directly, so the build path is
# unaffected.
if __name__ == '__main__':
    # Modern setuptools populates install_requires from pyproject.toml's
    # [project] dependencies table even when this script is run directly —
    # and py2app refuses to build when install_requires is set (it bundles
    # from the live venv and never installs dependencies itself). Clear the
    # attribute before py2app's check runs. This replaces the older
    # "rename pyproject.toml" workaround.
    from py2app.build_app import py2app as _py2app_cmd

    class py2app_from_venv(_py2app_cmd):
        def finalize_options(self):
            self.distribution.install_requires = None
            super().finalize_options()

    setup(
        app=APP,
        name=APP_NAME,
        options={'py2app': OPTIONS},
        cmdclass={'py2app': py2app_from_venv},
    )
