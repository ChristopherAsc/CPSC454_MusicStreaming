"""Wire format shared by the stream server and its clients.

Exchange, in order:
  1. Request  -- uint16 length, then that many bytes of ASCII sha256 hex digest.
  2. Status   -- uint8, one of the STATUS_* codes below.
  3. Header   -- only when status is STATUS_OK: uint32 channels, uint32 rate.
  4. Payload  -- raw signed 16-bit little-endian PCM until the connection ends.

All integers are network byte order. A server at capacity closes the
connection without sending any status at all.

The request carries a **content hash, not a file name**: the server resolves it
against the Track table and streams whatever file that row points at. A client
therefore cannot name a path, so path traversal is not expressible in the
protocol -- an unknown digest is simply a row that does not exist.
"""

import re
import struct

STATUS_OK = 0
STATUS_NOT_FOUND = 1
STATUS_BAD_REQUEST = 2
STATUS_SERVER_ERROR = 3

STATUS_TEXT = {
    STATUS_NOT_FOUND: 'no track with that sha256',
    STATUS_BAD_REQUEST: 'malformed request',
    STATUS_SERVER_ERROR: 'the track could not be decoded',
}

REQUEST_LEN_FORMAT = '!H'
REQUEST_LEN_SIZE = struct.calcsize(REQUEST_LEN_FORMAT)
STATUS_FORMAT = '!B'
STATUS_SIZE = struct.calcsize(STATUS_FORMAT)
HEADER_FORMAT = '!II'
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

# A sha256 hex digest is exactly 64 characters, so this doubles as the bound on
# how much a hostile length prefix can make us read or allocate.
SHA256_HEX_LENGTH = 64
MAX_REQUEST_LEN = SHA256_HEX_LENGTH

_SHA256_HEX = re.compile(r'\A[0-9a-fA-F]{64}\Z')


def is_sha256_hex(value):
    """True if value is a 64-character hex digest, in either case.

    Checked before the digest reaches the database so a malformed request is
    rejected as BAD_REQUEST rather than becoming a pointless query.
    """
    return bool(value) and bool(_SHA256_HEX.match(value))


def normalize_digest(value):
    """Fold a digest to the lowercase form stored in the database.

    Python's hexdigest() is lowercase, so that is what the column holds, but a
    client hashing elsewhere may well send uppercase -- and an exact-match
    lookup would silently miss. Case is the only thing forgiven here.
    """
    return value.lower()


def recv_exact(sock, n):
    """Receive exactly n bytes, or None if the connection closes first.

    TCP may split any read, so multi-byte fields must be reassembled rather
    than assumed to arrive whole.
    """
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)
