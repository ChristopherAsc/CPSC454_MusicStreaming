import argparse
import ctypes
import logging
import socket
import struct

import pyaudio

import protocol

log = logging.getLogger(__name__)

HOST = '127.0.0.1'
PORT = 5001
CHUNK_SIZE = 4096

# Signature of libasound's error callback: (file, line, function, err, fmt).
_ALSA_ERROR_HANDLER_TYPE = ctypes.CFUNCTYPE(
    None, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p
)
# libasound keeps the raw pointer we hand it, so the callback object must stay
# referenced here. If it were local it would be garbage collected and the next
# ALSA warning would call into freed memory.
_alsa_error_handler = None

# Sane bounds for a format advertised by the server (see connect()).
MIN_CHANNELS, MAX_CHANNELS = 1, 8
MIN_RATE, MAX_RATE = 8000, 192000


def silence_alsa_warnings():
    """Stop libasound printing device-probe noise to stderr.

    Opening a device makes ALSA probe hardware this machine may not have, and
    it reports each miss ('Unknown PCM cards.pcm.rear', 'Cannot open device
    /dev/dsp') straight to stderr from C -- beneath Python, so logging cannot
    filter it. Handing it a no-op handler is the supported way to quiet it.
    Playback is unaffected: these are probe results, not failures.
    """
    global _alsa_error_handler

    def ignore(filename, line, function, err, fmt):
        pass

    _alsa_error_handler = _ALSA_ERROR_HANDLER_TYPE(ignore)
    try:
        asound = ctypes.CDLL('libasound.so.2')
        asound.snd_lib_error_set_handler(_alsa_error_handler)
    except (OSError, AttributeError):
        # No libasound (non-Linux, or a different audio stack): nothing to do.
        pass


