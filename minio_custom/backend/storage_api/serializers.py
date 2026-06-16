import re

from django.contrib.auth import get_user_model
from rest_framework import serializers

from storage_api.models import AccessGroup, UserProfile, VisibilityGrant


CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")


def validate_object_key_value(value):
    key = str(value or "")
    if not key:
        raise serializers.ValidationError("Object key is required.")
    if len(key) > 1024:
        raise serializers.ValidationError("Object key must be 1024 characters or fewer.")
    if CONTROL_CHAR_RE.search(key):
        raise serializers.ValidationError("Object key cannot contain control characters.")
    return key


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = get_user_model()
        fields = ("id", "username", "email", "password")
        read_only_fields = ("id",)

    def create(self, validated_data):
        password = validated_data.pop("password")
        return get_user_model().objects.create_user(password=password, **validated_data)


class UserAdminSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, min_length=8, allow_blank=True)
    role = serializers.ChoiceField(choices=UserProfile.ROLE_CHOICES, required=False)

    class Meta:
        model = get_user_model()
        fields = ("id", "username", "password", "role", "is_active", "is_superuser")
        read_only_fields = ("id", "is_superuser")

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.is_superuser:
            data["role"] = "superuser"
        else:
            profile, _ = UserProfile.objects.get_or_create(user=instance)
            data["role"] = profile.role
        return data

    def create(self, validated_data):
        password = validated_data.pop("password", "")
        if not password:
            raise serializers.ValidationError({"password": "Password is required."})
        role = validated_data.pop("role", UserProfile.ROLE_VIEWER)
        user = get_user_model().objects.create_user(password=password, **validated_data)
        UserProfile.objects.update_or_create(user=user, defaults={"role": role})
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", "")
        role = validated_data.pop("role", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        if password:
            instance.set_password(password)
        instance.save()
        if role and not instance.is_superuser:
            UserProfile.objects.update_or_create(user=instance, defaults={"role": role})
        return instance


class VisibilityGrantSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)
    group_name = serializers.CharField(source="group.name", read_only=True)

    class Meta:
        model = VisibilityGrant
        fields = (
            "id",
            "target_type",
            "role",
            "user",
            "username",
            "group",
            "group_name",
            "bucket",
            "prefix",
            "access",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "username", "group_name", "created_at", "updated_at")

    def validate(self, attrs):
        target_type = attrs.get("target_type", getattr(self.instance, "target_type", None))
        role = attrs.get("role", getattr(self.instance, "role", ""))
        user = attrs.get("user", getattr(self.instance, "user", None))
        group = attrs.get("group", getattr(self.instance, "group", None))
        prefix = attrs.get("prefix", getattr(self.instance, "prefix", ""))

        if target_type == VisibilityGrant.TARGET_ROLE:
            if not role:
                raise serializers.ValidationError({"role": "Role target requires a role."})
            attrs["user"] = None
            attrs["group"] = None
        elif target_type == VisibilityGrant.TARGET_USER:
            if not user:
                raise serializers.ValidationError({"user": "User target requires a user."})
            attrs["role"] = ""
            attrs["group"] = None
        elif target_type == VisibilityGrant.TARGET_GROUP:
            if not group:
                raise serializers.ValidationError({"group": "Group target requires a group."})
            attrs["role"] = ""
            attrs["user"] = None
        else:
            raise serializers.ValidationError({"target_type": "Invalid target type."})

        if prefix:
            attrs["prefix"] = str(prefix).strip().lstrip("/")
        return attrs


class AccessGroupSerializer(serializers.ModelSerializer):
    users = serializers.PrimaryKeyRelatedField(
        many=True,
        queryset=get_user_model().objects.all(),
        required=False,
    )
    user_details = UserAdminSerializer(source="users", many=True, read_only=True)

    class Meta:
        model = AccessGroup
        fields = ("id", "name", "users", "user_details", "created_at", "updated_at")
        read_only_fields = ("id", "user_details", "created_at", "updated_at")

    def validate_name(self, value):
        return value.strip()

    def create(self, validated_data):
        users = validated_data.pop("users", [])
        group = AccessGroup.objects.create(**validated_data)
        group.users.set(users)
        return group

    def update(self, instance, validated_data):
        users = validated_data.pop("users", None)
        instance.name = validated_data.get("name", instance.name)
        instance.save()
        if users is not None:
            instance.users.set(users)
        return instance


class AccessGroupListSerializer(serializers.ModelSerializer):
    member_count = serializers.IntegerField(read_only=True)
    member_preview = serializers.SerializerMethodField()

    class Meta:
        model = AccessGroup
        fields = ("id", "name", "member_count", "member_preview", "created_at", "updated_at")

    def get_member_preview(self, instance):
        users = getattr(instance, "prefetched_users", None)
        if users is None:
            users = list(instance.users.order_by("username")[:3])
        else:
            users = users[:3]
        return [{"id": user.id, "username": user.username} for user in users]


class BucketSerializer(serializers.Serializer):
    name = serializers.RegexField(
        regex=r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$",
        max_length=63,
        min_length=3,
    )
    group_id = serializers.IntegerField(required=False, allow_null=True)
    open_to_all = serializers.BooleanField(required=False, default=True)

    def validate_group_id(self, value):
        if value in ("", None):
            return None
        if not AccessGroup.objects.filter(pk=value).exists():
            raise serializers.ValidationError("Group does not exist.")
        return value


class ObjectUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    key = serializers.CharField(required=False, allow_blank=True, max_length=1024)

    def validate(self, attrs):
        uploaded_file = attrs.get("file")
        attrs["key"] = validate_object_key_value(attrs.get("key") or getattr(uploaded_file, "name", ""))
        return attrs
