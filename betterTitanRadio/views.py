import hashlib
import mimetypes
import re
from pathlib import Path
from django.db.models import Q

from django.http import FileResponse, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, render
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


def _read_file_range(fileobj, start, length, chunk_size=8192):
    fileobj.seek(start)
    remaining = length

    try:
        while remaining > 0:
            chunk = fileobj.read(min(chunk_size, remaining))

            if not chunk:
                break

            remaining -= len(chunk)
            yield chunk
    finally:
        fileobj.close()


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
        # The PCM stream server addresses tracks by content hash, not by id or
        # name, so the client needs the digest to ask for anything.
        "sha256": track.sha256,
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


def _format_duration(seconds):
    if seconds is None:
        return "--:--"

    total_seconds = round(seconds)
    minutes, remaining_seconds = divmod(total_seconds, 60)

    return f"{minutes}:{remaining_seconds:02d}"


def _format_file_size(size):
    if not size:
        return "0 MB"

    return f"{size / (1024 * 1024):.1f} MB"


def _track_format(track):
    extension = Path(track.original_filename).suffix

    return extension.lstrip(".").upper() or "Audio"


def _dashboard_track(request, track, index):
    accents = [
        "#ef476f",
        "#06d6a0",
        "#ffd166",
        "#118ab2",
        "#9b5de5",
    ]

    return {
        "id": track.id,
        "sha256": track.sha256,
        "title": track.display_title,
        "artist": track.display_artist,
        "album": track.album or "Unknown album",
        "source": track.file.name,
        "format": _track_format(track),
        "size": _format_file_size(track.file_size),
        "duration": _format_duration(track.duration_seconds),
        "status": "Ready",
        "accent": accents[index % len(accents)],
        "mime_type": track.mime_type or "audio/mpeg",
        "stream_url": f"/tracks/{track.id}/stream/",
        "download_url": f"/tracks/{track.id}/download/",
    }

@require_GET
def api_search(request):
    query = request.GET.get("q", "").strip()
    if not query:
        return JsonResponse({"results": []})

    tracks = Track.objects.filter(
        Q(title__icontains=query) | Q(artist__icontains=query) | Q(album__icontains=query)
    ).order_by("-id")[:10]

    results = [
        {
            "id": t.id,
            "sha256": t.sha256,
            "title": t.display_title,
            "artist": t.display_artist,
            "stream_url": f"/tracks/{t.id}/stream/",
        }
        for t in tracks
    ]
    return JsonResponse({"results": results})

@require_GET
def home(request):
    queryset = Track.objects.order_by("-id")
    tracks = [
        _dashboard_track(request, track, index)
        for index, track in enumerate(queryset)
    ]
    total_size = sum(track.file_size for track in queryset)

    metrics = [
        {
            "label": "Stream latency",
            "value": "Local",
            "trend": "Served by Django stream endpoint",
        },
        {
            "label": "Library size",
            "value": f"{len(tracks)} tracks",
            "trend": _format_file_size(total_size),
        },
        {
            "label": "Upload support",
            "value": "Ready",
            "trend": "Audio files saved with metadata",
        },
        {
            "label": "Server status",
            "value": "Online",
            "trend": "SQLite fallback for local dev",
        },
    ]

    upload_queue = [
        {"name": "Upload form", "state": "Available"},
        {"name": "JSON API", "state": "Available"},
        {"name": "Stream/download", "state": "Available"},
    ]

    return render(
        request,
        "home.html",
        {
            "tracks": tracks,
            "metrics": metrics,
            "upload_queue": upload_queue,
        },
    )


@require_GET
def settings_page(request):
    queryset = Track.objects.order_by("-id")

    return render(
        request,
        "settings.html",
        {
            "track_count": queryset.count(),
            "library_size": _format_file_size(
                sum(track.file_size for track in queryset)
            ),
        },
    )


