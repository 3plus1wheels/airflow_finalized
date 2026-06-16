from django.conf import settings
from django.db import models
from django.db.models import Q


class UserProfile(models.Model):
    ROLE_ADMIN = "admin"
    ROLE_EDITOR = "editor"
    ROLE_VIEWER = "viewer"
    ROLE_CHOICES = (
        (ROLE_ADMIN, "Admin"),
        (ROLE_EDITOR, "Editor"),
        (ROLE_VIEWER, "Viewer"),
    )

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=16, choices=ROLE_CHOICES, default=ROLE_VIEWER)

    class Meta:
        indexes = [
            models.Index(fields=["role"], name="userprofile_role_idx"),
        ]

    def __str__(self):
        return f"{self.user} ({self.role})"


class AccessGroup(models.Model):
    name = models.CharField(max_length=80, unique=True)
    users = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name="access_groups")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class VisibilityGrant(models.Model):
    TARGET_ROLE = "role"
    TARGET_USER = "user"
    TARGET_GROUP = "group"
    TARGET_CHOICES = (
        (TARGET_ROLE, "Role"),
        (TARGET_USER, "User"),
        (TARGET_GROUP, "Group"),
    )

    ACCESS_READ = "read"
    ACCESS_WRITE = "write"
    ACCESS_CHOICES = (
        (ACCESS_READ, "Read"),
        (ACCESS_WRITE, "Write"),
    )

    target_type = models.CharField(max_length=8, choices=TARGET_CHOICES)
    role = models.CharField(max_length=16, choices=UserProfile.ROLE_CHOICES, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="visibility_grants",
    )
    group = models.ForeignKey(
        AccessGroup,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="visibility_grants",
    )
    bucket = models.CharField(max_length=63)
    prefix = models.CharField(max_length=1024, blank=True, default="")
    access = models.CharField(max_length=8, choices=ACCESS_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["bucket", "prefix", "target_type", "role", "user_id", "group_id"]
        indexes = [
            models.Index(
                fields=["bucket", "prefix", "target_type", "role", "user", "group"],
                name="grant_admin_order_idx",
            ),
            models.Index(fields=["bucket", "access", "prefix"], name="grant_bucket_access_idx"),
            models.Index(fields=["target_type", "access", "bucket"], name="grant_target_access_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                check=(
                    Q(target_type="role", role__in=["admin", "editor", "viewer"], user__isnull=True, group__isnull=True)
                    | Q(target_type="user", role="", user__isnull=False, group__isnull=True)
                    | Q(target_type="group", role="", user__isnull=True, group__isnull=False)
                ),
                name="visibility_grant_valid_target",
            ),
            models.UniqueConstraint(
                fields=["target_type", "role", "bucket", "prefix", "access"],
                condition=Q(target_type="role"),
                name="unique_role_visibility_grant",
            ),
            models.UniqueConstraint(
                fields=["target_type", "user", "bucket", "prefix", "access"],
                condition=Q(target_type="user"),
                name="unique_user_visibility_grant",
            ),
            models.UniqueConstraint(
                fields=["target_type", "group", "bucket", "prefix", "access"],
                condition=Q(target_type="group"),
                name="unique_group_visibility_grant",
            ),
        ]

    def __str__(self):
        if self.target_type == self.TARGET_ROLE:
            target = self.role
        elif self.target_type == self.TARGET_GROUP:
            target = self.group_id
        else:
            target = self.user_id
        return f"{self.target_type}:{target} {self.access} {self.bucket}/{self.prefix}"
