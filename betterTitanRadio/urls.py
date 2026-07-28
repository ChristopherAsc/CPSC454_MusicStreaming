from django.urls import path

from . import views


app_name = "betterTitanRadio"


urlpatterns = [
    path("", views.home, name="home"),
    path("test/", views.test, name="test"),
    path("upload/", views.upload_page, name="upload"),

    path(
        "api/tracks/",
        views.api_tracks,
        name="api_tracks",
    ),
    path(
        "api/tracks/upload/",
        views.api_upload,
        name="api_upload",
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

