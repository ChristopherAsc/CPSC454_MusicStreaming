"""Turn a client-supplied sha256 into an openable, decodable audio source.

This is the only module in the streaming package that touches the database. The
server hands it an untrusted digest and gets back either a ready-to-decode
source or None; everything about how tracks are stored stays behind this
boundary.
"""

import logging

from mutagen import File as MutagenFile

from ..models import Track
from . import protocol

log = logging.getLogger(__name__)

# Guard rails on what we will advertise in the stream header. A client sizes its
# playback buffers from these numbers, so a nonsensical value from a corrupt tag
# should be rejected here rather than sent on.
MIN_CHANNELS, MAX_CHANNELS = 1, 8
MIN_RATE, MAX_RATE = 8000, 192000


class AudioSource:
    """A decodable track: the readable file plus the PCM format it will yield."""

    def __init__(self, track, fileobj, channels, rate):
        self.track = track
        self.fileobj = fileobj
        self.channels = channels
        self.rate = rate

    def close(self):
        try:
            self.fileobj.close()
        except (ValueError, OSError):
            pass


def find_track(digest):
    """Look up the Track with this sha256, or None.

    `digest` is untrusted input straight off the wire. It is validated as a hex
    digest before the query so a malformed value never reaches the database,
    and the lookup is an exact match on an indexed, unique column -- there is no
    pattern matching a caller could widen into a scan of the table.
    """
    if not protocol.is_sha256_hex(digest):
        return None
    return Track.objects.filter(sha256=protocol.normalize_digest(digest)).first()


def _probe_format(fileobj):
    """Read channels and sample rate from the file's own headers.

    Uses mutagen rather than ffprobe because ffprobe needs a real path, which
    only local storage provides -- mutagen reads straight from the file object,
    so S3-backed tracks probe the same way. Rewinds afterwards so the caller
    still gets the whole file.
    """
    try:
        audio = MutagenFile(fileobj)
    except Exception:
        audio = None
    finally:
        fileobj.seek(0)

    info = getattr(audio, 'info', None)
    if info is None:
        return None

    channels = getattr(info, 'channels', None)
    rate = getattr(info, 'sample_rate', None)
    if channels is None or rate is None:
        return None

    channels, rate = int(channels), int(rate)
    if not (MIN_CHANNELS <= channels <= MAX_CHANNELS):
        return None
    if not (MIN_RATE <= rate <= MAX_RATE):
        return None
    return channels, rate


def open_source(track):
    """Open `track`'s file and probe it, or None if it cannot be decoded.

    Storage-agnostic: `track.file.open()` works for both local disk and S3,
    where no filesystem path exists at all.
    """
    try:
        fileobj = track.file.open('rb')
    except (FileNotFoundError, OSError) as exc:
        log.error('Track %s: file %r is missing (%s)', track.pk, track.file.name, exc)
        return None

    try:
        probed = _probe_format(fileobj)
    except (ValueError, OSError) as exc:
        log.error('Track %s: cannot probe %r (%s)', track.pk, track.file.name, exc)
        probed = None

    if probed is None:
        log.error('Track %s: unreadable audio format in %r', track.pk, track.file.name)
        try:
            fileobj.close()
        except (ValueError, OSError):
            pass
        return None

    channels, rate = probed
    return AudioSource(track, fileobj, channels, rate)
