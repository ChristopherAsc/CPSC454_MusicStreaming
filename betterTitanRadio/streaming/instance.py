import socket
import struct
import threading

from . import protocol
from .encoder import AudioEncoder


class AudioStreamerInstance:
    """One client connection paired with its own encoder, streaming PCM audio to that client.

    Owns both resources for the lifetime of the connection and releases them in
    the correct order. Usable as a context manager, which guarantees close()
    runs even if streaming raises:

        with AudioStreamerInstance(conn, addr) as instance:
            instance.start(source)
            instance.stream()
    """

    CHUNK_SIZE = 4096

    def __init__(self, conn, addr, chunk_size=CHUNK_SIZE):
        self._conn = conn
        self._addr = addr
        self._chunk_size = chunk_size
        self._encoder = None
        self._pcm_stream = None
        self._closed = False
        self._stop_event = threading.Event()

    @property
    def addr(self):
        return self._addr

    def receive_request(self):
        """Read the sha256 digest this client is asking for.

        Returns the requested digest as a string, or None if the client hung up
        or sent a malformed request. The value is untrusted -- the caller must
        validate it before it reaches the database.
        """
        raw_len = protocol.recv_exact(self._conn, protocol.REQUEST_LEN_SIZE)
        if raw_len is None:
            return None
        (length,) = struct.unpack(protocol.REQUEST_LEN_FORMAT, raw_len)
        if length == 0 or length > protocol.MAX_REQUEST_LEN:
            return None

        raw_digest = protocol.recv_exact(self._conn, length)
        if raw_digest is None:
            return None
        try:
            return raw_digest.decode('ascii')
        except UnicodeDecodeError:
            return None

    def send_status(self, status):
        """Tell the client we cannot serve its request."""
        self._conn.sendall(struct.pack(protocol.STATUS_FORMAT, status))

    def start(self, source):
        """Begin encoding `source` and send the client the OK status + stream header.

        `source` is an already-resolved resolver.AudioSource; this method takes
        ownership of it, so callers must not close it themselves afterwards.
        """
        self._encoder = AudioEncoder()
        self._pcm_stream = self._encoder.open(
            source.fileobj, source.channels, source.rate
        )

        # Status, then header: channels + sample rate as uint32s in network
        # byte order, so the client can configure playback before PCM arrives.
        self._conn.sendall(
            struct.pack(protocol.STATUS_FORMAT, protocol.STATUS_OK)
            + struct.pack(protocol.HEADER_FORMAT, source.channels, source.rate)
        )

    def stream(self):
        """Pump encoded PCM to the client as fast as the socket accepts it.

        Returns True if the whole file was sent, False if the client hung up
        early or close() stopped us.

        Deliberately unpaced: sendall() returns once the kernel buffers the
        bytes, not once the client plays them, so a song lands in the socket in
        about a second and the client buffers the rest. Note the consequence --
        an instance lives only as long as the transfer, not the playback, so
        the server's cap bounds simultaneous transfers (and their ffmpeg
        processes), not simultaneous listeners.
        """
        if self._pcm_stream is None:
            raise RuntimeError('start() must be called before stream()')

        try:
            while not self._stop_event.is_set():
                data = self._pcm_stream.read(self._chunk_size)
                if not data:
                    return True
                self._conn.sendall(data)
            return False
        except (BrokenPipeError, ConnectionResetError):
            return False
        except (ValueError, OSError):
            # Resources were torn down underneath us by a concurrent close().
            return False

    def close(self):
        """Release both resources.

        Teardown order matters -- do NOT reorder:
          1. encoder -- close first. Killing ffmpeg unblocks any read() parked
             waiting on PCM, so this can never hang.
          2. socket  -- close only once nothing can still try to send on it.
        """
        if self._closed:
            return
        self._closed = True
        # Wake stream() if it is mid-transfer.
        self._stop_event.set()

        # 1. Encoder first (kills ffmpeg, frees any blocked read, closes the
        #    source file it took ownership of).
        if self._encoder is not None:
            self._encoder.close()
            self._encoder = None
        self._pcm_stream = None

        # 2. Socket last. shutdown() first so a send blocked in another thread
        #    is released; it raises if the peer already vanished, which is fine.
        if self._conn is not None:
            try:
                self._conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self._conn.close()
            self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False