class AudioStreamClient:
    """Owns the socket connection and playback device for one server stream.

    The client-side counterpart to AudioStreamerInstance: it owns both
    resources for the life of the connection and releases them in the correct
    order. Usable as a context manager, which guarantees close() runs even if
    playback raises:

        with AudioStreamClient() as client:
            if client.connect('club_music.ogg'):
                client.play()
    """

    def __init__(self, host=HOST, port=PORT, chunk_size=CHUNK_SIZE):
        self._host = host
        self._port = port
        self._chunk_size = chunk_size
        self._sock = None
        self._pyaudio = None
        self._stream = None
        self._closed = False
        self.channels = None
        self.rate = None

    def connect(self, filename):
        """Connect, request filename, and open the playback device for it.

        Returns False if the server refused the request, closed on us, or
        advertised a format we will not accept.
        """
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.connect((self._host, self._port))
        log.info('Connected to %s:%s', self._host, self._port)

        if not self._send_request(filename):
            return False
        if not self._read_status():
            return False
        return self._read_header()

    def _send_request(self, filename):
        """Send the requested filename as a length-prefixed UTF-8 string."""
        encoded = filename.encode('utf-8')
        if not encoded or len(encoded) > protocol.MAX_REQUEST_LEN:
            log.error('Filename must be 1-%d bytes: %r', protocol.MAX_REQUEST_LEN, filename)
            return False
        self._sock.sendall(struct.pack(protocol.REQUEST_LEN_FORMAT, len(encoded)) + encoded)
        log.info('Requested %r', filename)
        return True

    def _read_status(self):
        """Read the server's verdict on our request."""
        try:
            raw = protocol.recv_exact(self._sock, protocol.STATUS_SIZE)
        except ConnectionResetError:
            # A server at capacity closes on us with our request still unread
            # in its receive buffer, which makes the kernel answer with RST
            # rather than a clean FIN. Same meaning as a silent close.
            raw = None
        if raw is None:
            log.error('Server closed without responding (it may be at capacity)')
            return False
        (status,) = struct.unpack(protocol.STATUS_FORMAT, raw)
        if status != protocol.STATUS_OK:
            reason = protocol.STATUS_TEXT.get(status, f'unknown status {status}')
            log.error('Server refused the request: %s', reason)
            return False
        return True

    def _read_header(self):
        """Read and validate the advertised stream format, then open the device."""
        header = protocol.recv_exact(self._sock, protocol.HEADER_SIZE)
        if header is None:
            log.error('Server closed before sending the stream header')
            return False

        channels, rate = struct.unpack(protocol.HEADER_FORMAT, header)
        # channels/rate arrive from the network as uint32 (up to ~4.3 billion)
        # and are passed straight into PortAudio's C layer, which sizes
        # internal buffers from them. Reject out-of-range values here so a
        # malformed or hostile server can't drive a huge native allocation.
        if not (MIN_CHANNELS <= channels <= MAX_CHANNELS):
            log.error('Rejecting bogus channel count: %d', channels)
            return False
        if not (MIN_RATE <= rate <= MAX_RATE):
            log.error('Rejecting bogus sample rate: %d', rate)
            return False

        self.channels = channels
        self.rate = rate
        log.info('Stream format: %d channel(s) @ %d Hz', channels, rate)

        self._pyaudio = pyaudio.PyAudio()
        self._stream = self._pyaudio.open(
            format=pyaudio.paInt16,
            channels=channels,
            rate=rate,
            output=True,
        )
        return True

    def play(self):
        """Play the incoming stream until the server finishes or hangs up.

        Returns True if the stream ended normally, False if it was cut short.
        """
        if self._stream is None:
            raise RuntimeError('connect() must succeed before play()')

        try:
            while True:
                data = self._sock.recv(self._chunk_size)
                if not data:
                    return True
                self._stream.write(data)
        except (ConnectionResetError, BrokenPipeError):
            log.error('Connection to server lost')
            return False
        except (ValueError, OSError):
            # Resources were torn down underneath us by a concurrent close().
            return False

    def close(self):
        """Release both resources.

        Teardown order matters -- do NOT reorder:
          1. socket -- close first. It is the source feeding playback, so
             closing it unblocks a recv() parked waiting on a server that went
             quiet, exactly as killing ffmpeg frees the server's reads.
          2. device -- stop/close the PyAudio stream only once nothing can feed
             it, then terminate the PyAudio instance last.
        """
        if self._closed:
            return
        self._closed = True

        # 1. Socket first (frees any blocked recv).
        if self._sock is not None:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass  # peer already gone
            self._sock.close()
            self._sock = None

        # 2. Playback device second (guarded: an aborted stream can raise).
        if self._stream is not None:
            try:
                self._stream.stop_stream()
            except (ValueError, OSError):
                pass
            self._stream.close()
            self._stream = None

        if self._pyaudio is not None:
            self._pyaudio.terminate()
            self._pyaudio = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


def parse_args():
    parser = argparse.ArgumentParser(
        description='Request an audio file from the stream server and play it.'
    )
    parser.add_argument(
        'filename',
        help='name of the audio file to play, as it appears in the server media directory',
    )
    parser.add_argument('--host', default=HOST, help=f'server address (default: {HOST})')
    parser.add_argument('--port', type=int, default=PORT, help=f'server port (default: {PORT})')
    return parser.parse_args()


def main():
    # Bare message format: this is a single-threaded CLI, so timestamps and
    # levels would only clutter what the user reads.
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    # Must run before PyAudio initialises, which is what triggers the probing.
    silence_alsa_warnings()
    args = parse_args()
    # The context manager owns the socket + device and closes both in order,
    # even if connect()/play() raise.
    with AudioStreamClient(host=args.host, port=args.port) as client:
        try:
            if not client.connect(args.filename):
                return
            if client.play():
                log.info('Stream ended')
        except (ConnectionRefusedError, OSError) as exc:
            log.error('Could not stream: %s', exc)
        except KeyboardInterrupt:
            log.info('Stopping playback')


if __name__ == '__main__':
    main()
