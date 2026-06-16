import mimetypes
from math import ceil

from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.contrib.auth import get_user_model
from django.middleware.csrf import get_token
from django.http import FileResponse
from django.db.models import Count, Prefetch, Q
from django.utils.http import content_disposition_header
from django.utils.dateparse import parse_datetime
from django.utils.timezone import is_naive, make_aware
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer, TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken

from storage_api.models import AccessGroup, UserProfile, VisibilityGrant
from storage_api.minio_client import get_s3_client
from storage_api.serializers import (
    AccessGroupSerializer,
    AccessGroupListSerializer,
    BucketSerializer,
    ObjectUploadSerializer,
    RegisterSerializer,
    UserAdminSerializer,
    VisibilityGrantSerializer,
    validate_object_key_value,
)


def error_response(exc, status_code=status.HTTP_400_BAD_REQUEST):
    if isinstance(exc, ClientError):
        detail = exc.response.get("Error", {}).get("Message", str(exc))
    else:
        detail = str(exc)
    return Response({"detail": detail}, status=status_code)


def guess_content_type(key):
    return mimetypes.guess_type(key)[0] or "application/octet-stream"


def get_optional_version_id(request):
    version_id = request.query_params.get("version_id")
    return version_id if version_id not in ("", None) else None


def validate_bucket_param(bucket):
    serializer = BucketSerializer(data={"name": bucket})
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data["name"]


def get_required_key_param(request):
    return validate_object_key_value(request.query_params.get("key"))


def get_bounded_max_keys(request, default=100, minimum=1, maximum=1000):
    raw_max_keys = request.query_params.get("max_keys", default)
    try:
        max_keys = int(raw_max_keys)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(max_keys, maximum))


def forbidden(message="You do not have permission to perform this action."):
    return Response({"detail": message}, status=status.HTTP_403_FORBIDDEN)


def paginated_response(queryset, request, serializer_class):
    try:
        page = max(1, int(request.query_params.get("page", "1")))
    except ValueError:
        page = 1
    try:
        page_size = int(request.query_params.get("page_size", "25"))
    except ValueError:
        page_size = 25
    page_size = max(1, min(page_size, 100))
    count = queryset.count()
    total_pages = max(1, ceil(count / page_size)) if count else 1
    if page > total_pages:
        page = total_pages
    start = (page - 1) * page_size
    results = serializer_class(queryset[start:start + page_size], many=True).data
    return Response(
        {
            "results": results,
            "count": count,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
        }
    )


def get_role(user):
    if user.is_superuser:
        return "superuser"
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return profile.role


def is_admin(user):
    return user.is_superuser or get_role(user) == UserProfile.ROLE_ADMIN


def can_manage_user(actor, target):
    if actor.is_superuser:
        return target.id != actor.id
    if get_role(actor) != UserProfile.ROLE_ADMIN or target.id == actor.id:
        return False
    return not target.is_superuser and get_role(target) in (UserProfile.ROLE_EDITOR, UserProfile.ROLE_VIEWER)


def user_permissions(user):
    role = get_role(user)
    manage_users = user.is_superuser or role == UserProfile.ROLE_ADMIN
    return {
        "can_manage_users": manage_users,
        "can_manage_admins": user.is_superuser,
        "can_read_storage": True,
        "can_write_storage": user.is_superuser or role == UserProfile.ROLE_ADMIN,
        "role": role,
    }


def normalize_prefix(prefix):
    return str(prefix or "").strip().lstrip("/")


def prefix_matches_key(prefix, key):
    normalized_prefix = normalize_prefix(prefix)
    normalized_key = normalize_prefix(key)
    if not normalized_prefix:
        return True
    if normalized_prefix.endswith("/"):
        return normalized_key.startswith(normalized_prefix)
    return normalized_key == normalized_prefix or normalized_key.startswith(f"{normalized_prefix}/")


