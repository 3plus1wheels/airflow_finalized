from django.urls import path

from storage_api.views import (
    BucketDetailView,
    BucketListCreateView,
    BucketRewindView,
    AccessGroupView,
    MeView,
    ObjectShareView,
    ObjectTagsView,
    ObjectVersionsView,
    ObjectView,
    UserAdminView,
    VisibilityGrantView,
)


urlpatterns = [
    path("me/", MeView.as_view(), name="me"),
    path("users/", UserAdminView.as_view(), name="user-list-create"),
    path("users/<int:user_id>/", UserAdminView.as_view(), name="user-detail"),
    path("groups/", AccessGroupView.as_view(), name="group-list-create"),
    path("groups/<int:group_id>/", AccessGroupView.as_view(), name="group-detail"),
    path("visibility-grants/", VisibilityGrantView.as_view(), name="visibility-grant-list-create"),
    path("visibility-grants/<int:grant_id>/", VisibilityGrantView.as_view(), name="visibility-grant-detail"),
    path("buckets/", BucketListCreateView.as_view(), name="bucket-list-create"),
    path("buckets/<str:bucket>/", BucketDetailView.as_view(), name="bucket-detail"),
    path("buckets/<str:bucket>/rewind/", BucketRewindView.as_view(), name="bucket-rewind"),
    path("buckets/<str:bucket>/objects/", ObjectView.as_view(), name="object-list-create-delete"),
    path(
        "buckets/<str:bucket>/objects/download/",
        ObjectView.as_view(),
        {"download": True},
        name="object-download",
    ),
    path("buckets/<str:bucket>/objects/share/", ObjectShareView.as_view(), name="object-share"),
    path("buckets/<str:bucket>/objects/tags/", ObjectTagsView.as_view(), name="object-tags"),
    path("buckets/<str:bucket>/objects/versions/", ObjectVersionsView.as_view(), name="object-versions"),
]
