import socket
import struct

import pyaudio

HOST = '127.0.0.1'
PORT = 5001
CHUNK_SIZE = 4096


def recv_exact(sock, n):
    """Receive exactly n bytes, or None if the connection closes first."""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((HOST, PORT))
    print(f'Connected to {HOST}:{PORT}')

    # Read the header the server sends up front: channels and sample rate.
    header = recv_exact(sock, 8)
    if header is None:
        print('Server closed before sending stream header')
        sock.close()
        return
    channels, rate = struct.unpack('!II', header)
    # channels/rate arrive from the network as uint32 (up to ~4.3 billion) and
    # are passed straight into PortAudio's C layer, which sizes internal
    # buffers from them. Reject out-of-range values here so a malformed or
    # hostile server can't drive a huge native allocation or crash.
    if not (1 <= channels <= 8):
        print(f'Rejecting bogus channel count: {channels}')
        sock.close()
        return
    if not (8000 <= rate <= 192000):
        print(f'Rejecting bogus sample rate: {rate}')
        sock.close()
        return
    print(f'Stream format: {channels} channel(s) @ {rate} Hz')

    p = pyaudio.PyAudio()
    stream = p.open(format=pyaudio.paInt16, channels=channels, rate=rate, output=True)

    try:
        while True:
            data = sock.recv(CHUNK_SIZE)
            if not data:
                break
            stream.write(data)
        print('Stream ended')
    except KeyboardInterrupt:
        print('\nStopping playback')
    finally:
        stream.stop_stream()
        stream.close()
        p.terminate()
        sock.close()


if __name__ == '__main__':
    main()
