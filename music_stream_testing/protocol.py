"""Wire format shared by the server and client.

Exchange, in order:
  1. Request  -- uint16 length, then that many bytes of UTF-8 filename.
  2. Status   -- uint8, one of the STATUS_* codes below.
  3. Header   -- only when status is STATUS_OK: uint32 channels, uint32 rate.
  4. Payload  -- raw signed 16-bit little-endian PCM until the connection ends.

All integers are network byte order. A server at capacity closes the
connection without sending any status at all.
"""

import struct

STATUS_OK = 0
STATUS_NOT_FOUND = 1
STATUS_BAD_REQUEST = 2

STATUS_TEXT = {
    STATUS_NOT_FOUND: 'file not available on the server',
    STATUS_BAD_REQUEST: 'malformed request',
}

REQUEST_LEN_FORMAT = '!H'
REQUEST_LEN_SIZE = struct.calcsize(REQUEST_LEN_FORMAT)
STATUS_FORMAT = '!B'
STATUS_SIZE = struct.calcsize(STATUS_FORMAT)
HEADER_FORMAT = '!II'
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)

# Bounds the filename a client may ask for, so a hostile length prefix can't
# make us allocate or read an unbounded amount.
MAX_REQUEST_LEN = 255


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
