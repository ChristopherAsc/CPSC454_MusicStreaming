import socket
import struct

from encoder import AudioEncoder

HOST = '0.0.0.0'
PORT = 5001
FILE_INPUT = 'club_music.ogg'
CHUNK_SIZE = 4096


def handle_client(conn, addr):
    """Encode FILE_INPUT and stream its PCM bytes to a single connected client."""
    print(f'Client connected: {addr}')
    encoder = AudioEncoder()
    pcm_stream = encoder.open(FILE_INPUT)
    try:
        # Header first so the client can configure playback: two uint32s in
        # network byte order -- channel count and sample rate.
        conn.sendall(struct.pack('!II', encoder.channels, encoder.rate))

        while True:
            data = pcm_stream.read(CHUNK_SIZE)
            if not data:
                break
            conn.sendall(data)
        print(f'Finished streaming to {addr}')
    except (BrokenPipeError, ConnectionResetError):
        print(f'Client {addr} disconnected early')
    finally:
        encoder.close()
        conn.close()


def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(1)
    print(f'Server listening on {HOST}:{PORT}')

    try:
        while True:
            conn, addr = server.accept()
            handle_client(conn, addr)
    except KeyboardInterrupt:
        print('\nShutting down server')
    finally:
        server.close()


if __name__ == '__main__':
    main()
