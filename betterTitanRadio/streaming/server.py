import logging
import socket
import threading

from django.db import connection as db_connection

from . import protocol, resolver
from .instance import AudioStreamerInstance

log = logging.getLogger(__name__)

HOST = '127.0.0.1'
PORT = 5001
BACKLOG = 5
# Each live instance spawns its own ffmpeg process, so simultaneous streams are
# capped to keep N clients from turning into N unbounded transcodes.
MAX_INSTANCES = 4


class StreamServer:
    """Accepts clients and owns the lifetime of one AudioStreamerInstance per connection.

    Each instance streams on its own thread, so the registry below is touched
    from several threads at once and every read/write of it is guarded by _lock.

    A client asks for a track by sha256; the digest is resolved against the
    Track table (see resolver.py), never against the filesystem.
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
        log.info('Stream server listening on %s:%s', self._host, self._port)

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
            completed = self._serve_request(instance)
        except (BrokenPipeError, ConnectionResetError, OSError, ValueError):
            # Client vanished, or shutdown() closed our resources underneath us.
            completed = False
        finally:
            # Django opens a connection per thread and would otherwise hold it
            # for the process's lifetime; with one thread per stream that leaks
            # a connection per client until the database refuses new ones.
            db_connection.close()

        if completed:
            log.info('Finished streaming to %s', instance.addr)
        self.remove_instance(instance)

    def _serve_request(self, instance):
        """Run one request/response exchange. Returns True if the track was fully sent."""
        digest = instance.receive_request()
        # A digest that isn't 64 hex characters is a protocol error, not a miss.
        # Saying so leaks nothing about the library -- the client already knows
        # what it sent -- and tells a broken client which of the two it is.
        if digest is None or not protocol.is_sha256_hex(digest):
            log.warning('Bad request from %s: %r', instance.addr, digest)
            instance.send_status(protocol.STATUS_BAD_REQUEST)
            return False

        track = resolver.find_track(digest)
        if track is None:
            log.warning('%s requested unknown sha256: %r', instance.addr, digest)
            instance.send_status(protocol.STATUS_NOT_FOUND)
            return False

        source = resolver.open_source(track)
        if source is None:
            # The row exists but its file is missing or undecodable -- that is
            # our problem, not a bad request, so say so distinctly.
            log.error('%s requested undecodable track %s', instance.addr, track.pk)
            instance.send_status(protocol.STATUS_SERVER_ERROR)
            return False

        log.info('%s requested %s (track %s)', instance.addr, track.display_title, track.pk)
        # start() takes ownership of `source`; the instance closes it.
        instance.start(source)
        return instance.stream()

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
        log.info('Shutting down stream server')

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
