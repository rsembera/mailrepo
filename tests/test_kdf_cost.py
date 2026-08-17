"""The KDF work factor, and the guards that keep the cheap path in its box.

Argon2id at production strength costs most of a second per hash, and the
suite performs hundreds of them — a full run took ~10 minutes on the M4
and ~12 on Apollo (Session 80), slow enough to change how the work gets
done rather than merely being annoying. Ported from Daybook's fix of
August 15.

So the suite runs at a lower work factor. THIS IS NOT MOCKING. It is the
same algorithm through the same call site; the archive is still encrypted
with Argon2id-derived keys and still reopened by re-deriving them. What a
lower cost stops proving is that the derivation is SLOW — which is exactly
what the tests in this file exist to prove separately.

The danger being guarded is not a weak archive. The parameters are not
recorded in the key file, so an archive created cheaply cannot be opened
at production strength or the reverse: getting this wrong locks someone
out of their archive permanently. Hence two environment variables, and
hence this file.
"""

import time

import pytest

from core import encryption
from core.database import Database
from core.encryption import Encryption

PASSWORD = "a passphrase of decent length"


class TestTheProductionParametersAreWhatTheySay:
    def test_they_are_pinned_exactly(self):
        """THE GUARD THAT MATTERS MOST IN THIS FILE.

        Everything else here is about keeping the cheap path contained.
        This is the one that notices if the cheap values ever become the
        real ones — the failure that would ship a lawyer's correspondence
        archive derived at 1 MiB and say nothing. Asserted as literals,
        not against the fast constants, so a typo in either cannot make
        both agree.
        """
        assert encryption.ARGON2_TIME_COST == 6
        assert encryption.ARGON2_MEMORY_COST == 262_144
        assert encryption.ARGON2_PARALLELISM == 1
        assert encryption.ARGON2_KEY_LENGTH == 32

    def test_the_fast_values_are_unmistakably_cheaper(self):
        assert encryption.ARGON2_FAST_TIME_COST < encryption.ARGON2_TIME_COST
        assert encryption.ARGON2_FAST_MEMORY_COST < encryption.ARGON2_MEMORY_COST


class TestTheCheapPathNeedsBothKeys:
    """The parameters are not in the key file. An archive created cheaply
    cannot be opened at production strength, so the cheap path must be
    unreachable by accident."""

    def test_the_default_is_production(self, monkeypatch):
        monkeypatch.delenv("MAILREPO_FAST_KDF", raising=False)
        monkeypatch.delenv("MAILREPO_DATA_DIR", raising=False)
        assert encryption.argon2_parameters() == (6, 262_144, 1)

    def test_the_fast_flag_alone_does_nothing(self, monkeypatch):
        """A real install has no data-dir override, so it cannot reach
        the cheap path however the environment is configured."""
        monkeypatch.setenv("MAILREPO_FAST_KDF", "1")
        monkeypatch.delenv("MAILREPO_DATA_DIR", raising=False)
        assert encryption.argon2_parameters() == (6, 262_144, 1)

    def test_a_sandbox_alone_does_nothing(self, tmp_path, monkeypatch):
        """MAILREPO_DATA_DIR is a supported override — a future package
        or a second archive on one machine may legitimately set it. Its
        archives must derive at production strength, or moving one back
        to a default install would leave it unopenable."""
        monkeypatch.setenv("MAILREPO_DATA_DIR", str(tmp_path))
        monkeypatch.delenv("MAILREPO_FAST_KDF", raising=False)
        assert encryption.argon2_parameters() == (6, 262_144, 1)

    def test_both_together_are_cheap(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MAILREPO_DATA_DIR", str(tmp_path))
        monkeypatch.setenv("MAILREPO_FAST_KDF", "1")
        assert encryption.argon2_parameters() == (
            encryption.ARGON2_FAST_TIME_COST,
            encryption.ARGON2_FAST_MEMORY_COST,
            1,
        )


class TestTheProductionPathStillRunsForReal:
    """The rest of the suite proves the archive works. These two prove it
    works AT PRODUCTION STRENGTH, which the rest can no longer speak to.

    Deliberately slow — several seconds between them — and worth every
    second: without these, nothing in 600-odd tests would notice if the
    production parameters stopped working while the cheap ones kept
    passing.
    """

    @pytest.fixture(autouse=True)
    def full_cost(self, monkeypatch):
        # conftest keeps MAILREPO_DATA_DIR pointed at the per-test temp
        # dir (so nothing here touches a real install); dropping only the
        # fast flag puts derivation back at production strength.
        monkeypatch.delenv("MAILREPO_FAST_KDF", raising=False)
        Database.close()
        Encryption.lock()
        yield
        Database.close()
        Encryption.lock()

    def test_a_v3_archive_created_at_full_cost_opens_at_full_cost(self):
        """Both credentials, both wrappers, production work factor."""
        recovery_key = Encryption.initialize_v3(PASSWORD)
        Encryption.lock()

        assert Encryption.unlock(PASSWORD)
        assert Encryption.verify_recovery_key(recovery_key)

    def test_derivation_is_actually_expensive(self):
        """Pinned as a FLOOR, not a figure. Argon2id's whole purpose is
        to cost real time and real memory; a parameter change that
        quietly made it cheap would leave every other test green.

        A quarter of a second is far below the ~750ms measured on the M4
        and ~1s on Apollo, chosen so a slower machine — or a busy one —
        does not fail this. It is nowhere near the milliseconds the cheap
        path takes, which is the distinction being drawn.
        """
        Encryption.initialize_v3(PASSWORD)
        Encryption.lock()

        started = time.perf_counter()
        assert Encryption.unlock(PASSWORD)
        elapsed = time.perf_counter() - started

        assert elapsed > 0.25, (
            f"a password unlock took {elapsed:.3f}s — production Argon2id "
            f"should cost far more than this"
        )
