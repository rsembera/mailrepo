"""PST conversion directories: plain-text mail in the temp folder."""

import os
import tempfile

import pytest

from core import Encryption, pst_temp


@pytest.fixture
def temp_root(tmp_path, monkeypatch):
    """A temp folder reached through a symlink, as on macOS (/var -> /private/var)."""
    real = tmp_path / "private" / "T"
    real.mkdir(parents=True)
    link = tmp_path / "T"
    link.symlink_to(real)
    monkeypatch.setattr(tempfile, "tempdir", str(link))
    monkeypatch.setattr(pst_temp, "_own", set())
    return link


def _fill(path):
    with open(os.path.join(path, "Inbox"), "wb") as f:
        f.write(b"From someone\nSubject: x\n\nbody\n")


def test_conversion_dir_is_recognised_through_a_symlinked_temp_folder(temp_root):
    made = pst_temp.create()
    # mkdtemp hands back the unresolved path; the route resolves it.
    assert made.startswith(str(temp_root))
    assert pst_temp.is_conversion_dir(made)
    assert pst_temp.is_conversion_dir(os.path.realpath(made))


def test_cleanup_route_removes_the_conversion(authenticated_client, temp_root):
    made = pst_temp.create()
    _fill(made)
    resp = authenticated_client.post("/api/filesystem/cleanup-pst-temp", json={"temp_dir": made})
    assert resp.status_code == 200, resp.get_json()
    assert not os.path.exists(made)


@pytest.mark.parametrize(
    "build",
    [
        lambda root, outside: str(outside),
        lambda root, outside: str(root),
        lambda root, outside: os.path.join(str(root), "mailrepo_pst_x", "..", "..", "outside"),
        lambda root, outside: os.path.join(str(root), "mailrepo_pst_"),
        lambda root, outside: os.path.join(str(root), "other_mailrepo_pst_x"),
        lambda root, outside: "",
    ],
)
def test_cleanup_route_refuses_anything_else(authenticated_client, temp_root, tmp_path, build):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")
    (temp_root / "other_mailrepo_pst_x").mkdir()
    (temp_root / "mailrepo_pst_").mkdir()
    resp = authenticated_client.post(
        "/api/filesystem/cleanup-pst-temp", json={"temp_dir": build(temp_root, outside)}
    )
    assert resp.status_code == 400
    assert (outside / "keep.txt").exists()
    assert (temp_root / "other_mailrepo_pst_x").exists()
    assert (temp_root / "mailrepo_pst_").exists()


def test_a_nested_directory_with_the_prefix_is_not_ours(temp_root):
    nested = temp_root / "someone_else" / "mailrepo_pst_abc"
    nested.mkdir(parents=True)
    assert not pst_temp.is_conversion_dir(str(nested))
    assert not pst_temp.remove(str(nested))
    assert nested.exists()


def test_a_symlink_with_the_prefix_is_not_followed(temp_root, tmp_path):
    target = tmp_path / "precious"
    target.mkdir()
    (target / "keep.txt").write_text("keep")
    (temp_root / "mailrepo_pst_link").symlink_to(target)
    assert not pst_temp.remove(str(temp_root / "mailrepo_pst_link"))
    pst_temp.sweep()
    assert (target / "keep.txt").exists()


def test_locking_removes_this_runs_conversions_only(authenticated_client, temp_root):
    mine = pst_temp.create()
    _fill(mine)
    # Made by another running copy of the app.
    theirs = os.path.join(os.path.realpath(str(temp_root)), "mailrepo_pst_other")
    os.mkdir(theirs)

    Encryption.lock()

    assert not os.path.exists(mine)
    assert os.path.exists(theirs)


def test_launch_sweep_removes_every_leftover(temp_root):
    a = pst_temp.create()
    b = os.path.join(os.path.realpath(str(temp_root)), "mailrepo_pst_crashed")
    os.mkdir(b)
    _fill(b)
    other = temp_root / "unrelated"
    other.mkdir()
    assert pst_temp.sweep() == 2
    assert not os.path.exists(a) and not os.path.exists(b)
    assert other.exists()


def test_exit_removes_this_runs_conversions(temp_root):
    import inspect

    import main

    assert "pst_temp.remove_own()" in inspect.getsource(main._cleanup)
    assert "pst_temp.sweep()" in inspect.getsource(main.prepare_app)
    made = pst_temp.create()
    assert pst_temp.remove_own() == 1
    assert not os.path.exists(made)
    assert pst_temp.remove_own() == 0


def test_conversion_is_allowed_more_than_five_minutes_and_holds_off_the_idle_lock():
    import inspect

    from web.blueprints.api import filesystem

    assert filesystem.PST_CONVERT_TIMEOUT >= 30 * 60
    source = inspect.getsource(filesystem.convert_pst_to_mbox)
    assert 'idle.busy("pst-convert")' in source
    assert "timeout=PST_CONVERT_TIMEOUT" in source


def test_read_file_route_is_gone(authenticated_client, tmp_path):
    """Nothing in the app used it; it returned any file on the machine as text."""
    target = tmp_path / "secret.txt"
    target.write_text("secret")
    resp = authenticated_client.post("/api/filesystem/read-file", json={"path": str(target)})
    assert resp.status_code in (404, 405)
