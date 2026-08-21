"""
Tests for web/blueprints/api/folders.py - Folder management API.
"""


class TestFolderCreation:
    """Tests for creating archive folders."""

    def test_create_folder(self, authenticated_client, initialized_app):
        """Should create a folder at root level."""
        response = authenticated_client.post(
            "/api/folders", json={"name": "Client Files"}, content_type="application/json"
        )

        assert response.status_code == 201
        data = response.get_json()
        assert data["folder"]["name"] == "Client Files"
        assert data["folder"]["parent_id"] is None

    def test_create_nested_folder(self, authenticated_client, initialized_app):
        """Should create a nested folder."""
        # Create parent
        response = authenticated_client.post(
            "/api/folders", json={"name": "Clients"}, content_type="application/json"
        )
        parent_id = response.get_json()["folder"]["id"]

        # Create child
        response = authenticated_client.post(
            "/api/folders",
            json={"name": "John Smith", "parent_id": parent_id},
            content_type="application/json",
        )

        assert response.status_code == 201
        data = response.get_json()
        assert data["folder"]["name"] == "John Smith"
        assert data["folder"]["parent_id"] == parent_id

    def test_create_folder_empty_name_rejected(self, authenticated_client, initialized_app):
        """Should reject empty folder names."""
        response = authenticated_client.post(
            "/api/folders", json={"name": ""}, content_type="application/json"
        )

        assert response.status_code == 400
        assert "required" in response.get_json()["error"].lower()

    def test_create_folder_duplicate_name_rejected(self, authenticated_client, initialized_app):
        """Should reject duplicate names at same level."""
        authenticated_client.post(
            "/api/folders", json={"name": "Unique Name"}, content_type="application/json"
        )

        response = authenticated_client.post(
            "/api/folders", json={"name": "Unique Name"}, content_type="application/json"
        )

        assert response.status_code == 400
        assert "already exists" in response.get_json()["error"].lower()


class TestFolderListing:
    """Tests for listing folders."""

    def test_list_folders_empty(self, authenticated_client, initialized_app):
        """Should return empty list when no folders exist."""
        response = authenticated_client.get("/api/folders")

        assert response.status_code == 200
        assert response.get_json()["folders"] == []

    def test_list_folders(self, authenticated_client, initialized_app):
        """Should return all folders."""
        # Create some folders
        authenticated_client.post("/api/folders", json={"name": "Folder A"})
        authenticated_client.post("/api/folders", json={"name": "Folder B"})

        response = authenticated_client.get("/api/folders")

        assert response.status_code == 200
        folders = response.get_json()["folders"]
        assert len(folders) == 2
        names = [f["name"] for f in folders]
        assert "Folder A" in names
        assert "Folder B" in names


class TestFolderDeletion:
    """Tests for soft-deleting folders."""

    def test_delete_folder(self, authenticated_client, initialized_app):
        """Should soft-delete a folder."""
        # Create folder
        response = authenticated_client.post("/api/folders", json={"name": "To Delete"})
        folder_id = response.get_json()["folder"]["id"]

        # Delete it
        response = authenticated_client.delete(f"/api/folders/{folder_id}")

        assert response.status_code == 200
        assert response.get_json()["success"] is True

        # Should still exist but with deleted_at set
        response = authenticated_client.get("/api/folders")
        folders = response.get_json()["folders"]
        deleted = [f for f in folders if f["id"] == folder_id]
        assert len(deleted) == 1
        assert deleted[0]["deleted_at"] is not None

    def test_delete_folder_with_children(self, authenticated_client, initialized_app):
        """Should soft-delete folder and all children."""
        # Create parent
        response = authenticated_client.post("/api/folders", json={"name": "Parent"})
        parent_id = response.get_json()["folder"]["id"]

        # Create child
        response = authenticated_client.post(
            "/api/folders", json={"name": "Child", "parent_id": parent_id}
        )
        child_id = response.get_json()["folder"]["id"]

        # Delete parent
        authenticated_client.delete(f"/api/folders/{parent_id}")

        # Both should be deleted
        response = authenticated_client.get("/api/folders")
        folders = response.get_json()["folders"]

        parent = next(f for f in folders if f["id"] == parent_id)
        child = next(f for f in folders if f["id"] == child_id)

        assert parent["deleted_at"] is not None
        assert child["deleted_at"] is not None


