"""
dmgbuild settings for the MailRepo installer image.

Usage (after py2app + bundle_dylibs + codesign):

    ./venv/bin/dmgbuild -s packaging/dmg_settings.py "MailRepo" dist/MailRepo-<version>.dmg

GEOMETRY CONTRACT with packaging/dmg_background.svg: window 540x320,
icon size 100, app icon centered at (140, 125), Applications alias at
(400, 125). The arrow in the background artwork is drawn between those
two slots — move one, move both.
"""

# dmgbuild exec()s this file without __file__, so paths are relative to
# the working directory: RUN FROM THE REPO ROOT (as the usage line does).
import os.path

if not os.path.isdir("packaging"):
    raise SystemExit("run dmgbuild from the repo root (packaging/ not found here)")

application = os.path.join("dist", "MailRepo.app")

files = [application]
symlinks = {"Applications": "/Applications"}

background = os.path.join("packaging", "dmg_background.tiff")

window_rect = ((200, 200), (540, 320))
default_view = "icon-view"
icon_size = 100
text_size = 12

icon_locations = {
    "MailRepo.app": (140, 125),
    "Applications": (400, 125),
}

# Show nothing else: no toolbar, no sidebar, no status bar.
show_status_bar = False
show_tab_view = False
show_toolbar = False
show_pathbar = False
show_sidebar = False

format = "UDZO"  # compressed, read-only