@require_POST
def api_clear_library(request):
    """Delete every track, and the audio files behind them.

    Deliberately NOT csrf_exempt, unlike the upload endpoints: this destroys the
    whole library, so it must be reachable only from a form this site rendered.

    Files are removed one at a time rather than with a bulk queryset delete,
    because a bulk delete drops the rows without touching storage and would
    leave every audio file orphaned on disk.
    """
    tracks = list(Track.objects.all())
    file_errors = []

    for track in tracks:
        try:
            track.file.delete(save=False)
        except Exception as exc:
            # Losing a file is not a reason to keep its row; record and continue.
            file_errors.append(f"{track.original_filename}: {exc}")

        track.delete()

    response = {
        "deleted": len(tracks),
        "message": (
            f"Cleared {len(tracks)} track{'' if len(tracks) == 1 else 's'} "
            "from the library."
            if tracks
            else "The library was already empty."
        ),
    }

    if file_errors:
        response["file_errors"] = file_errors

    return JsonResponse(response)


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
def api_search(request):
    query = request.GET.get("q", "").strip()

    if not query:
        return JsonResponse({"results": []})

    tracks = Track.objects.filter(
        Q(title__icontains=query)
        | Q(artist__icontains=query)
        | Q(album__icontains=query)
    ).order_by("-id")[:10]

    results = [
        {
            "id": track.id,
            "sha256": track.sha256,
            "title": track.display_title,
            "artist": track.display_artist,
            "stream_url": f"/tracks/{track.id}/stream/",
        }
        for track in tracks
    ]

    return JsonResponse({"results": results})


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


@csrf_exempt
@require_POST
def api_upload_folder(request):
    """Ingest many files at once -- everything playable in an uploaded folder.

    A real music folder is not all music: it holds cover art, playlists and
    stray dotfiles too. Those are *skipped* rather than treated as failures, so
    one `folder.jpg` never makes an otherwise clean upload look broken.

    Accepts any number of files under the `files` field, so a whole folder can
    be posted in one request:

        curl -F "files=@a.mp3" -F "files=@b.flac" .../api/tracks/upload-folder/

    The dashboard instead posts one file per request, which bounds memory and
    lets it report progress; both use this endpoint.
    """
    uploads = request.FILES.getlist("files")

    if not uploads:
        return JsonResponse(
            {
                "error": (
                    "Upload one or more files using the multipart "
                    "form field named 'files'."
                )
            },
            status=400,
        )

    results = []
    counts = {"created": 0, "duplicate": 0, "skipped": 0, "failed": 0}

    for uploaded_file in uploads:
        # Multipart carries only the basename, never the folder structure, so
        # duplicates are caught by content hash rather than by path.
        name = uploaded_file.name
        extension = Path(name).suffix.lower()

        if extension not in ALLOWED_AUDIO_EXTENSIONS:
            counts["skipped"] += 1
            results.append(
                {
                    "name": name,
                    "status": "skipped",
                    "reason": (
                        f"{extension or 'no extension'} is not an audio format"
                    ),
                }
            )
            continue

        try:
            track, created, warning = _create_track(uploaded_file)
        except ValueError as exc:
            counts["failed"] += 1
            results.append(
                {"name": name, "status": "failed", "reason": str(exc)}
            )
            continue
        except Exception as exc:
            # One unreadable file must not abandon the rest of the folder.
            counts["failed"] += 1
            results.append(
                {"name": name, "status": "failed", "reason": str(exc)}
            )
            continue

        status = "created" if created else "duplicate"
        counts[status] += 1

        entry = {
            "name": name,
            "status": status,
            "track": _serialize_track(request, track),
        }

        if warning:
            entry["metadata_warning"] = warning

        results.append(entry)

    return JsonResponse(
        {
            "received": len(uploads),
            "counts": counts,
            "results": results,
        },
        status=201 if counts["created"] else 200,
    )


@require_http_methods(["GET", "HEAD"])
def stream_track(request, track_id):
    track = get_object_or_404(Track, pk=track_id)
    content_type = track.mime_type or "audio/mpeg"
    file_size = track.file_size
    range_header = request.headers.get("Range", "")

    if range_header.startswith("bytes=") and file_size:
        range_value = range_header.removeprefix("bytes=").split(",", 1)[0]
        start_text, _, end_text = range_value.partition("-")

        try:
            if start_text:
                start = int(start_text)
                end = int(end_text) if end_text else file_size - 1
            else:
                suffix_length = int(end_text)
                start = max(file_size - suffix_length, 0)
                end = file_size - 1
        except ValueError:
            start = 0
            end = file_size - 1

        start = max(start, 0)
        end = min(end, file_size - 1)

        if start > end:
            response = HttpResponse(status=416)
            response["Content-Range"] = f"bytes */{file_size}"
            return response

        length = end - start + 1
        response = StreamingHttpResponse(
            _read_file_range(track.file.open("rb"), start, length),
            status=206,
            content_type=content_type,
        )
        response["Content-Length"] = str(length)
        response["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        response["Accept-Ranges"] = "bytes"
        response["Content-Disposition"] = (
            f'inline; filename="{track.original_filename}"'
        )

        return response

    response = FileResponse(
        track.file.open("rb"),
        content_type=content_type,
    )

    response["Accept-Ranges"] = "bytes"
    response["Content-Length"] = str(file_size)
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