class TestFolderRestore:
    """Tests for restoring folders from trash."""

    def test_restore_folder(self, authenticated_client, initialized_app):
        """Should restore a deleted folder."""
        # Create and delete
        response = authenticated_client.post("/api/folders", json={"name": "Restore Me"})
        folder_id = response.get_json()["folder"]["id"]
        authenticated_client.delete(f"/api/folders/{folder_id}")

        # Restore
        response = authenticated_client.post(f"/api/folders/{folder_id}/restore")

        assert response.status_code == 200
        assert response.get_json()["success"] is True

        # Should no longer have deleted_at
        response = authenticated_client.get("/api/folders")
        folder = next(f for f in response.get_json()["folders"] if f["id"] == folder_id)
        assert folder["deleted_at"] is None

    def test_restore_renames_on_conflict(self, authenticated_client, initialized_app):
        """Should rename folder if name conflicts on restore."""
        # Create original
        response = authenticated_client.post("/api/folders", json={"name": "Conflict"})
        folder_id = response.get_json()["folder"]["id"]

        # Delete it
        authenticated_client.delete(f"/api/folders/{folder_id}")

        # Create new folder with same name
        authenticated_client.post("/api/folders", json={"name": "Conflict"})

        # Restore original - should get renamed
        response = authenticated_client.post(f"/api/folders/{folder_id}/restore")

        assert response.status_code == 200
        data = response.get_json()
        assert data["folder"]["renamed"] is True
        assert data["folder"]["name"] == "Conflict (2)"


