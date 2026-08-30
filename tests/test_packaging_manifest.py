"""The packaging manifest must cover what the app actually imports.

setup_app.py is only exercised when someone builds a .dmg, so mistakes in it
stay invisible for months and then surface as a packaged app that dies at
login. EdgeCase shipped exactly that bug once. This test imports the app the
way it runs and asserts every third-party package it pulls in is declared.

It is a drift alarm, not a build test: it cannot prove py2app will succeed,
only that the manifest still describes the application.
"""

import importlib
import sys

import pytest


@pytest.fixture(scope="module")
def imported_app_modules():
    """Import the app the way it runs, then report what got loaded."""
    importlib.import_module("web")
    importlib.import_module("web.app")
    # Lazily-imported paths that a bare `import web.app` would not reach.
    for name in (
        "core.crypto_migration_v3",
        "core.password_change",
        "core.pending_commit",
        "core.pdf_export",
        "core.sync_cache",
        "utils.backup",
    ):
        importlib.import_module(name)
    return dict(sys.modules)


@pytest.fixture(scope="module")
def manifest():
    import setup_app

    return setup_app


FIRST_PARTY_ROOTS = {"core", "web", "utils"}

# In sys.modules because pytest, setuptools or py2app are running — not
# because MailRepo imports them.
TOOLING = {
    "pytest", "py", "pluggy", "iniconfig", "setuptools", "pkg_resources",
    "_pytest", "attr", "attrs", "pycparser", "packaging", "exceptiongroup",
    "typing_extensions", "distutils", "more_itertools", "pygments", "tomli",
    "jaraco", "backports", "importlib_metadata", "zipp", "platformdirs",
    "wheel", "py2app", "macholib", "modulegraph", "altgraph", "ruff",
    "__main__", "_distutils_hack",
    # argon2's compiled extension registers itself under this bare name as
    # well as inside its package; the package is what the manifest declares.
    "_ffi",
}


def test_first_party_roots_are_declared(manifest):
    """Declared as packages, so submodules are covered automatically."""
    declared = set(manifest.FIRST_PARTY_PACKAGES)
    assert FIRST_PARTY_ROOTS <= declared, FIRST_PARTY_ROOTS - declared


def test_user_data_directories_are_not_bundled(manifest):
    """archive/, data/, config/, backups/ are the user's mail, not code."""
    bundled = set(manifest.OPTIONS["packages"]) | set(manifest.OPTIONS["resources"])
    assert not bundled & {"archive", "data", "config", "backups"}


def test_every_imported_third_party_package_is_declared(imported_app_modules, manifest):
    declared = {p.lower() for p in manifest.OPTIONS["packages"]}
    declared |= {i.lower() for i in manifest.OPTIONS["includes"]}
    missing = set()
    for name, module in imported_app_modules.items():
        if "." in name or module is None:
            continue
        path = str(getattr(module, "__file__", "") or "")
        if "site-packages" not in path:
            continue
        if name.lower() not in declared:
            missing.add(name)
    missing -= TOOLING
    assert not missing, f"undeclared runtime packages: {sorted(missing)}"


@pytest.mark.parametrize(
    "package", ["argon2", "_argon2_cffi_bindings", "sqlcipher3", "weasyprint", "cffi"]
)
def test_load_bearing_native_packages_are_declared(manifest, package):
    """Each of these is a compiled extension (or loads one) and each fails
    late — at login, at first search, at first PDF export — not at launch."""
    assert package in manifest.OPTIONS["packages"]


def test_cffi_backend_is_explicitly_included(manifest):
    """_cffi_backend is a bare extension beside the cffi package; argon2,
    cryptography and weasyprint all need it and modulegraph can miss it."""
    assert "_cffi_backend" in manifest.OPTIONS["includes"]


def test_lazily_imported_modules_are_explicitly_included(manifest):
    """Imported from inside functions, so they are named rather than trusted
    to static analysis. Each really must exist."""
    for module in manifest.OPTIONS["includes"]:
        if module.startswith(("core.", "utils.", "web.")):
            importlib.import_module(module)


def test_launcher_is_the_entry_point(manifest):
    assert manifest.APP == ["launcher.py"]


def test_declared_packages_are_all_importable(manifest):
    """A typo in the manifest should fail here, not during a .dmg build."""
    unimportable = []
    for name in manifest.OPTIONS["packages"]:
        try:
            importlib.import_module(name)
        except Exception:
            unimportable.append(name)
    assert not unimportable, f"declared but not importable: {unimportable}"


def test_templates_and_static_are_bundled(manifest):
    assert "web/templates" in manifest.OPTIONS["resources"]
    assert "web/static" in manifest.OPTIONS["resources"]
