"""WebSocket <-> TCP bridge, so a browser can reach the raw-PCM stream server.

A web page cannot open a raw TCP socket -- the browser only gives JavaScript
WebSockets and HTTP. This process bridges the gap: it accepts a WebSocket from
the page and, for each one, opens a plain TCP connection to server.py, then
relays bytes between the two in both directions.

The bridge is deliberately dumb about the protocol. It copies bytes verbatim, so
the browser speaks exactly the same wire format (request -> status -> header ->
PCM) it would over TCP; all the parsing lives in the page. Every browser
connection gets its own TCP connection to the server, which is what the server's
per-connection instance model already expects.

Run it alongside the server:

    python3 server.py
    python3 web_client_example/bridge.py
"""

import argparse
import asyncio
import logging

import websockets

log = logging.getLogger(__name__)

WS_HOST = '127.0.0.1'
WS_PORT = 8765
TCP_HOST = '127.0.0.1'
TCP_PORT = 5001
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


async def handle_browser(websocket):
    """Bridge one browser connection to its own TCP connection to the server."""
    peer = websocket.remote_address
    try:
        reader, writer = await asyncio.open_connection(TCP_HOST, TCP_PORT)
    except OSError as exc:
        log.error('%s: cannot reach audio server at %s:%s (%s)', peer, TCP_HOST, TCP_PORT, exc)
        # 1011 = server error; the page shows this as a failed connection.
        await websocket.close(code=1011, reason='audio server unavailable')
        return

    log.info('%s connected, bridging to %s:%s', peer, TCP_HOST, TCP_PORT)
    up = asyncio.create_task(_ws_to_tcp(websocket, writer))
    down = asyncio.create_task(_tcp_to_ws(reader, websocket))
    try:
        # The stream is over as soon as EITHER direction ends: the server closes
        # the TCP side when the song finishes (down completes), or the user
        # navigates away and the WebSocket drops (up completes). Tear down both.
        done, pending = await asyncio.wait(
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


async def serve(ws_host, ws_port):
    async with websockets.serve(handle_browser, ws_host, ws_port):
        log.info('Bridge listening on ws://%s:%s -> tcp %s:%s',
                 ws_host, ws_port, TCP_HOST, TCP_PORT)
        await asyncio.Future()  # run until interrupted


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--ws-host', default=WS_HOST,
                        help=f'address for the browser-facing WebSocket (default: {WS_HOST})')
    parser.add_argument('--ws-port', type=int, default=WS_PORT,
                        help=f'port for the WebSocket (default: {WS_PORT})')
    parser.add_argument('--tcp-host', default=TCP_HOST,
                        help=f'audio server address (default: {TCP_HOST})')
    parser.add_argument('--tcp-port', type=int, default=TCP_PORT,
                        help=f'audio server port (default: {TCP_PORT})')
    return parser.parse_args()


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s',
                        datefmt='%H:%M:%S')
    args = parse_args()
    global TCP_HOST, TCP_PORT
    TCP_HOST, TCP_PORT = args.tcp_host, args.tcp_port
    try:
        asyncio.run(serve(args.ws_host, args.ws_port))
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
