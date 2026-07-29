"""Run the raw-PCM stream server (and, by default, its WebSocket bridge).

A management command rather than a standalone script so the streaming code runs
inside a configured Django process -- settings loaded, apps ready, ORM usable --
which is what lets the server resolve a requested sha256 against the Track table.

    python manage.py runstreamserver
    python manage.py runstreamserver --no-bridge --port 5002
"""

import logging
import threading

from django.conf import settings
from django.core.management.base import BaseCommand

from betterTitanRadio.streaming import bridge as bridge_module
from betterTitanRadio.streaming.server import StreamServer


class Command(BaseCommand):
    help = 'Stream tracks as raw PCM over TCP, with a WebSocket bridge for browsers.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--host',
            default=settings.STREAM_SERVER_HOST,
            help='address the TCP server binds to (default: %(default)s)',
        )
        parser.add_argument(
            '--port',
            type=int,
            default=settings.STREAM_SERVER_PORT,
            help='port the TCP server binds to (default: %(default)s)',
        )
        parser.add_argument(
            '--max-instances',
            type=int,
            default=settings.STREAM_MAX_INSTANCES,
            help='simultaneous streams allowed, one ffmpeg each (default: %(default)s)',
        )
        parser.add_argument(
            '--bridge-host',
            default=settings.STREAM_BRIDGE_HOST,
            help='address the browser-facing WebSocket binds to (default: %(default)s)',
        )
        parser.add_argument(
            '--bridge-port',
            type=int,
            default=settings.STREAM_BRIDGE_PORT,
            help='port for the WebSocket bridge (default: %(default)s)',
        )
        parser.add_argument(
            '--no-bridge',
            action='store_true',
            help='run only the TCP server; browsers will have nothing to connect to',
        )

    def handle(self, *args, **options):
        self._configure_logging(options['verbosity'])

        host, port = options['host'], options['port']
        server = StreamServer(
            host=host,
            port=port,
            max_instances=options['max_instances'],
        )

        if not options['no_bridge']:
            # The bridge is asyncio and the server is blocking sockets, so the
            # bridge gets its own thread with its own event loop. Daemon, so
            # Ctrl-C in serve_forever() below is enough to end the process.
            threading.Thread(
                target=bridge_module.run,
                kwargs={
                    'ws_host': options['bridge_host'],
                    'ws_port': options['bridge_port'],
                    'tcp_host': '127.0.0.1' if host == '0.0.0.0' else host,
                    'tcp_port': port,
                },
                daemon=True,
                name='ws-bridge',
            ).start()

        self.stdout.write(self.style.SUCCESS(
            f'Stream server on {host}:{port}'
            + ('' if options['no_bridge']
               else f", bridge on ws://{options['bridge_host']}:{options['bridge_port']}")
            + '  (Ctrl-C to stop)'
        ))

        try:
            server.serve_forever()
        except KeyboardInterrupt:
            # serve_forever's finally already runs shutdown().
            self.stdout.write('\nStopped.')

    def _configure_logging(self, verbosity):
        """Send the streaming package's logs to the console.

        Configured here rather than at import: this is the entry point, so
        importing StreamServer elsewhere won't hijack the root logger.
        """
        handler = logging.StreamHandler(self.stdout)
        handler.setFormatter(logging.Formatter(
            '%(asctime)s [%(levelname)s] %(threadName)s | %(message)s',
            datefmt='%H:%M:%S',
        ))
        package_log = logging.getLogger('betterTitanRadio.streaming')
        package_log.handlers = [handler]
        package_log.setLevel(logging.WARNING if verbosity == 0 else logging.INFO)
        package_log.propagate = False
