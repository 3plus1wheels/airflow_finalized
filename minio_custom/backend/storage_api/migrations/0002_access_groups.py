from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("storage_api", "0001_roles_visibility"),
    ]

    operations = [
        migrations.CreateModel(
            name="AccessGroup",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=80, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "users",
                    models.ManyToManyField(blank=True, related_name="access_groups", to=settings.AUTH_USER_MODEL),
                ),
            ],
            options={
                "ordering": ["name"],
            },
        ),
        migrations.RemoveConstraint(
            model_name="visibilitygrant",
            name="visibility_grant_valid_target",
        ),
        migrations.AlterModelOptions(
            name="visibilitygrant",
            options={"ordering": ["bucket", "prefix", "target_type", "role", "user_id", "group_id"]},
        ),
        migrations.AlterField(
            model_name="visibilitygrant",
            name="target_type",
            field=models.CharField(choices=[("role", "Role"), ("user", "User"), ("group", "Group")], max_length=8),
        ),
        migrations.AddField(
            model_name="visibilitygrant",
            name="group",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="visibility_grants",
                to="storage_api.accessgroup",
            ),
        ),
        migrations.AddConstraint(
            model_name="visibilitygrant",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(
                        ("group__isnull", True),
                        ("role__in", ["admin", "editor", "viewer"]),
                        ("target_type", "role"),
                        ("user__isnull", True),
                    )
                    | models.Q(("group__isnull", True), ("role", ""), ("target_type", "user"), ("user__isnull", False))
                    | models.Q(("group__isnull", False), ("role", ""), ("target_type", "group"), ("user__isnull", True))
                ),
                name="visibility_grant_valid_target",
            ),
        ),
        migrations.AddConstraint(
            model_name="visibilitygrant",
            constraint=models.UniqueConstraint(
                condition=models.Q(("target_type", "group")),
                fields=("target_type", "group", "bucket", "prefix", "access"),
                name="unique_group_visibility_grant",
            ),
        ),
    ]
