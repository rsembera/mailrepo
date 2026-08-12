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