def grants_for_user(user, bucket=None):
    if is_admin(user):
        return VisibilityGrant.objects.none()
    role = get_role(user)
    query = Q(target_type=VisibilityGrant.TARGET_ROLE, role=role) | Q(
        target_type=VisibilityGrant.TARGET_USER,
        user=user,
    ) | Q(
        target_type=VisibilityGrant.TARGET_GROUP,
        group__users=user,
    )
    grants = VisibilityGrant.objects.filter(query)
    if bucket is not None:
        grants = grants.filter(bucket=bucket)
    return grants


def has_storage_access(user, bucket, key="", access=VisibilityGrant.ACCESS_READ):
    if is_admin(user):
        return True
    allowed_access = [access]
    if access == VisibilityGrant.ACCESS_READ:
        allowed_access.append(VisibilityGrant.ACCESS_WRITE)
    normalized_key = normalize_prefix(key)
    for grant in grants_for_user(user, bucket).filter(access__in=allowed_access):
        prefix = normalize_prefix(grant.prefix)
        if not normalized_key or prefix_matches_key(prefix, normalized_key):
            return True
    return False


def filter_objects_for_user(user, bucket, objects):
    if is_admin(user):
        return objects
    grants = list(
        grants_for_user(user, bucket).filter(
            access__in=[VisibilityGrant.ACCESS_READ, VisibilityGrant.ACCESS_WRITE]
        )
    )
    if not grants:
        return []
    allowed_prefixes = [normalize_prefix(grant.prefix) for grant in grants]
    if "" in allowed_prefixes:
        return objects
    return [
        item
        for item in objects
        if any(prefix_matches_key(prefix, item.get("key", "")) for prefix in allowed_prefixes)
    ]


def writable_prefixes_for_user(user, bucket):
    if is_admin(user):
        return [""]
    return [
        normalize_prefix(grant.prefix)
        for grant in grants_for_user(user, bucket).filter(access=VisibilityGrant.ACCESS_WRITE)
    ]


