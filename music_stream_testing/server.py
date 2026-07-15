import logging
import os
import socket
import threading

import protocol
from audio_streamer_instance import AudioStreamerInstance

log = logging.getLogger(__name__)

HOST = '0.0.0.0'
PORT = 5001
BACKLOG = 5
# Each live instance spawns its own ffmpeg process, so simultaneous streams are
# capped to keep N clients from turning into N unbounded transcodes.
MAX_INSTANCES = 4
# Only files directly inside this directory may be streamed. It is a dedicated
# folder holding nothing but media, so a client can never name source code or
# anything else in the project, even before the checks in resolve_media_path().
MEDIA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'media')


def resolve_media_path(requested):
    """Resolve a client-supplied name to a real file inside MEDIA_DIR.

    Returns None if the name is unsafe or no such file exists. The client names
    a file, never a path: anything with a separator, a parent reference, or a
    leading dot is refused outright. That also rules out ffmpeg URL inputs
    (http://...), which would otherwise reach ffprobe and let a client make the
    server fetch arbitrary URLs.
    """
    if not requested or requested.startswith('.'):
        return None
    if '/' in requested or '\\' in requested or '\x00' in requested:
        return None

    candidate = os.path.realpath(os.path.join(MEDIA_DIR, requested))
    media_root = os.path.realpath(MEDIA_DIR)
    # Containment check against the resolved path: realpath collapses '..' and
    # follows symlinks, so this catches traversal that name checks alone miss.
    if os.path.commonpath([candidate, media_root]) != media_root:
        return None
    if not os.path.isfile(candidate):
        return None
    return candidate


class StreamServer:
    """Accepts clients and owns the lifetime of one AudioStreamerInstance per connection.

    Each instance streams on its own thread, so the registry below is touched
    from several threads at once and every read/write of it is guarded by _lock.
    """

    def __init__(self, host=HOST, port=PORT, max_instances=MAX_INSTANCES):
        self._host = host
        self._port = port
        self._max_instances = max_instances
        self._sock = None
        self._workers = {}  # live AudioStreamerInstance -> its streaming thread
        self._lock = threading.Lock()
        self._running = False

    @property
    def instance_count(self):
        """How many instances are currently streaming."""
        with self._lock:
            return len(self._workers)

    def serve_forever(self):
        """Listen and spawn an instance per client until interrupted."""
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((self._host, self._port))
        self._sock.listen(BACKLOG)
        self._running = True
        log.info('Server listening on %s:%s', self._host, self._port)

        try:
            while self._running:
                try:
                    conn, addr = self._sock.accept()
                except OSError:
                    break  # listening socket closed by shutdown()
                self.create_instance(conn, addr)
        finally:
            self.shutdown()

    def create_instance(self, conn, addr):
        """Register a new instance for this client and start streaming to it.

        Returns False and drops the connection if the server is at capacity.
        """
        with self._lock:
            # Check the cap and register in one lock hold: doing it in two
            # steps would let connections race past the check and exceed it.
            at_capacity = len(self._workers) >= self._max_instances
            if not at_capacity:
                instance = AudioStreamerInstance(conn, addr)
                thread = threading.Thread(
                    target=self._run_instance,
                    args=(instance,),
                    daemon=True,
                    # Name the thread after its client so concurrent streams
                    # are tellable apart in the log's threadName field.
                    name=f'stream-{addr[0]}:{addr[1]}',
                )
                self._workers[instance] = thread

        if at_capacity:
            # Just close: the client reads no header and reports the refusal.
            log.warning('Rejected %s: at capacity (%d streams)', addr, self._max_instances)
            conn.close()
            return False

        thread.start()
        log.info('Client connected: %s (%d active)', addr, self.instance_count)
        return True

    def _run_instance(self, instance):
        """Body of a streaming thread: serve one client's request, then deregister."""
        try:
            requested = instance.receive_request()
            if requested is None:
                log.warning('Bad request from %s', instance.addr)
                instance.send_status(protocol.STATUS_BAD_REQUEST)
                completed = False
            else:
                path = resolve_media_path(requested)
                if path is None:
                    # Same response for unsafe and merely-missing names, so a
                    # client can't probe the filesystem by reading the replies.
                    log.warning(
                        '%s requested unavailable file: %r', instance.addr, requested
                    )
                    instance.send_status(protocol.STATUS_NOT_FOUND)
                    completed = False
                else:
                    log.info('%s requested %s', instance.addr, os.path.basename(path))
                    instance.start(path)
                    completed = instance.stream()
        except (BrokenPipeError, ConnectionResetError, OSError, ValueError):
            # Client vanished, or shutdown() closed our resources underneath us.
            completed = False

        if completed:
            log.info('Finished streaming to %s', instance.addr)
        self.remove_instance(instance)

    def remove_instance(self, instance):
        """Close an instance and drop it from the registry. Safe to call twice."""
        instance.close()
        with self._lock:
            self._workers.pop(instance, None)

    def shutdown(self):
        """Stop accepting, tear down every live instance, and wait for its thread."""
        if not self._running:
            return
        self._running = False
        log.info('Shutting down server')

        # 1. Stop accepting first, so no new instance appears mid-shutdown.
        if self._sock is not None:
            self._sock.close()
            self._sock = None

        # 2. Snapshot the registry under the lock, but close OUTSIDE it: close()
        #    unblocks each worker, which then takes the lock itself to
        #    deregister -- holding it here would stall them into a deadlock.
        with self._lock:
            workers = list(self._workers.items())

        for instance, _thread in workers:
            instance.close()
        for _instance, thread in workers:
            thread.join(timeout=2)

        with self._lock:
            self._workers.clear()
        log.info('All instances closed')


def main():
    # Configured here rather than at import: this is the entry point, so
    # importing StreamServer elsewhere won't hijack the root logger.
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(threadName)s | %(message)s',
        datefmt='%H:%M:%S',
    )
    server = StreamServer()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass  # serve_forever's finally already runs shutdown()


if __name__ == '__main__':
    main()
