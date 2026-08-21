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


class TestSubfolderEmailCounts:
    """A folder holding nothing directly but everything in its subfolders
    used to read as empty -- loudest in the Retention Vault, where the list
    said 100 and the folder opened at zero. The list is right: permanent
    deletion takes the whole tree. So the folder-emails endpoint now hands
    back a tree count for each direct subfolder, and both the archive view
    and the vault view use it to say where the mail actually is."""

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
                    "Client correspondence",
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

    def _counts(self, client, folder_id):
        response = client.get(f"/api/folders/{folder_id}/emails")
        assert response.status_code == 200
        return response.get_json()["subfolder_counts"]

    def test_each_subfolder_reports_its_own_count(
        self, authenticated_client, initialized_app
    ):
        """The reported case: nothing in the folder itself, everything one
        level down, and the numbers have to add up to the parent's."""
        parent_id = self._make_folder(authenticated_client, "20240502-EK")
        child_2024 = self._make_folder(authenticated_client, "2024", parent_id)
        child_2025 = self._make_folder(authenticated_client, "2025", parent_id)
        self._add_messages(child_2024, 6)
        self._add_messages(child_2025, 4)

        body = authenticated_client.get(f"/api/folders/{parent_id}/emails").get_json()

        assert body["emails"] == []
        assert body["subfolder_counts"][str(child_2024)] == 6
        assert body["subfolder_counts"][str(child_2025)] == 4
        assert sum(body["subfolder_counts"].values()) == 10

    def test_a_subfolder_count_reaches_all_the_way_down(
        self, authenticated_client, initialized_app
    ):
        """Client folders nest deeper than one year of correspondence, so a
        subfolder's number covers its own subfolders too."""
        top_id = self._make_folder(authenticated_client, "Client")
        mid_id = self._make_folder(authenticated_client, "2025", top_id)
        leaf_id = self._make_folder(authenticated_client, "Q3", mid_id)
        self._add_messages(mid_id, 2)
        self._add_messages(leaf_id, 5)

        assert self._counts(authenticated_client, top_id)[str(mid_id)] == 7
        assert self._counts(authenticated_client, mid_id)[str(leaf_id)] == 5

    def test_counts_ignore_soft_deleted_emails(self, authenticated_client, initialized_app):
        """Trashed emails are not in the folder, so they must not inflate
        the number that explains where the mail went."""
        parent_id = self._make_folder(authenticated_client, "Mixed")
        child_id = self._make_folder(authenticated_client, "2025", parent_id)
        self._add_messages(child_id, 2)
        self._add_messages(child_id, 7, deleted=True)

        assert self._counts(authenticated_client, parent_id)[str(child_id)] == 2

    def test_counts_ignore_trashed_subfolders(self, authenticated_client, initialized_app):
        """A subfolder in the trash is not linked in the view, so it has no
        count to report."""
        parent_id = self._make_folder(authenticated_client, "Parent")
        kept_id = self._make_folder(authenticated_client, "2025", parent_id)
        trashed_id = self._make_folder(authenticated_client, "Old", parent_id)
        self._add_messages(kept_id, 3)
        self._add_messages(trashed_id, 9)
        assert authenticated_client.delete(f"/api/folders/{trashed_id}").status_code == 200

        counts = self._counts(authenticated_client, parent_id)

        assert counts[str(kept_id)] == 3
        assert str(trashed_id) not in counts

    def test_the_vault_list_total_matches_its_subfolder_counts(
        self, authenticated_client, initialized_app
    ):
        """The Vault list counts the tree because that is what permanent
        deletion destroys; opening the folder must account for the same
        emails rather than contradicting the row."""
        parent_id = self._make_folder(authenticated_client, "20240502-EK")
        child_2024 = self._make_folder(authenticated_client, "2024", parent_id)
        child_2025 = self._make_folder(authenticated_client, "2025", parent_id)
        self._add_messages(child_2024, 6)
        self._add_messages(child_2025, 4)
        self._vault(authenticated_client, parent_id)

        listed = authenticated_client.get("/api/folders/vault").get_json()["folders"]
        row = next(f for f in listed if f["id"] == parent_id)
        body = authenticated_client.get(f"/api/folders/{parent_id}/emails").get_json()

        assert row["email_count"] == 10
        assert len(body["emails"]) + sum(body["subfolder_counts"].values()) == row["email_count"]

    def test_a_folder_with_no_subfolders_reports_none(
        self, authenticated_client, initialized_app
    ):
        """Nothing to explain, so nothing extra on screen."""
        folder_id = self._make_folder(authenticated_client, "Flat")
        self._add_messages(folder_id, 3)

        body = authenticated_client.get(f"/api/folders/{folder_id}/emails").get_json()

        assert len(body["emails"]) == 3
        assert body["subfolder_counts"] == {}
