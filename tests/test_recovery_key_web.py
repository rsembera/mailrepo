"""
End-to-end tests for the recovery-key web flow.

The crypto is covered elsewhere; these exercise the wiring — routes,
templates, sessions — because that is where this feature can fail in ways
the unit tests cannot see.

One thing worth stating explicitly, because it is a security property and
not a detail: the recovery key must never be placed in the Flask session.
Sessions are SIGNED, not encrypted, so anything put there is readable in
the browser's cookie jar. test_recovery_key_never_enters_the_session is
the guard.
"""

import pytest

from core.encryption import Encryption

PASSWORD = "TestPassword123!"
NEW_PASSWORD = "BrandNewPassword789!"


def extract_recovery_key(html):
    """Pull the key out of the rendered page."""
    marker = 'id="recovery-key-value">'
    start = html.index(marker) + len(marker)
    end = html.index("<", start)
    return html[start:end].strip()


@pytest.fixture
def fresh_client(app):
    """A client against an app with no archive set up yet."""
    return app.test_client()


class TestSetupFlow:
    def test_setup_creates_v3_and_shows_the_key(self, fresh_client):
        response = fresh_client.post(
            "/auth/setup",
            data={"password": PASSWORD, "confirm": PASSWORD},
        )
        assert response.status_code == 200
        html = response.get_data(as_text=True)

        assert "Save your recovery key" in html
        key = extract_recovery_key(html)
        assert len(key.split("-")) == 8

        assert Encryption.salt_file_version() == 3
        assert Encryption.unlock_with_recovery_key(key)

    def test_recovery_key_never_enters_the_session(self, fresh_client):
        """Flask sessions are signed, not encrypted.

        A recovery key in the session cookie would be readable by anything
        with access to the browser profile.
        """
        response = fresh_client.post(
            "/auth/setup",
            data={"password": PASSWORD, "confirm": PASSWORD},
        )
        key = extract_recovery_key(response.get_data(as_text=True))

        with fresh_client.session_transaction() as sess:
            for value in sess.values():
                assert key not in str(value)

        cookies = response.headers.getlist("Set-Cookie")
        for cookie in cookies:
            assert key not in cookie
            # base32 groups would survive urlencoding intact, so a naive
            # check on the whole key is sufficient here.

    def test_setup_still_rejects_short_and_mismatched_passwords(self, fresh_client):
        response = fresh_client.post(
            "/auth/setup", data={"password": "short", "confirm": "short"}
        )
        assert "at least 12 characters" in response.get_data(as_text=True)
        assert not Encryption.is_initialized()

        response = fresh_client.post(
            "/auth/setup", data={"password": PASSWORD, "confirm": "Different123!"}
        )
        assert "do not match" in response.get_data(as_text=True)
        assert not Encryption.is_initialized()


class TestRecoveryLogin:
    @pytest.fixture
    def archive(self, fresh_client):
        response = fresh_client.post(
            "/auth/setup", data={"password": PASSWORD, "confirm": PASSWORD}
        )
        key = extract_recovery_key(response.get_data(as_text=True))
        fresh_client.post("/auth/logout")
        return {"client": fresh_client, "key": key}

    def test_login_page_offers_the_recovery_link(self, archive):
        html = archive["client"].get("/auth/login").get_data(as_text=True)
        assert "/auth/login/recovery" in html

    def test_recovery_key_unlocks_and_redirects_to_password_reset(self, archive):
        response = archive["client"].post(
            "/auth/login/recovery",
            data={"recovery_key": archive["key"]},
        )
        assert response.status_code == 302
        assert "new-password" in response.headers["Location"]
        assert Encryption.is_unlocked()

    def test_formatting_variations_are_accepted(self, archive):
        mangled = archive["key"].lower().replace("-", " ")
        response = archive["client"].post(
            "/auth/login/recovery", data={"recovery_key": mangled}
        )
        assert response.status_code == 302

    def test_wrong_key_is_rejected(self, archive):
        response = archive["client"].post(
            "/auth/login/recovery",
            data={"recovery_key": Encryption.generate_recovery_key()},
        )
        assert response.status_code == 200
        assert "does not open this archive" in response.get_data(as_text=True)

    def test_mistyped_key_says_so_rather_than_wrong_key(self, archive):
        """A typo and a wrong key are different problems."""
        response = archive["client"].post(
            "/auth/login/recovery", data={"recovery_key": "TOO-SHORT"}
        )
        html = response.get_data(as_text=True)
        assert "characters" in html
        assert "does not open this archive" not in html

    def test_new_password_after_recovery_works(self, archive):
        client = archive["client"]
        client.post("/auth/login/recovery", data={"recovery_key": archive["key"]})

        response = client.post(
            "/auth/login/recovery/new-password",
            data={"password": NEW_PASSWORD, "confirm": NEW_PASSWORD},
        )
        assert response.status_code == 302

        Encryption.lock()
        assert Encryption.unlock(NEW_PASSWORD)

    def test_recovery_key_survives_the_password_reset(self, archive):
        client = archive["client"]
        client.post("/auth/login/recovery", data={"recovery_key": archive["key"]})
        client.post(
            "/auth/login/recovery/new-password",
            data={"password": NEW_PASSWORD, "confirm": NEW_PASSWORD},
        )

        Encryption.lock()
        assert Encryption.unlock_with_recovery_key(archive["key"])

    def test_password_reset_page_requires_a_session(self, archive):
        Encryption.lock()
        response = archive["client"].get("/auth/login/recovery/new-password")
        assert response.status_code == 302
        assert "login" in response.headers["Location"]
