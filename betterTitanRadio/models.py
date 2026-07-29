from django.db import models

# Create your models here.
# models are like the database schema
from django.db import models


class Track(models.Model):
    file = models.FileField(upload_to="tracks/%Y/%m/")
    original_filename = models.CharField(max_length=255)

    title = models.CharField(max_length=255, blank=True)
    artist = models.CharField(max_length=255, blank=True)
    album = models.CharField(max_length=255, blank=True)
    album_artist = models.CharField(max_length=255, blank=True)
    genre = models.CharField(max_length=255, blank=True)

    year = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
    )

    track_number = models.PositiveIntegerField(
        null=True,
        blank=True,
    )

    duration_seconds = models.FloatField(
        null=True,
        blank=True,
    )

    bitrate_kbps = models.PositiveIntegerField(
        null=True,
        blank=True,
    )

    mime_type = models.CharField(
        max_length=100,
        blank=True,
    )

    file_size = models.PositiveBigIntegerField(default=0)

    sha256 = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
    )

    uploaded_at = models.DateTimeField(auto_now_add=True)

    @property
    def display_title(self):
        return self.title or self.original_filename

    @property
    def display_artist(self):
        return self.artist or "Unknown artist"

    def __str__(self):
        return f"{self.display_artist} - {self.display_title}"