class TestRetentionVaultPeriods:
    """Retention periods are statutory and vary by jurisdiction and
    profession, so the UI presets (1/3/5/7/10 years) are shortcuts, not
    the supported range."""

    def _make_folder(self, client, name):
        response = client.post(
            "/api/folders", json={"name": name}, content_type="application/json"
        )
        assert response.status_code == 201
        return response.get_json()["folder"]["id"]

    def test_accepts_an_arbitrary_retention_period(
        self, authenticated_client, initialized_app
    ):
        """15 years is not a preset, and is a common medical-records term."""
        import time

        folder_id = self._make_folder(authenticated_client, "Medical Records")
        fifteen_years = int(time.time()) + (15 * 365 * 24 * 3600)

        response = authenticated_client.post(
            f"/api/folders/{folder_id}/vault",
            json={"retention_date": fifteen_years},
            content_type="application/json",
        )
        assert response.status_code == 200

        listing = authenticated_client.get("/api/folders").get_json()
        folder = next(f for f in listing["folders"] if f["id"] == folder_id)
        assert folder["retention_date"] == fifteen_years

    def test_accepts_a_period_longer_than_every_preset(
        self, authenticated_client, initialized_app
    ):
        """Some obligations run for decades — 'life of the client plus N'
        can exceed anything on the preset row."""
        import time

        folder_id = self._make_folder(authenticated_client, "Estate Files")
        fifty_years = int(time.time()) + (50 * 365 * 24 * 3600)

        response = authenticated_client.post(
            f"/api/folders/{folder_id}/vault",
            json={"retention_date": fifty_years},
            content_type="application/json",
        )
        assert response.status_code == 200

    def test_rejects_a_non_numeric_retention_date(
        self, authenticated_client, initialized_app
    ):
        folder_id = self._make_folder(authenticated_client, "Bad Input")
        response = authenticated_client.post(
            f"/api/folders/{folder_id}/vault",
            json={"retention_date": "fifteen"},
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_rejects_a_missing_retention_date(
        self, authenticated_client, initialized_app
    ):
        folder_id = self._make_folder(authenticated_client, "No Date")
        response = authenticated_client.post(
            f"/api/folders/{folder_id}/vault",
            json={},
            content_type="application/json",
        )
        assert response.status_code == 400


class TestVaultSubfolderCounts:
    """A vault folder holding nothing directly but everything in its
    subfolders used to show (100) in the list and "0 emails" when opened.
    The list is right -- permanent deletion takes the whole tree -- so the
    endpoint hands back a tree count for every vault folder, letting the
    folder view say where those emails actually are."""

    def _make_folder(self, client, name, parent_id=None):
        payload = {"name": name}
        if parent_id is not None:
            payload["parent_id"] = parent_id
        response = client.post("/api/folders", json=payload, content_type="application/json")
        assert response.status_code == 201
        return response.get_json()["folder"]["id"]

    def _add_messages(self, folder_id, count, deleted=False):
        import secrets

        from core import Database

        for _ in range(count):
            token = secrets.token_hex(6)
            Database.execute(
                """INSERT INTO messages
                   (folder_id, message_id, subject, filepath, deleted_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    folder_id,
                    f"<{token}@test>",
                    "Retained correspondence",
                    f"archive/{folder_id}/{token}.eml.enc",
                    1739633400 if deleted else None,
                ),
            )
        Database.commit()

    def _vault(self, client, folder_id):
        import time

        response = client.post(
            f"/api/folders/{folder_id}/vault",
            json={"retention_date": int(time.time()) + (7 * 365 * 24 * 3600)},
            content_type="application/json",
        )
        assert response.status_code == 200

    def test_counts_are_returned_for_subfolders_not_just_the_top(
        self, authenticated_client, initialized_app
    ):
        """The subfolder numbers have to add up to the number the Vault
        list shows against their parent."""
        parent_id = self._make_folder(authenticated_client, "20240502-EK")
        child_2024 = self._make_folder(authenticated_client, "2024", parent_id)
        child_2025 = self._make_folder(authenticated_client, "2025", parent_id)
        self._add_messages(child_2024, 6)
        self._add_messages(child_2025, 4)
        self._vault(authenticated_client, parent_id)

        data = authenticated_client.get("/api/folders/vault").get_json()

        counts = data["counts"]
        assert counts[str(child_2024)] == 6
        assert counts[str(child_2025)] == 4
        assert counts[str(parent_id)] == 10

        listed = next(f for f in data["folders"] if f["id"] == parent_id)
        assert listed["email_count"] == counts[str(parent_id)]

    def test_a_parent_holding_nothing_directly_still_counts_its_tree(
        self, authenticated_client, initialized_app
    ):
        """The reported case: nothing in the folder itself, everything one
        level down."""
        parent_id = self._make_folder(authenticated_client, "Empty Parent")
        child_id = self._make_folder(authenticated_client, "2025", parent_id)
        self._add_messages(child_id, 3)
        self._vault(authenticated_client, parent_id)

        data = authenticated_client.get("/api/folders/vault").get_json()

        assert data["counts"][str(parent_id)] == 3
        emails = authenticated_client.get(f"/api/folders/{parent_id}/emails").get_json()
        assert emails["emails"] == []

    def test_counts_reach_through_more_than_one_level(
        self, authenticated_client, initialized_app
    ):
        """Client folders nest deeper than one year of correspondence."""
        top_id = self._make_folder(authenticated_client, "Client")
        mid_id = self._make_folder(authenticated_client, "2025", top_id)
        leaf_id = self._make_folder(authenticated_client, "Q3", mid_id)
        self._add_messages(leaf_id, 5)
        self._vault(authenticated_client, top_id)

        counts = authenticated_client.get("/api/folders/vault").get_json()["counts"]

        assert counts[str(leaf_id)] == 5
        assert counts[str(mid_id)] == 5
        assert counts[str(top_id)] == 5

    def test_counts_ignore_soft_deleted_emails(self, authenticated_client, initialized_app):
        """Trashed emails are not in the folder, so they must not inflate
        the number the folder view explains."""
        parent_id = self._make_folder(authenticated_client, "Mixed")
        child_id = self._make_folder(authenticated_client, "2025", parent_id)
        self._add_messages(child_id, 2)
        self._add_messages(child_id, 7, deleted=True)
        self._vault(authenticated_client, parent_id)

        counts = authenticated_client.get("/api/folders/vault").get_json()["counts"]

        assert counts[str(child_id)] == 2
        assert counts[str(parent_id)] == 2

    def test_folders_outside_the_vault_are_not_counted(
        self, authenticated_client, initialized_app
    ):
        """counts is keyed by vault folder; an ordinary archive folder has
        no business being in it."""
        vault_parent = self._make_folder(authenticated_client, "Retained")
        self._add_messages(vault_parent, 1)
        self._vault(authenticated_client, vault_parent)
        ordinary_id = self._make_folder(authenticated_client, "Active Matter")
        self._add_messages(ordinary_id, 9)

        counts = authenticated_client.get("/api/folders/vault").get_json()["counts"]

        assert str(vault_parent) in counts
        assert str(ordinary_id) not in counts
