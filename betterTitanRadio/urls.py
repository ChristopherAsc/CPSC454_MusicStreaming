from django.urls import path

from . import views


urlpatterns = [
    path("", views.home, name="home"),
    path("test/", views.test, name="test"),
    path("upload/", views.upload_page, name="upload"),
    path("settings/", views.settings_page, name="settings"),

    path(
        "api/library/clear/",
        views.api_clear_library,
        name="api_clear_library",
    ),

    path(
        "api/tracks/",
        views.api_tracks,
        name="api_tracks",
    ),
    path(
        "api/search/",
        views.api_search,
        name="api_search",
    ),
    path(
        "api/tracks/upload/",
        views.api_upload,
        name="api_upload",
    ),
    path(
        "api/tracks/upload-folder/",
        views.api_upload_folder,
        name="api_upload_folder",
    ),

    path(
        "tracks/<int:track_id>/stream/",
        views.stream_track,
        name="stream_track",
    ),
    path(
        "tracks/<int:track_id>/download/",
        views.download_track,
        name="download_track",
    ),
]
