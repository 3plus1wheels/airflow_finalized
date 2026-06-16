from datetime import datetime, timezone
from io import BytesIO
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework.test import APIClient

from storage_api.models import AccessGroup, UserProfile, VisibilityGrant


def set_role(user, role):
    UserProfile.objects.update_or_create(user=user, defaults={"role": role})
    return user


def object_fixture(key, size=5):
    return {
        "Key": key,
        "Size": size,
        "LastModified": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "ETag": '"abc"',
    }


class AuthAndAdminTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.superuser = get_user_model().objects.create_superuser(
            username="root",
            password="password123",
        )
        self.admin = set_role(
            get_user_model().objects.create_user(username="manager", password="password123"),
            UserProfile.ROLE_ADMIN,
        )

    def test_register_disabled_and_me_includes_role_permissions(self):
        register_response = self.client.post(
            reverse("register"),
            {"username": "alice", "password": "password123"},
            format="json",
        )
        self.assertEqual(register_response.status_code, 403)

        token_response = self.client.post(
            reverse("token_obtain_pair"),
            {"username": "root", "password": "password123"},
            format="json",
        )
        self.assertEqual(token_response.status_code, 200)
        self.assertIn("access_token", token_response.cookies)
        self.assertTrue(token_response.cookies["access_token"]["httponly"])
        self.assertIn("refresh_token", token_response.cookies)
        self.assertTrue(token_response.cookies["refresh_token"]["httponly"])
        self.assertIn("csrftoken", token_response.cookies)

        me_response = self.client.get(reverse("me"))
        self.assertEqual(me_response.status_code, 200)
        self.assertEqual(me_response.data["role"], "superuser")
        self.assertTrue(me_response.data["permissions"]["can_manage_admins"])

        logout_response = self.client.post(
            reverse("token_logout"),
            HTTP_X_CSRFTOKEN=token_response.cookies["csrftoken"].value,
        )
        self.assertEqual(logout_response.status_code, 204)
        self.assertEqual(logout_response.cookies["access_token"].value, "")

    @patch("storage_api.views.get_s3_client")
    def test_cookie_auth_requires_csrf_for_unsafe_requests(self, get_s3_client):
        s3 = Mock()
        get_s3_client.return_value = s3
        client = APIClient(enforce_csrf_checks=True)
        token_response = client.post(
            reverse("token_obtain_pair"),
            {"username": "root", "password": "password123"},
            format="json",
        )
        self.assertEqual(token_response.status_code, 200)

        forbidden_response = client.post(reverse("bucket-list-create"), {"name": "csrf-bucket"}, format="json")
        self.assertEqual(forbidden_response.status_code, 403)

        allowed_response = client.post(
            reverse("bucket-list-create"),
            {"name": "csrf-bucket"},
            format="json",
            HTTP_X_CSRFTOKEN=token_response.cookies["csrftoken"].value,
        )
        self.assertEqual(allowed_response.status_code, 201)
        s3.create_bucket.assert_called_once_with(Bucket="csrf-bucket")

    def test_auth_endpoints_ignore_stale_invalid_access_cookie(self):
        client = APIClient()
        client.cookies["access_token"] = "stale.invalid.token"

        token_response = client.post(
            reverse("token_obtain_pair"),
            {"username": "root", "password": "password123"},
            format="json",
        )
        self.assertEqual(token_response.status_code, 200)
        self.assertIn("access_token", token_response.cookies)

        refresh_response = client.post(reverse("token_refresh"), {}, format="json")
        self.assertEqual(refresh_response.status_code, 200)
        self.assertIn("access_token", refresh_response.cookies)

        client.cookies["access_token"] = "stale.invalid.token"
        logout_response = client.post(reverse("token_logout"))
        self.assertEqual(logout_response.status_code, 204)
        self.assertEqual(logout_response.cookies["access_token"].value, "")

    def test_superuser_can_create_admin_editor_viewer_and_grants(self):
        self.client.force_authenticate(self.superuser)

        for role in (UserProfile.ROLE_ADMIN, UserProfile.ROLE_EDITOR, UserProfile.ROLE_VIEWER):
            response = self.client.post(
                reverse("user-list-create"),
                {"username": f"{role}user", "password": "password123", "role": role},
                format="json",
            )
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.data["role"], role)

        grant_response = self.client.post(
            reverse("visibility-grant-list-create"),
            {
                "target_type": VisibilityGrant.TARGET_ROLE,
                "role": UserProfile.ROLE_VIEWER,
                "bucket": "docs",
                "prefix": "public/",
                "access": VisibilityGrant.ACCESS_READ,
            },
            format="json",
        )
        self.assertEqual(grant_response.status_code, 201)
        self.assertEqual(grant_response.data["prefix"], "public/")

        group_response = self.client.post(
            reverse("group-list-create"),
            {"name": "ops", "users": [get_user_model().objects.get(username="editoruser").id]},
            format="json",
        )
        self.assertEqual(group_response.status_code, 201)
        self.assertEqual(group_response.data["name"], "ops")

    def test_admin_cannot_manage_admin_or_superuser(self):
        self.client.force_authenticate(self.admin)

        create_admin = self.client.post(
            reverse("user-list-create"),
            {"username": "newadmin", "password": "password123", "role": UserProfile.ROLE_ADMIN},
            format="json",
        )
        self.assertEqual(create_admin.status_code, 403)

        edit_super = self.client.patch(
            reverse("user-detail", kwargs={"user_id": self.superuser.id}),
            {"username": "changed"},
            format="json",
        )
        self.assertEqual(edit_super.status_code, 403)

        create_editor = self.client.post(
            reverse("user-list-create"),
            {"username": "editor", "password": "password123", "role": UserProfile.ROLE_EDITOR},
            format="json",
        )
        self.assertEqual(create_editor.status_code, 201)

    def test_admin_lists_are_paginated_and_filterable(self):
        self.client.force_authenticate(self.superuser)
        viewer = set_role(
            get_user_model().objects.create_user(username="alpha-viewer", password="password123"),
            UserProfile.ROLE_VIEWER,
        )
        editor = set_role(
            get_user_model().objects.create_user(username="beta-editor", password="password123"),
            UserProfile.ROLE_EDITOR,
        )
        group = AccessGroup.objects.create(name="ops-alpha")
        group.users.add(viewer, editor)
        VisibilityGrant.objects.create(
            target_type=VisibilityGrant.TARGET_GROUP,
            group=group,
            bucket="docs",
            prefix="public/",
            access=VisibilityGrant.ACCESS_WRITE,
        )

        users_response = self.client.get(
            reverse("user-list-create"),
            {"q": "alpha", "role": UserProfile.ROLE_VIEWER, "page_size": "1"},
        )
        self.assertEqual(users_response.status_code, 200)
        self.assertEqual(users_response.data["page_size"], 1)
        self.assertEqual(users_response.data["count"], 1)
        self.assertEqual(users_response.data["results"][0]["username"], "alpha-viewer")

        groups_response = self.client.get(reverse("group-list-create"), {"q": "alpha"})
        self.assertEqual(groups_response.status_code, 200)
        self.assertEqual(groups_response.data["count"], 1)
        self.assertEqual(groups_response.data["results"][0]["member_count"], 2)
        self.assertEqual(groups_response.data["results"][0]["member_preview"][0]["username"], "alpha-viewer")

        grants_response = self.client.get(
            reverse("visibility-grant-list-create"),
            {"target_type": "group", "bucket": "docs", "access": "write"},
        )
        self.assertEqual(grants_response.status_code, 200)
        self.assertEqual(grants_response.data["count"], 1)
        self.assertEqual(grants_response.data["results"][0]["group_name"], "ops-alpha")

    def test_group_list_uses_bounded_queries(self):
        self.client.force_authenticate(self.superuser)
        users = [
            set_role(
                get_user_model().objects.create_user(username=f"member-{index}", password="password123"),
                UserProfile.ROLE_VIEWER,
            )
            for index in range(5)
        ]
        for index in range(5):
            group = AccessGroup.objects.create(name=f"ops-{index}")
            group.users.add(*users)

        with CaptureQueriesContext(connection) as captured:
            response = self.client.get(reverse("group-list-create"), {"page_size": "5"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 5)
        self.assertEqual(len(response.data["results"]), 5)
        self.assertLessEqual(len(captured), 4)

    def test_admin_query_indexes_exist(self):
        with connection.cursor() as cursor:
            profile_indexes = connection.introspection.get_constraints(cursor, UserProfile._meta.db_table)
            grant_indexes = connection.introspection.get_constraints(cursor, VisibilityGrant._meta.db_table)

        self.assertIn("userprofile_role_idx", profile_indexes)
        self.assertIn("grant_admin_order_idx", grant_indexes)
        self.assertIn("grant_bucket_access_idx", grant_indexes)
        self.assertIn("grant_target_access_idx", grant_indexes)


class StorageApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = set_role(
            get_user_model().objects.create_user(username="admin", password="password123"),
            UserProfile.ROLE_ADMIN,
        )
        self.editor = set_role(
            get_user_model().objects.create_user(username="editor", password="password123"),
            UserProfile.ROLE_EDITOR,
        )
        self.viewer = set_role(
            get_user_model().objects.create_user(username="viewer", password="password123"),
            UserProfile.ROLE_VIEWER,
        )

    def mock_s3(self, get_s3_client):
        s3 = Mock()
        get_s3_client.return_value = s3
        created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        s3.list_buckets.return_value = {
            "Buckets": [
                {"Name": "docs", "CreationDate": created_at},
                {"Name": "private", "CreationDate": created_at},
            ]
        }
        s3.list_objects_v2.return_value = {
            "Contents": [
                object_fixture("public/readme.txt"),
                object_fixture("publicity/secret.txt"),
                object_fixture("private/secret.txt"),
                object_fixture("editor/upload.txt"),
            ]
        }
        s3.get_object.return_value = {
            "Body": BytesIO(b"hello"),
            "ContentType": "text/plain",
        }
        s3.head_object.return_value = {
            "ContentType": "text/plain",
            "Metadata": {},
        }
        s3.generate_presigned_url.return_value = "https://example.test/share"
        s3.get_object_tagging.return_value = {"TagSet": [{"Key": "env", "Value": "test"}]}
        s3.list_object_versions.return_value = {
            "Versions": [
                {
                    "Key": "public/readme.txt",
                    "VersionId": "1",
                    "IsLatest": True,
                    "LastModified": datetime(2026, 1, 1, tzinfo=timezone.utc),
                    "Size": 5,
                    "ETag": '"abc"',
                }
            ]
        }
        return s3

    def test_bucket_endpoints_require_auth(self):
        response = APIClient().get(reverse("bucket-list-create"))
        self.assertEqual(response.status_code, 401)

    @patch("storage_api.views.get_s3_client")
    def test_admin_can_list_create_delete_buckets(self, get_s3_client):
        self.client.force_authenticate(self.admin)
        s3 = self.mock_s3(get_s3_client)

        list_response = self.client.get(reverse("bucket-list-create"))
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual([item["name"] for item in list_response.data["buckets"]], ["docs", "private"])

        create_response = self.client.post(reverse("bucket-list-create"), {"name": "new-bucket"}, format="json")
        self.assertEqual(create_response.status_code, 201)
        s3.create_bucket.assert_called_once_with(Bucket="new-bucket")
        self.assertTrue(
            VisibilityGrant.objects.filter(
                target_type=VisibilityGrant.TARGET_ROLE,
                role=UserProfile.ROLE_VIEWER,
                bucket="new-bucket",
                access=VisibilityGrant.ACCESS_READ,
            ).exists()
        )
        self.assertTrue(
            VisibilityGrant.objects.filter(
                target_type=VisibilityGrant.TARGET_ROLE,
                role=UserProfile.ROLE_EDITOR,
                bucket="new-bucket",
                access=VisibilityGrant.ACCESS_WRITE,
            ).exists()
        )

        delete_response = self.client.delete(reverse("bucket-detail", kwargs={"bucket": "new-bucket"}))
        self.assertEqual(delete_response.status_code, 204)
        s3.delete_bucket.assert_called_once_with(Bucket="new-bucket")

    @patch("storage_api.views.get_s3_client")
    def test_bucket_can_be_restricted_to_group(self, get_s3_client):
        self.client.force_authenticate(self.admin)
        self.mock_s3(get_s3_client)
        group = AccessGroup.objects.create(name="ops")
        group.users.add(self.editor)

        response = self.client.post(
            reverse("bucket-list-create"),
            {"name": "team-bucket", "group_id": group.id, "open_to_all": False},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(
            VisibilityGrant.objects.filter(
                target_type=VisibilityGrant.TARGET_GROUP,
                group=group,
                bucket="team-bucket",
                access=VisibilityGrant.ACCESS_WRITE,
            ).exists()
        )

    @patch("storage_api.views.get_s3_client")
    def test_viewer_sees_nothing_without_grants(self, get_s3_client):
        self.client.force_authenticate(self.viewer)
        self.mock_s3(get_s3_client)

        bucket_response = self.client.get(reverse("bucket-list-create"))
        self.assertEqual(bucket_response.status_code, 200)
        self.assertEqual(bucket_response.data["buckets"], [])

        objects_response = self.client.get(reverse("object-list-create-delete", kwargs={"bucket": "docs"}))
        self.assertEqual(objects_response.status_code, 403)

    @patch("storage_api.views.get_s3_client")
    @override_settings(MINIO_PUBLIC_ENDPOINT="https://public.example")
    def test_viewer_read_prefix_grant_filters_and_blocks_writes(self, get_s3_client):
        self.client.force_authenticate(self.viewer)
        s3 = self.mock_s3(get_s3_client)
        VisibilityGrant.objects.create(
            target_type=VisibilityGrant.TARGET_ROLE,
            role=UserProfile.ROLE_VIEWER,
            bucket="docs",
            prefix="public/",
            access=VisibilityGrant.ACCESS_READ,
        )

        bucket_response = self.client.get(reverse("bucket-list-create"))
        self.assertEqual([item["name"] for item in bucket_response.data["buckets"]], ["docs"])

        list_response = self.client.get(reverse("object-list-create-delete", kwargs={"bucket": "docs"}))
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual([item["key"] for item in list_response.data["objects"]], ["public/readme.txt"])

        download_response = self.client.get(
            reverse("object-download", kwargs={"bucket": "docs"}),
            {"key": "public/readme.txt"},
        )
        self.assertEqual(download_response.status_code, 200)

        share_response = self.client.get(
            reverse("object-share", kwargs={"bucket": "docs"}),
            {"key": "public/readme.txt"},
        )
        self.assertEqual(share_response.status_code, 200)
        get_s3_client.assert_any_call(endpoint_url="https://public.example")

        upload_response = self.client.post(
            reverse("object-list-create-delete", kwargs={"bucket": "docs"}),
            {"file": BytesIO(b"hello"), "key": "public/new.txt"},
            format="multipart",
        )
        self.assertEqual(upload_response.status_code, 403)

        delete_response = self.client.delete(
            f"{reverse('object-list-create-delete', kwargs={'bucket': 'docs'})}?key=public/readme.txt",
        )
        self.assertEqual(delete_response.status_code, 403)
        s3.delete_object.assert_not_called()

    @patch("storage_api.views.get_s3_client")
    def test_prefix_grant_matches_path_boundary(self, get_s3_client):
        self.client.force_authenticate(self.viewer)
        self.mock_s3(get_s3_client)
        VisibilityGrant.objects.create(
            target_type=VisibilityGrant.TARGET_ROLE,
            role=UserProfile.ROLE_VIEWER,
            bucket="docs",
            prefix="public",
            access=VisibilityGrant.ACCESS_READ,
        )

        list_response = self.client.get(reverse("object-list-create-delete", kwargs={"bucket": "docs"}))
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual([item["key"] for item in list_response.data["objects"]], ["public/readme.txt"])

        exact_response = self.client.get(
            reverse("object-download", kwargs={"bucket": "docs"}),
            {"key": "public"},
        )
        self.assertEqual(exact_response.status_code, 200)

        boundary_response = self.client.get(
            reverse("object-download", kwargs={"bucket": "docs"}),
            {"key": "publicity/secret.txt"},
        )
        self.assertEqual(boundary_response.status_code, 403)

    @patch("storage_api.views.get_s3_client")
    def test_object_list_uses_bounded_pagination_parameters(self, get_s3_client):
        self.client.force_authenticate(self.admin)
        s3 = self.mock_s3(get_s3_client)
        s3.list_objects_v2.return_value = {
            "Contents": [object_fixture("public/readme.txt")],
            "IsTruncated": True,
            "NextContinuationToken": "next-page",
        }

        response = self.client.get(
            reverse("object-list-create-delete", kwargs={"bucket": "docs"}),
            {"prefix": "public/", "continuation_token": "page-1", "max_keys": "25"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["is_truncated"])
        self.assertEqual(response.data["next_continuation_token"], "next-page")
        s3.list_objects_v2.assert_called_once_with(
            Bucket="docs",
            MaxKeys=25,
            Prefix="public/",
            ContinuationToken="page-1",
        )

    @patch("storage_api.views.get_s3_client")
    def test_object_keys_reject_control_characters(self, get_s3_client):
        self.client.force_authenticate(self.admin)
        s3 = self.mock_s3(get_s3_client)

        upload_response = self.client.post(
            reverse("object-list-create-delete", kwargs={"bucket": "docs"}),
            {"file": BytesIO(b"hello"), "key": "bad\r\nname.txt"},
            format="multipart",
        )
        self.assertEqual(upload_response.status_code, 400)
        s3.upload_fileobj.assert_not_called()

        download_response = self.client.get(
            reverse("object-download", kwargs={"bucket": "docs"}),
            {"key": "bad\r\nname.txt"},
        )
        self.assertEqual(download_response.status_code, 400)

    @patch("storage_api.views.get_s3_client")
    def test_preview_content_disposition_escapes_filename(self, get_s3_client):
        self.client.force_authenticate(self.admin)
        s3 = self.mock_s3(get_s3_client)

        response = self.client.get(
            reverse("object-share", kwargs={"bucket": "docs"}),
            {"key": 'public/bad"name.txt', "preview": "true"},
        )
        self.assertEqual(response.status_code, 200)
        params = s3.generate_presigned_url.call_args.kwargs["Params"]
        self.assertEqual(params["ResponseContentDisposition"], "inline; filename=\"bad\\\"name.txt\"")

    @patch("storage_api.views.get_s3_client")
    def test_editor_write_prefix_and_user_specific_grants(self, get_s3_client):
        self.client.force_authenticate(self.editor)
        s3 = self.mock_s3(get_s3_client)
        VisibilityGrant.objects.create(
            target_type=VisibilityGrant.TARGET_ROLE,
            role=UserProfile.ROLE_EDITOR,
            bucket="docs",
            prefix="editor/",
            access=VisibilityGrant.ACCESS_WRITE,
        )
        VisibilityGrant.objects.create(
            target_type=VisibilityGrant.TARGET_USER,
            user=self.editor,
            bucket="docs",
            prefix="public/",
            access=VisibilityGrant.ACCESS_READ,
        )

        list_response = self.client.get(reverse("object-list-create-delete", kwargs={"bucket": "docs"}))
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(
            [item["key"] for item in list_response.data["objects"]],
            ["public/readme.txt", "editor/upload.txt"],
        )

        upload_response = self.client.post(
            reverse("object-list-create-delete", kwargs={"bucket": "docs"}),
            {"file": BytesIO(b"hello"), "key": "editor/new.txt"},
            format="multipart",
        )
        self.assertEqual(upload_response.status_code, 201)

        tag_response = self.client.put(
            f"{reverse('object-tags', kwargs={'bucket': 'docs'})}?key=editor/upload.txt",
            {"tags": {"team": "ops"}},
            format="json",
        )
        self.assertEqual(tag_response.status_code, 200)

        forbidden_upload = self.client.post(
            reverse("object-list-create-delete", kwargs={"bucket": "docs"}),
            {"file": BytesIO(b"hello"), "key": "public/new.txt"},
            format="multipart",
        )
        self.assertEqual(forbidden_upload.status_code, 403)

        delete_response = self.client.delete(
            f"{reverse('object-list-create-delete', kwargs={'bucket': 'docs'})}?key=editor/upload.txt",
        )
        self.assertEqual(delete_response.status_code, 204)
        s3.delete_object.assert_called()
