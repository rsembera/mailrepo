"""
Code review 2026-11, finding 17: one backup cycle for logout, app exit
and Backup Now. The exit path had drifted: no retention cleanup, and the
post-backup command still went through a plain subprocess.run.
"""

import main
import utils
from core import Database, Encryption
from core.database import set_setting
from utils import backup


def _something_to_back_up():
    Database.execute("INSERT INTO folders (name) VALUES ('F')")
    Database.commit()


def _spy(monkeypatch):
    calls = {"commands": [], "retention": []}
    monkeypatch.setattr(
        utils,
        "run_shell_command",
        lambda cmd, timeout=300: (calls["commands"].append(cmd), (True, "ok", "out"))[1],
    )
    real_cleanup = backup.cleanup_old_backups
    monkeypatch.setattr(
        backup,
        "cleanup_old_backups",
        lambda retention, location=None: (
            calls["retention"].append(retention),
            real_cleanup(retention, location),
        )[1],
    )
    return calls


class TestRunDueBackup:
    def test_takes_the_backup_prunes_and_runs_the_command(self, initialized_app, monkeypatch):
        calls = _spy(monkeypatch)
        _something_to_back_up()
        set_setting("backup_frequency", "daily")
        set_setting("backup_retention", "6months")
        set_setting("post_backup_command", "echo done")

        result = backup.run_due_backup()

        assert result is not None and result["type"] == "full"
        assert calls["retention"] == ["6months"]
        assert calls["commands"] == ["echo done"]
        assert backup.load_manifest().get("last_backup_check")  # the check was recorded

    def test_does_nothing_when_no_backup_is_due(self, initialized_app, monkeypatch):
        calls = _spy(monkeypatch)
        _something_to_back_up()
        set_setting("backup_frequency", "manual")
        assert backup.run_due_backup() is None
        assert calls == {"commands": [], "retention": []}

    def test_a_failing_command_does_not_fail_the_backup(self, initialized_app, monkeypatch):
        monkeypatch.setattr(
            utils, "run_shell_command", lambda cmd, timeout=300: (False, "timed out", "")
        )
        _something_to_back_up()
        set_setting("post_backup_command", "false")
        assert backup.run_due_backup() is not None


class TestAppExit:
    def test_exit_runs_the_shared_cycle(self, app, initialized_app, monkeypatch):
        ran = []
        monkeypatch.setattr(backup, "run_due_backup", lambda: ran.append(True))
        monkeypatch.setattr(main, "_cleanup_done", False)
        main._cleanup(app)
        assert ran == [True]

    def test_exit_after_a_lock_does_not_touch_the_archive(self, app, initialized_app, monkeypatch):
        ran = []
        monkeypatch.setattr(backup, "run_due_backup", lambda: ran.append(True))
        monkeypatch.setattr(main, "_cleanup_done", False)
        Database.close()
        Encryption.lock()
        main._cleanup(app)
        assert ran == []
        assert Database._connection is None

    def test_exit_no_longer_shells_out_on_its_own(self):
        import inspect

        assert "subprocess" not in inspect.getsource(main._cleanup)
