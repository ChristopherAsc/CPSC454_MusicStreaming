import hashlib
import mimetypes
import re
from pathlib import Path

from django.http import FileResponse, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.html import escape
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import (
    require_GET,
    require_http_methods,
    require_POST,
)
from mutagen import File as MutagenFile

from .models import Track


ALLOWED_AUDIO_EXTENSIONS = {
    ".mp3",
    ".flac",
    ".wav",
    ".m4a",
    ".aac",
    ".ogg",
    ".opus",
}


def _first_tag(tags, *keys):
    for key in keys:
        value = tags.get(key)

        if not value:
            continue

        if isinstance(value, (list, tuple)):
            value = value[0]

        text = str(value).strip()

        if text:
            return text

    return ""


def _parse_number(value):
    if not value:
        return None

    try:
        return int(str(value).split("/", 1)[0].strip())
    except (TypeError, ValueError):
        return None


def _parse_year(value):
    if not value:
        return None

    match = re.search(
        r"\b(?:18|19|20|21)\d{2}\b",
        str(value),
    )

    return int(match.group(0)) if match else None


def _calculate_sha256(uploaded_file):
    digest = hashlib.sha256()

    for chunk in uploaded_file.chunks():
        digest.update(chunk)

    uploaded_file.seek(0)

    return digest.hexdigest()


def _extract_metadata(fileobj, filename):
    stem = Path(filename).stem
    audio = MutagenFile(fileobj, easy=True)

    if audio is None:
        return {"title": stem}

    tags = audio.tags or {}
    info = audio.info

    genre_values = tags.get("genre") or []

    if isinstance(genre_values, str):
        genre_values = [genre_values]

    genre = ", ".join(
        dict.fromkeys(
            str(value).strip()
            for value in genre_values
            if str(value).strip()
        )
    )

    bitrate = getattr(info, "bitrate", None)

    return {
        "title": _first_tag(tags, "title") or stem,
        "artist": _first_tag(tags, "artist"),
        "album": _first_tag(tags, "album"),
        "album_artist": _first_tag(
            tags,
            "albumartist",
            "album artist",
        ),
        "genre": genre,
        "year": _parse_year(
            _first_tag(tags, "date", "originaldate")
        ),
        "track_number": _parse_number(
            _first_tag(tags, "tracknumber")
        ),
        "duration_seconds": getattr(
            info,
            "length",
            None,
        ),
        "bitrate_kbps": (
            round(bitrate / 1000)
            if bitrate
            else None
        ),
    }


def _create_track(uploaded_file):
    extension = Path(uploaded_file.name).suffix.lower()

    if extension not in ALLOWED_AUDIO_EXTENSIONS:
        raise ValueError(
            "Unsupported audio extension: "
            f"{extension or 'missing extension'}"
        )

    file_hash = _calculate_sha256(uploaded_file)

    existing = Track.objects.filter(
        sha256=file_hash,
    ).first()

    if existing:
        return existing, False, None

    mime_type = (
        getattr(uploaded_file, "content_type", "")
        or mimetypes.guess_type(uploaded_file.name)[0]
        or "audio/mpeg"
    )

    track = Track(
        file=uploaded_file,
        original_filename=uploaded_file.name,
        title=Path(uploaded_file.name).stem,
        file_size=uploaded_file.size,
        mime_type=mime_type,
        sha256=file_hash,
    )

    # The file must be saved before Mutagen can inspect it.
    track.save()

    metadata_warning = None

    try:
        with track.file.open("rb") as fileobj:
            metadata = _extract_metadata(
                fileobj,
                track.original_filename,
            )

        valid_fields = {
            field.name
            for field in Track._meta.fields
        }

        for field_name, value in metadata.items():
            if (
                field_name in valid_fields
                and value not in (None, "")
            ):
                setattr(track, field_name, value)

        track.save()

    except Exception as exc:
        metadata_warning = str(exc)

    return track, True, metadata_warning


def _serialize_track(request, track):
    uploaded_at = getattr(track, "uploaded_at", None)

    return {
        "id": track.id,
        "title": (
            track.title
            or track.original_filename
        ),
        "artist": (
            track.artist
            or "Unknown artist"
        ),
        "album": track.album,
        "album_artist": track.album_artist,
        "genre": track.genre,
        "year": track.year,
        "track_number": track.track_number,
        "duration_seconds": track.duration_seconds,
        "bitrate_kbps": track.bitrate_kbps,
        "file_size": track.file_size,
        "file": track.file.name,
        "stream_url": request.build_absolute_uri(
            f"/tracks/{track.id}/stream/"
        ),
        "download_url": request.build_absolute_uri(
            f"/tracks/{track.id}/download/"
        ),
        "uploaded_at": (
            uploaded_at.isoformat()
            if uploaded_at
            else None
        ),
    }


