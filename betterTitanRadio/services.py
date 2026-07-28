import hashlib
import mimetypes
import re
from pathlib import Path
from typing import Any

from mutagen import File as MutagenFile

from .forms import ALLOWED_AUDIO_EXTENSIONS
from .models import Track


def _first_tag(tags: Any, *keys: str) -> str:
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


def _parse_number(value: str) -> int | None:
    if not value:
        return None

    try:
        return int(value.split("/", 1)[0].strip())
    except (TypeError, ValueError):
        return None


def _parse_year(value: str) -> int | None:
    if not value:
        return None

    match = re.search(r"\b(18|19|20|21)\d{2}\b", value)

    if match:
        return int(match.group(0))

    return None


def _hash_upload(uploaded_file) -> str:
    digest = hashlib.sha256()

    for chunk in uploaded_file.chunks():
        digest.update(chunk)

    uploaded_file.seek(0)

    return digest.hexdigest()


def extract_metadata(file_path: str | Path) -> dict:
    path = Path(file_path)
    audio = MutagenFile(path, easy=True)

    if audio is None:
        return {
            "title": path.stem,
        }

    tags = audio.tags or {}
    info = audio.info

    date_value = _first_tag(
        tags,
        "date",
        "originaldate",
    )

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
        "title": (
            _first_tag(tags, "title")
            or path.stem
        ),
        "artist": _first_tag(tags, "artist"),
        "album": _first_tag(tags, "album"),
        "album_artist": _first_tag(
            tags,
            "albumartist",
        ),
        "genre": genre,
        "year": _parse_year(date_value),
        "track_number": _parse_number(
            _first_tag(tags, "tracknumber")
        ),
        "disc_number": _parse_number(
            _first_tag(tags, "discnumber")
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


def create_track(uploaded_file) -> tuple[Track, bool]:
    extension = Path(
        uploaded_file.name
    ).suffix.lower()

    if extension not in ALLOWED_AUDIO_EXTENSIONS:
        raise ValueError("Unsupported audio format.")

    sha256 = _hash_upload(uploaded_file)

    existing = Track.objects.filter(
        sha256=sha256,
    ).first()

    if existing:
        return existing, False

    mime_type, _ = mimetypes.guess_type(
        uploaded_file.name
    )

    track = Track(
        file=uploaded_file,
        original_filename=uploaded_file.name,
        file_size=uploaded_file.size,
        mime_type=mime_type or "audio/mpeg",
        sha256=sha256,
    )

    # file must exist on disk before mutagen reads it.
    track.save()

    metadata = extract_metadata(track.file.path)

    for field, value in metadata.items():
        if value not in (None, ""):
            setattr(track, field, value)

    track.save()

    return track, True