#!/usr/bin/env python3
"""
Bundle the Homebrew native libraries MailRepo needs into MailRepo.app.

py2app cannot see these: WeasyPrint loads pango, harfbuzz, fontconfig and
their dependencies through cffi.dlopen by bare name at import time, and
readpst is a subprocess. So after `python setup_app.py py2app`, run:

    ./venv/bin/python packaging/bundle_dylibs.py dist/MailRepo.app [--sign IDENTITY]

What it does
  1. Walks the dependency closure of the seed libraries and readpst
     (otool -L, recursively, Homebrew paths only) so the list is computed,
     not maintained by hand.
  2. Copies each library into Contents/Frameworks under its install-name
     leaf, and readpst into Contents/Helpers.
  3. Rewrites every /opt/homebrew reference to @loader_path (libraries)
     or @executable_path/../Frameworks (readpst) with install_name_tool.
  4. Signs each modified file: ad-hoc by default (required on Apple
     Silicon just to load), or with --sign "Developer ID Application: ..."
     for a release build.

launcher.py pre-loads Contents/Frameworks/*.dylib before WeasyPrint is
imported and puts Contents/Helpers on PATH. See docs/Mac_Packaging_Guide.md.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

HOMEBREW = "/opt/homebrew"

# What WeasyPrint dlopens (text/ffi.py) plus the PST converter. Their
# dependencies are discovered below.
SEED_LIBS = [
    "libgobject-2.0.0.dylib",
    "libpango-1.0.0.dylib",
    "libpangoft2-1.0.0.dylib",
    "libharfbuzz.0.dylib",
    "libharfbuzz-subset.0.dylib",
    "libfontconfig.1.dylib",
]
SEED_BINS = ["readpst"]


def otool_deps(path):
    out = subprocess.run(["otool", "-L", str(path)], capture_output=True, text=True, check=True)
    lines = out.stdout.splitlines()[1:]
    return [line.split()[0] for line in lines if line.strip()]


def install_name(path):
    out = subprocess.run(["otool", "-D", str(path)], capture_output=True, text=True, check=True)
    lines = [line for line in out.stdout.splitlines()[1:] if line.strip()]
    return lines[0].strip() if lines else str(path)


def closure(seeds):
    """realpath -> canonical leaf name, for every Homebrew library reachable."""
    found = {}
    stack = [os.path.realpath(s) for s in seeds]
    while stack:
        real = stack.pop()
        if real in found:
            continue
        found[real] = Path(install_name(real)).name
        for dep in otool_deps(real):
            if dep.startswith(HOMEBREW):
                dep_real = os.path.realpath(dep)
                if dep_real != real and dep_real not in found:
                    stack.append(dep_real)
    return found


def rewrite(target, mapping, prefix):
    """Point every Homebrew reference in `target` at the bundled copy."""
    args = []
    for dep in otool_deps(target):
        if dep.startswith(HOMEBREW):
            leaf = mapping[os.path.realpath(dep)]
            args += ["-change", dep, f"{prefix}/{leaf}"]
    if args:
        subprocess.run(["install_name_tool", *args, str(target)], check=True)


def sign(path, identity):
    # Hardened runtime only with a real identity: it turns on library
    # validation, which requires matching Team IDs, and ad-hoc signatures
    # have none — readpst would then refuse its own bundled libgsf.
    if identity == "-":
        opts = ["--timestamp=none"]
    else:
        opts = ["--timestamp", "--options", "runtime"]
    subprocess.run(
        ["codesign", "--force", *opts, "--sign", identity, str(path)],
        check=True, capture_output=True,
    )


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    app = Path(sys.argv[1]).resolve()
    identity = "-"
    if "--sign" in sys.argv:
        identity = sys.argv[sys.argv.index("--sign") + 1]

    frameworks = app / "Contents" / "Frameworks"
    helpers = app / "Contents" / "Helpers"
    frameworks.mkdir(exist_ok=True)
    helpers.mkdir(exist_ok=True)

    seed_paths = [f"{HOMEBREW}/lib/{n}" for n in SEED_LIBS]
    bin_paths = [shutil.which(b) or f"{HOMEBREW}/bin/{b}" for b in SEED_BINS]
    for p in seed_paths + bin_paths:
        if not Path(p).exists():
            sys.exit(f"missing on this machine: {p}")

    libs = closure(seed_paths + bin_paths)
    # readpst itself is in the closure walk only as a root; drop it from the lib map.
    lib_map = {r: n for r, n in libs.items() if r.endswith(".dylib")}

    print(f"{len(lib_map)} libraries:")
    for real, leaf in sorted(lib_map.items(), key=lambda kv: kv[1]):
        dst = frameworks / leaf
        shutil.copy2(real, dst)
        dst.chmod(0o755)
        subprocess.run(["install_name_tool", "-id", f"@loader_path/{leaf}", str(dst)], check=True)
        rewrite(dst, lib_map, "@loader_path")
        sign(dst, identity)
        print(f"  {leaf}")

    for b in bin_paths:
        dst = helpers / Path(b).name
        shutil.copy2(os.path.realpath(b), dst)
        dst.chmod(0o755)
        rewrite(dst, lib_map, "@executable_path/../Frameworks")
        sign(dst, identity)
        print(f"helper: {dst.name}")

    # Nothing may still point at Homebrew.
    leaks = []
    for f in list(frameworks.glob("*.dylib")) + list(helpers.iterdir()):
        for dep in otool_deps(f):
            if dep.startswith(HOMEBREW):
                leaks.append((f.name, dep))
    if leaks:
        for name, dep in leaks:
            print(f"LEAK {name} -> {dep}")
        sys.exit(1)
    print("no Homebrew references remain")


if __name__ == "__main__":
    main()