@require_GET
def home(request):
    tracks = Track.objects.order_by("-id")

    sections = []

    for track in tracks:
        title = escape(
            track.title or track.original_filename
        )
        artist = escape(
            track.artist or "Unknown artist"
        )
        album = escape(
            track.album or "Unknown album"
        )
        genre = escape(
            track.genre or "Unknown genre"
        )
        year = escape(
            str(track.year)
            if track.year
            else "Unknown"
        )
        mime_type = escape(
            track.mime_type or "audio/mpeg"
        )

        sections.append(
            f"""
            <article style="
                border: 1px solid #cccccc;
                margin: 16px 0;
                padding: 16px;
            ">
                <h2>{title}</h2>

                <p>
                    <strong>Artist:</strong> {artist}<br>
                    <strong>Album:</strong> {album}<br>
                    <strong>Genre:</strong> {genre}<br>
                    <strong>Year:</strong> {year}
                </p>

                <audio controls preload="metadata">
                    <source
                        src="/tracks/{track.id}/stream/"
                        type="{mime_type}"
                    >
                </audio>

                <p>
                    <a href="/tracks/{track.id}/download/">
                        Download
                    </a>
                </p>
            </article>
            """
        )

    library = (
        "\n".join(sections)
        if sections
        else "<p>No music has been uploaded yet.</p>"
    )

    return HttpResponse(
        f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta
                name="viewport"
                content="width=device-width, initial-scale=1"
            >
            <title>Better Titan Radio</title>
        </head>

        <body style="
            max-width: 900px;
            margin: 40px auto;
            padding: 0 20px;
            font-family: Arial, sans-serif;
        ">
            <h1>Better Titan Radio</h1>

            <p>
                <a href="/upload/">Upload music</a>
                |
                <a href="/api/tracks/">View JSON API</a>
                |
                <a href="/test/">Test server</a>
            </p>

            {library}
        </body>
        </html>
        """
    )


@require_GET
def test(request):
    return JsonResponse(
        {
            "status": "ok",
            "message": "Better Titan Radio is running.",
        }
    )


@csrf_exempt
@require_http_methods(["GET", "POST"])
def upload_page(request):
    if request.method == "GET":
        return HttpResponse(
            """
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta
                    name="viewport"
                    content="width=device-width, initial-scale=1"
                >
                <title>Upload Music</title>
            </head>

            <body style="
                max-width: 700px;
                margin: 40px auto;
                padding: 0 20px;
                font-family: Arial, sans-serif;
            ">
                <h1>Upload Music</h1>

                <form
                    method="post"
                    enctype="multipart/form-data"
                >
                    <p>
                        <input
                            type="file"
                            name="file"
                            accept="audio/*"
                            required
                        >
                    </p>

                    <button type="submit">
                        Upload
                    </button>
                </form>

                <p>
                    <a href="/">Back to library</a>
                </p>
            </body>
            </html>
            """
        )

    uploaded_file = request.FILES.get("file")

    if uploaded_file is None:
        return HttpResponse(
            "No file was supplied.",
            status=400,
        )

    try:
        track, created, warning = _create_track(
            uploaded_file
        )
    except ValueError as exc:
        return HttpResponse(
            escape(str(exc)),
            status=400,
        )

    message = (
        "Music uploaded successfully."
        if created
        else "That exact file was already uploaded."
    )

    warning_html = ""

    if warning:
        warning_html = (
            "<p><strong>Metadata warning:</strong> "
            f"{escape(warning)}</p>"
        )

    return HttpResponse(
        f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <title>Upload Result</title>
        </head>

        <body style="
            max-width: 700px;
            margin: 40px auto;
            padding: 0 20px;
            font-family: Arial, sans-serif;
        ">
            <h1>{escape(message)}</h1>

            <p>
                <strong>Title:</strong>
                {escape(track.title or track.original_filename)}
                <br>

                <strong>Artist:</strong>
                {escape(track.artist or "Unknown artist")}
                <br>

                <strong>Album:</strong>
                {escape(track.album or "Unknown album")}
                <br>

                <strong>Genre:</strong>
                {escape(track.genre or "Unknown genre")}
            </p>

            {warning_html}

            <p>
                <a href="/">View library</a>
                |
                <a href="/upload/">Upload another</a>
            </p>
        </body>
        </html>
        """
    )


@require_GET
def api_tracks(request):
    tracks = Track.objects.order_by("-id")

    return JsonResponse(
        {
            "count": tracks.count(),
            "tracks": [
                _serialize_track(request, track)
                for track in tracks
            ],
        }
    )


@csrf_exempt
@require_POST
def api_upload(request):
    uploaded_file = request.FILES.get("file")

    if uploaded_file is None:
        return JsonResponse(
            {
                "error": (
                    "Upload a file using the multipart "
                    "form field named 'file'."
                )
            },
            status=400,
        )

    try:
        track, created, warning = _create_track(
            uploaded_file
        )
    except ValueError as exc:
        return JsonResponse(
            {"error": str(exc)},
            status=400,
        )

    response = {
        "created": created,
        "message": (
            "Music uploaded successfully."
            if created
            else "That exact file already exists."
        ),
        "track": _serialize_track(request, track),
    }

    if warning:
        response["metadata_warning"] = warning

    return JsonResponse(
        response,
        status=201 if created else 200,
    )


@require_GET
def stream_track(request, track_id):
    track = get_object_or_404(Track, pk=track_id)

    response = FileResponse(
        track.file.open("rb"),
        content_type=(
            track.mime_type
            or "audio/mpeg"
        ),
    )

    response["Content-Disposition"] = (
        f'inline; filename="{track.original_filename}"'
    )

    return response


@require_GET
def download_track(request, track_id):
    track = get_object_or_404(Track, pk=track_id)

    return FileResponse(
        track.file.open("rb"),
        as_attachment=True,
        filename=track.original_filename,
        content_type=(
            track.mime_type
            or "audio/mpeg"
        ),
    )