class RegisterView(generics.CreateAPIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = RegisterSerializer

    def create(self, request, *args, **kwargs):
        return Response(
            {"detail": "Public registration is disabled. Ask an administrator to create an account."},
            status=status.HTTP_403_FORBIDDEN,
        )


def set_auth_cookies(response, access_token, refresh_token=None):
    response.set_cookie(
        settings.JWT_ACCESS_COOKIE_NAME,
        access_token,
        httponly=True,
        secure=settings.JWT_COOKIE_SECURE,
        samesite=settings.JWT_COOKIE_SAMESITE,
    )
    if refresh_token:
        response.set_cookie(
            settings.JWT_REFRESH_COOKIE_NAME,
            refresh_token,
            httponly=True,
            secure=settings.JWT_COOKIE_SECURE,
            samesite=settings.JWT_COOKIE_SAMESITE,
        )


def clear_auth_cookies(response):
    response.delete_cookie(
        settings.JWT_ACCESS_COOKIE_NAME,
        samesite=settings.JWT_COOKIE_SAMESITE,
    )
    response.delete_cookie(
        settings.JWT_REFRESH_COOKIE_NAME,
        samesite=settings.JWT_COOKIE_SAMESITE,
    )


class CookieTokenObtainPairView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = TokenObtainPairSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as exc:
            raise InvalidToken(exc.args[0])

        response = Response({"detail": "Authenticated."})
        get_token(request)
        set_auth_cookies(response, serializer.validated_data["access"], serializer.validated_data["refresh"])
        return response


class CookieTokenRefreshView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        data = request.data.copy()
        if not data.get("refresh"):
            data["refresh"] = request.COOKIES.get(settings.JWT_REFRESH_COOKIE_NAME, "")
        serializer = TokenRefreshSerializer(data=data)
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as exc:
            raise InvalidToken(exc.args[0])

        response = Response({"detail": "Refreshed."})
        set_auth_cookies(response, serializer.validated_data["access"])
        return response


class CookieTokenLogoutView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        response = Response(status=status.HTTP_204_NO_CONTENT)
        refresh_token = request.COOKIES.get(settings.JWT_REFRESH_COOKIE_NAME)
        if refresh_token:
            try:
                RefreshToken(refresh_token).blacklist()
            except (AttributeError, TokenError):
                pass
        clear_auth_cookies(response)
        return response


class MeView(APIView):
    def get(self, request):
        user = request.user
        return Response(
            {
                "id": user.id,
                "username": user.get_username(),
                "role": get_role(user),
                "is_superuser": user.is_superuser,
                "permissions": user_permissions(user),
            }
        )


class UserAdminView(APIView):
    def get(self, request, user_id=None):
        if not is_admin(request.user):
            return forbidden()
        if user_id:
            try:
                user = get_user_model().objects.get(pk=user_id)
            except get_user_model().DoesNotExist:
                return Response({"detail": "User not found."}, status=404)
            if not request.user.is_superuser and (user.is_superuser or get_role(user) == UserProfile.ROLE_ADMIN):
                return forbidden("Admins cannot view admin or superuser accounts.")
            return Response(UserAdminSerializer(user).data)
        users = get_user_model().objects.select_related("profile").all().order_by("username")
        if not request.user.is_superuser:
            users = users.filter(is_superuser=False).exclude(profile__role=UserProfile.ROLE_ADMIN)
        query = request.query_params.get("q", "").strip()
        role = request.query_params.get("role", "").strip()
        is_active = request.query_params.get("is_active", "").strip().lower()
        if query:
            users = users.filter(Q(username__icontains=query) | Q(email__icontains=query))
        if role:
            if role == "superuser":
                users = users.filter(is_superuser=True)
            else:
                users = users.filter(is_superuser=False, profile__role=role)
        if is_active in ("true", "false"):
            users = users.filter(is_active=is_active == "true")
        return paginated_response(users, request, UserAdminSerializer)

    def post(self, request):
        if not is_admin(request.user):
            return forbidden()
        serializer = UserAdminSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        role = serializer.validated_data.get("role", UserProfile.ROLE_VIEWER)
        if not request.user.is_superuser and role == UserProfile.ROLE_ADMIN:
            return forbidden("Admins cannot create admin users.")
        user = serializer.save()
        return Response(UserAdminSerializer(user).data, status=status.HTTP_201_CREATED)

    def patch(self, request, user_id):
        if not is_admin(request.user):
            return forbidden()
        try:
            user = get_user_model().objects.get(pk=user_id)
        except get_user_model().DoesNotExist:
            return Response({"detail": "User not found."}, status=404)
        if not can_manage_user(request.user, user):
            return forbidden("You cannot modify this user.")
        requested_role = request.data.get("role")
        if not request.user.is_superuser and requested_role == UserProfile.ROLE_ADMIN:
            return forbidden("Admins cannot promote users to admin.")
        serializer = UserAdminSerializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        return Response(UserAdminSerializer(serializer.save()).data)

    def delete(self, request, user_id):
        if not is_admin(request.user):
            return forbidden()
        try:
            user = get_user_model().objects.get(pk=user_id)
        except get_user_model().DoesNotExist:
            return Response({"detail": "User not found."}, status=404)
        if not can_manage_user(request.user, user):
            return forbidden("You cannot deactivate this user.")
        user.is_active = False
        user.save(update_fields=["is_active"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class VisibilityGrantView(APIView):
    def get(self, request, grant_id=None):
        if not is_admin(request.user):
            return forbidden()
        if grant_id:
            try:
                grant = VisibilityGrant.objects.get(pk=grant_id)
            except VisibilityGrant.DoesNotExist:
                return Response({"detail": "Grant not found."}, status=404)
            return Response(VisibilityGrantSerializer(grant).data)
        grants = VisibilityGrant.objects.select_related("user", "group").all()
        query = request.query_params.get("q", "").strip()
        target_type = request.query_params.get("target_type", "").strip()
        bucket = request.query_params.get("bucket", "").strip()
        access = request.query_params.get("access", "").strip()
        if query:
            grants = grants.filter(
                Q(role__icontains=query)
                | Q(user__username__icontains=query)
                | Q(group__name__icontains=query)
                | Q(bucket__icontains=query)
                | Q(prefix__icontains=query)
            )
        if target_type:
            grants = grants.filter(target_type=target_type)
        if bucket:
            grants = grants.filter(bucket=bucket)
        if access:
            grants = grants.filter(access=access)
        return paginated_response(grants, request, VisibilityGrantSerializer)

    def post(self, request):
        if not is_admin(request.user):
            return forbidden()
        serializer = VisibilityGrantSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        grant = serializer.save()
        return Response(VisibilityGrantSerializer(grant).data, status=status.HTTP_201_CREATED)

    def patch(self, request, grant_id):
        if not is_admin(request.user):
            return forbidden()
        try:
            grant = VisibilityGrant.objects.get(pk=grant_id)
        except VisibilityGrant.DoesNotExist:
            return Response({"detail": "Grant not found."}, status=404)
        serializer = VisibilityGrantSerializer(grant, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        return Response(VisibilityGrantSerializer(serializer.save()).data)

    def delete(self, request, grant_id):
        if not is_admin(request.user):
            return forbidden()
        try:
            grant = VisibilityGrant.objects.get(pk=grant_id)
        except VisibilityGrant.DoesNotExist:
            return Response({"detail": "Grant not found."}, status=404)
        grant.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AccessGroupView(APIView):
    def get(self, request, group_id=None):
        if not is_admin(request.user):
            return forbidden()
        if group_id:
            try:
                group = AccessGroup.objects.get(pk=group_id)
            except AccessGroup.DoesNotExist:
                return Response({"detail": "Group not found."}, status=404)
            return Response(AccessGroupSerializer(group).data)
        groups = AccessGroup.objects.annotate(member_count=Count("users", distinct=True)).prefetch_related(
            Prefetch("users", queryset=get_user_model().objects.order_by("username"), to_attr="prefetched_users")
        ).order_by("name")
        query = request.query_params.get("q", "").strip()
        if query:
            groups = groups.filter(Q(name__icontains=query) | Q(users__username__icontains=query)).distinct()
        return paginated_response(groups, request, AccessGroupListSerializer)

    def post(self, request):
        if not is_admin(request.user):
            return forbidden()
        serializer = AccessGroupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        group = serializer.save()
        return Response(AccessGroupSerializer(group).data, status=status.HTTP_201_CREATED)

    def patch(self, request, group_id):
        if not is_admin(request.user):
            return forbidden()
        try:
            group = AccessGroup.objects.get(pk=group_id)
        except AccessGroup.DoesNotExist:
            return Response({"detail": "Group not found."}, status=404)
        serializer = AccessGroupSerializer(group, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        return Response(AccessGroupSerializer(serializer.save()).data)

    def delete(self, request, group_id):
        if not is_admin(request.user):
            return forbidden()
        try:
            group = AccessGroup.objects.get(pk=group_id)
        except AccessGroup.DoesNotExist:
            return Response({"detail": "Group not found."}, status=404)
        group.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class BucketListCreateView(APIView):
    def get(self, request):
        try:
            response = get_s3_client().list_buckets()
        except (ClientError, BotoCoreError) as exc:
            return error_response(exc)

        buckets = [
            {
                "name": bucket["Name"],
                "created_at": bucket["CreationDate"],
            }
            for bucket in response.get("Buckets", [])
            if has_storage_access(request.user, bucket["Name"])
        ]
        return Response({"buckets": buckets})

    def post(self, request):
        if not is_admin(request.user):
            return forbidden()
        serializer = BucketSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        bucket_name = serializer.validated_data["name"]
        group_id = serializer.validated_data.get("group_id")
        open_to_all = serializer.validated_data.get("open_to_all", True)

        try:
            get_s3_client().create_bucket(Bucket=bucket_name)
        except (ClientError, BotoCoreError) as exc:
            return error_response(exc)

        if group_id:
            VisibilityGrant.objects.get_or_create(
                target_type=VisibilityGrant.TARGET_GROUP,
                group_id=group_id,
                bucket=bucket_name,
                prefix="",
                access=VisibilityGrant.ACCESS_WRITE,
                defaults={"role": "", "user": None},
            )
        elif open_to_all:
            VisibilityGrant.objects.get_or_create(
                target_type=VisibilityGrant.TARGET_ROLE,
                role=UserProfile.ROLE_VIEWER,
                bucket=bucket_name,
                prefix="",
                access=VisibilityGrant.ACCESS_READ,
                defaults={"user": None},
            )
            VisibilityGrant.objects.get_or_create(
                target_type=VisibilityGrant.TARGET_ROLE,
                role=UserProfile.ROLE_EDITOR,
                bucket=bucket_name,
                prefix="",
                access=VisibilityGrant.ACCESS_WRITE,
                defaults={"user": None},
            )

        return Response({"name": bucket_name, "group_id": group_id, "open_to_all": open_to_all}, status=status.HTTP_201_CREATED)


class BucketDetailView(APIView):
    def delete(self, request, bucket):
        bucket = validate_bucket_param(bucket)
        if not is_admin(request.user):
            return forbidden()
        try:
            get_s3_client().delete_bucket(Bucket=bucket)
        except (ClientError, BotoCoreError) as exc:
            return error_response(exc)

        return Response(status=status.HTTP_204_NO_CONTENT)


class BucketRewindView(APIView):
    def get(self, request, bucket):
        bucket = validate_bucket_param(bucket)
        if not has_storage_access(request.user, bucket):
            return forbidden()
        rewind_to = request.query_params.get("rewind_to")
        if not rewind_to:
            return Response({"detail": "Query parameter 'rewind_to' is required."}, status=400)

        rewind_at = parse_datetime(rewind_to)
        if not rewind_at:
            return Response({"detail": "Query parameter 'rewind_to' must be a valid datetime."}, status=400)
        if is_naive(rewind_at):
            rewind_at = make_aware(rewind_at)

        try:
            response = get_s3_client().list_object_versions(Bucket=bucket)
        except (ClientError, BotoCoreError) as exc:
            return error_response(exc)

        candidates = []
        for item in response.get("Versions", []):
            candidates.append(
                {
                    "key": item.get("Key"),
                    "version_id": item.get("VersionId"),
                    "is_delete_marker": False,
                    "last_modified": item.get("LastModified"),
                    "size": item.get("Size", 0),
                    "etag": item.get("ETag"),
                    "content_type": "binary/octet-stream",
                    "metadata": {},
                }
            )
        for item in response.get("DeleteMarkers", []):
            candidates.append(
                {
                    "key": item.get("Key"),
                    "version_id": item.get("VersionId"),
                    "is_delete_marker": True,
                    "last_modified": item.get("LastModified"),
                    "size": 0,
                    "etag": "",
                    "content_type": "binary/octet-stream",
                    "metadata": {},
                }
            )

        latest_by_key = {}
        for item in sorted(
            candidates,
            key=lambda value: value.get("last_modified").timestamp() if value.get("last_modified") else 0,
            reverse=True,
        ):
            key = item.get("key")
            modified = item.get("last_modified")
            if not key or not modified or modified > rewind_at or key in latest_by_key:
                continue
            latest_by_key[key] = item

        objects = [
            item
            for item in latest_by_key.values()
            if not item.get("is_delete_marker")
        ]
        objects = filter_objects_for_user(request.user, bucket, objects)
        return Response(
            {
                "rewind_to": rewind_at,
                "objects": sorted(objects, key=lambda item: item["key"]),
                "writable_prefixes": writable_prefixes_for_user(request.user, bucket),
            }
        )


class ObjectView(APIView):
    def get(self, request, bucket, download=False):
        bucket = validate_bucket_param(bucket)
        if download:
            key = get_required_key_param(request)
            if not has_storage_access(request.user, bucket, key):
                return forbidden()
            params = {"Bucket": bucket, "Key": key}
            version_id = get_optional_version_id(request)
            if version_id:
                params["VersionId"] = version_id
            try:
                s3_object = get_s3_client().get_object(**params)
            except (ClientError, BotoCoreError) as exc:
                return error_response(exc, status.HTTP_404_NOT_FOUND)

            return FileResponse(
                s3_object["Body"],
                as_attachment=True,
                filename=key.split("/")[-1] or "download",
                content_type=s3_object.get("ContentType", "application/octet-stream"),
            )

        if not has_storage_access(request.user, bucket):
            return forbidden()
        list_params = {
            "Bucket": bucket,
            "MaxKeys": get_bounded_max_keys(request),
        }
        prefix = normalize_prefix(request.query_params.get("prefix", ""))
        continuation_token = request.query_params.get("continuation_token")
        if prefix:
            list_params["Prefix"] = prefix
        if continuation_token:
            list_params["ContinuationToken"] = continuation_token

        try:
            response = get_s3_client().list_objects_v2(**list_params)
        except (ClientError, BotoCoreError) as exc:
            return error_response(exc)

        s3_client = get_s3_client()
        objects = []
        for item in response.get("Contents", []):
            key = item["Key"]
            object_data = {
                "key": key,
                "size": item["Size"],
                "last_modified": item["LastModified"],
                "etag": item["ETag"],
                "content_type": "binary/octet-stream",
                "metadata": {},
            }
            try:
                head = s3_client.head_object(Bucket=bucket, Key=key)
            except (ClientError, BotoCoreError):
                head = {}
            object_data["content_type"] = head.get("ContentType") or object_data["content_type"]
            object_data["metadata"] = head.get("Metadata") or {}
            objects.append(object_data)
        objects = filter_objects_for_user(request.user, bucket, objects)
        return Response(
            {
                "objects": objects,
                "writable_prefixes": writable_prefixes_for_user(request.user, bucket),
                "next_continuation_token": response.get("NextContinuationToken") or "",
                "is_truncated": response.get("IsTruncated", False),
            }
        )

    def post(self, request, bucket):
        bucket = validate_bucket_param(bucket)
        serializer = ObjectUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        uploaded_file = serializer.validated_data["file"]
        key = serializer.validated_data.get("key") or uploaded_file.name
        if not has_storage_access(request.user, bucket, key, VisibilityGrant.ACCESS_WRITE):
            return forbidden()

        extra_args = {}
        if uploaded_file.content_type:
            extra_args["ContentType"] = uploaded_file.content_type

        try:
            if extra_args:
                get_s3_client().upload_fileobj(uploaded_file, bucket, key, ExtraArgs=extra_args)
            else:
                get_s3_client().upload_fileobj(uploaded_file, bucket, key)
        except (ClientError, BotoCoreError) as exc:
            return error_response(exc)

        return Response({"bucket": bucket, "key": key}, status=status.HTTP_201_CREATED)

    def delete(self, request, bucket):
        bucket = validate_bucket_param(bucket)
        key = get_required_key_param(request)
        if not has_storage_access(request.user, bucket, key, VisibilityGrant.ACCESS_WRITE):
            return forbidden()

        params = {"Bucket": bucket, "Key": key}
        version_id = get_optional_version_id(request)
        if version_id:
            params["VersionId"] = version_id
        try:
            get_s3_client().delete_object(**params)
        except (ClientError, BotoCoreError) as exc:
            return error_response(exc)

        return Response(status=status.HTTP_204_NO_CONTENT)


class ObjectShareView(APIView):
    def get(self, request, bucket):
        bucket = validate_bucket_param(bucket)
        key = get_required_key_param(request)
        if not has_storage_access(request.user, bucket, key):
            return forbidden()
        try:
            expires_in = int(request.query_params.get("expires_in", 12 * 60 * 60))
        except ValueError:
            return Response({"detail": "Query parameter 'expires_in' must be an integer."}, status=400)

        expires_in = max(60, min(expires_in, 7 * 24 * 60 * 60))
        params = {"Bucket": bucket, "Key": key}
        version_id = get_optional_version_id(request)
        if version_id:
            params["VersionId"] = version_id
        if request.query_params.get("preview") == "true":
            filename = key.split("/")[-1] or "preview"
            params.update(
                {
                    "ResponseContentDisposition": content_disposition_header(False, filename),
                    "ResponseContentType": guess_content_type(key),
                }
            )

        try:
            url = get_s3_client(endpoint_url=settings.MINIO_PUBLIC_ENDPOINT).generate_presigned_url(
                "get_object",
                Params=params,
                ExpiresIn=expires_in,
            )
        except (ClientError, BotoCoreError) as exc:
            return error_response(exc)

        return Response({"url": url, "expires_in": expires_in})


class ObjectTagsView(APIView):
    def get(self, request, bucket):
        bucket = validate_bucket_param(bucket)
        key = get_required_key_param(request)
        if not has_storage_access(request.user, bucket, key):
            return forbidden()

        try:
            response = get_s3_client().get_object_tagging(Bucket=bucket, Key=key)
        except (ClientError, BotoCoreError) as exc:
            return error_response(exc)

        tags = {item["Key"]: item["Value"] for item in response.get("TagSet", [])}
        return Response({"tags": tags})

    def put(self, request, bucket):
        bucket = validate_bucket_param(bucket)
        key = get_required_key_param(request)
        if not has_storage_access(request.user, bucket, key, VisibilityGrant.ACCESS_WRITE):
            return forbidden()

        tags = request.data.get("tags", {})
        if not isinstance(tags, dict):
            return Response({"detail": "'tags' must be an object."}, status=400)

        tag_set = [{"Key": str(name), "Value": str(value)} for name, value in tags.items()]
        try:
            get_s3_client().put_object_tagging(
                Bucket=bucket,
                Key=key,
                Tagging={"TagSet": tag_set},
            )
        except (ClientError, BotoCoreError) as exc:
            return error_response(exc)

        return Response({"tags": tags})


class ObjectVersionsView(APIView):
    def get(self, request, bucket):
        bucket = validate_bucket_param(bucket)
        key = get_required_key_param(request)
        if not has_storage_access(request.user, bucket, key):
            return forbidden()

        try:
            response = get_s3_client().list_object_versions(Bucket=bucket, Prefix=key)
        except (ClientError, BotoCoreError) as exc:
            return error_response(exc)

        versions = [
            {
                "version_id": item.get("VersionId"),
                "is_latest": item.get("IsLatest", False),
                "is_delete_marker": False,
                "last_modified": item.get("LastModified"),
                "size": item.get("Size", 0),
                "etag": item.get("ETag"),
            }
            for item in response.get("Versions", [])
            if item.get("Key") == key
        ]
        delete_markers = [
            {
                "version_id": item.get("VersionId"),
                "is_latest": item.get("IsLatest", False),
                "is_delete_marker": True,
                "last_modified": item.get("LastModified"),
                "size": 0,
                "etag": "",
            }
            for item in response.get("DeleteMarkers", [])
            if item.get("Key") == key
        ]
        all_versions = sorted(
            [*versions, *delete_markers],
            key=lambda item: item.get("last_modified").timestamp() if item.get("last_modified") else 0,
            reverse=True,
        )
        return Response({"versions": all_versions})
