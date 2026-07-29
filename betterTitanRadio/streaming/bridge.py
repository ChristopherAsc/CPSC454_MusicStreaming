"""WebSocket <-> TCP bridge, so a browser can reach the raw-PCM stream server.

A web page cannot open a raw TCP socket -- the browser only gives JavaScript
WebSockets and HTTP. This bridge accepts a WebSocket from the page and, for each
one, opens a plain TCP connection to the stream server, then relays bytes
between the two in both directions.

The bridge is deliberately dumb about the protocol. It copies bytes verbatim, so
the browser speaks exactly the same wire format (request -> status -> header ->
PCM) it would over TCP; all the parsing lives in the page. Every browser
connection gets its own TCP connection to the server, which is what the server's
per-connection instance model already expects.

Run via the management command, which starts this alongside the TCP server:

    python manage.py runstreamserver
"""

import asyncio
import logging

import websockets

log = logging.getLogger(__name__)

WS_HOST = '127.0.0.1'
WS_PORT = 8765
# Matches the server's streaming chunk size; nothing breaks if it differs, since
# both sides reassemble the stream, but reading in similar units keeps latency
# and syscall counts sensible.
RELAY_CHUNK = 4096


async def _ws_to_tcp(websocket, writer):
    """Forward everything the browser sends into the TCP socket."""
    async for message in websocket:
        # The page only ever sends the binary request frame, but a stray text
        # frame would arrive as str -- encode it so writer.write() never chokes.
        if isinstance(message, str):
            message = message.encode('utf-8')
        writer.write(message)
        await writer.drain()


async def _tcp_to_ws(reader, websocket):
    """Forward the server's status, header, and PCM out to the browser."""
    while True:
        data = await reader.read(RELAY_CHUNK)
        if not data:
            return  # server finished the stream or hung up
        await websocket.send(data)


async def _handle_browser(websocket, tcp_host, tcp_port):
    """Bridge one browser connection to its own TCP connection to the server."""
    peer = websocket.remote_address
    try:
        reader, writer = await asyncio.open_connection(tcp_host, tcp_port)
    except OSError as exc:
        log.error('%s: cannot reach stream server at %s:%s (%s)',
                  peer, tcp_host, tcp_port, exc)
        # 1011 = server error; the page shows this as a failed connection.
        await websocket.close(code=1011, reason='stream server unavailable')
        return

    log.info('%s connected, bridging to %s:%s', peer, tcp_host, tcp_port)
    up = asyncio.create_task(_ws_to_tcp(websocket, writer))
    down = asyncio.create_task(_tcp_to_ws(reader, websocket))
    try:
        # The stream is over as soon as EITHER direction ends: the server closes
        # the TCP side when the song finishes (down completes), or the user
        # navigates away and the WebSocket drops (up completes). Tear down both.
        _done, pending = await asyncio.wait(
            {up, down}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass
        log.info('%s disconnected', peer)


async def serve(ws_host=WS_HOST, ws_port=WS_PORT,
                tcp_host='127.0.0.1', tcp_port=5001):
    """Run the bridge until the surrounding task is cancelled."""
    async def handler(websocket):
        await _handle_browser(websocket, tcp_host, tcp_port)

    async with websockets.serve(handler, ws_host, ws_port):
        log.info('Bridge listening on ws://%s:%s -> tcp %s:%s',
                 ws_host, ws_port, tcp_host, tcp_port)
        await asyncio.Future()  # run until cancelled


def run(ws_host=WS_HOST, ws_port=WS_PORT, tcp_host='127.0.0.1', tcp_port=5001):
    """Blocking entry point, for running the bridge on its own thread."""
    try:
        asyncio.run(serve(ws_host, ws_port, tcp_host, tcp_port))
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
