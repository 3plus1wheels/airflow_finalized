from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.db.models.expressions


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="UserProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "role",
                    models.CharField(
                        choices=[("admin", "Admin"), ("editor", "Editor"), ("viewer", "Viewer")],
                        default="viewer",
                        max_length=16,
                    ),
                ),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="profile",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="VisibilityGrant",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "target_type",
                    models.CharField(choices=[("role", "Role"), ("user", "User")], max_length=8),
                ),
                (
                    "role",
                    models.CharField(
                        blank=True,
                        choices=[("admin", "Admin"), ("editor", "Editor"), ("viewer", "Viewer")],
                        max_length=16,
                    ),
                ),
                ("bucket", models.CharField(max_length=63)),
                ("prefix", models.CharField(blank=True, default="", max_length=1024)),
                ("access", models.CharField(choices=[("read", "Read"), ("write", "Write")], max_length=8)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="visibility_grants",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["bucket", "prefix", "target_type", "role", "user_id"],
            },
        ),
        migrations.AddConstraint(
            model_name="visibilitygrant",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(("role__in", ["admin", "editor", "viewer"]), ("target_type", "role"), ("user__isnull", True))
                    | models.Q(("role", ""), ("target_type", "user"), ("user__isnull", False))
                ),
                name="visibility_grant_valid_target",
            ),
        ),
        migrations.AddConstraint(
            model_name="visibilitygrant",
            constraint=models.UniqueConstraint(
                condition=models.Q(("target_type", "role")),
                fields=("target_type", "role", "bucket", "prefix", "access"),
                name="unique_role_visibility_grant",
            ),
        ),
        migrations.AddConstraint(
            model_name="visibilitygrant",
            constraint=models.UniqueConstraint(
                condition=models.Q(("target_type", "user")),
                fields=("target_type", "user", "bucket", "prefix", "access"),
                name="unique_user_visibility_grant",
            ),
        ),
    ]
