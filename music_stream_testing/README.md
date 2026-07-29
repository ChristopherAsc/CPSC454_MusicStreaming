# Music Streaming

A small TCP server that decodes audio files to raw PCM with ffmpeg and streams
them to connecting clients. Two clients are included: a native terminal player
(PyAudio) and a browser player (Web Audio API, reached through a WebSocket
bridge).

```
                                            ┌────────────────────────────┐
  audio file ──▶ encoder.py (ffmpeg) ──PCM──▶  server.py  (TCP :5001)    │
                                            └──────────┬──────────┬──────┘
                                                       │ TCP      │ TCP
                                              client.py│          │bridge.py (WebSocket :8765)
                                              (PyAudio) │          │
                                                        ▼          ▼
                                                 terminal     browser (index.html)
```

## The wire protocol

Server and clients share one format, defined in `protocol.py`. Per connection,
in order:

1. **Request** — uint16 length, then that many bytes of UTF-8 file name.
2. **Status** — uint8: `0` OK, `1` not found, `2` bad request.
3. **Header** — on OK only: uint32 channels, uint32 sample rate.
4. **Payload** — raw signed 16-bit little-endian PCM until the connection closes.

All integers are network byte order. A server at capacity closes without
sending a status at all.

## Components

| File | Role |
|------|------|
| `protocol.py` | Shared wire format: status codes, struct layouts, `recv_exact()`. |
| `encoder.py` | `AudioEncoder` — decodes a file to PCM by piping it through ffmpeg, feeding ffmpeg's stdin on a background thread so decode and read run concurrently. Exposes the PCM as a readable stream. |
| `audio_streamer_instance.py` | `AudioStreamerInstance` — one client connection paired with its own encoder. Owns both resources and tears them down in the right order (encoder before socket). |
| `server.py` | `StreamServer` — accepts clients, runs one instance per connection on its own thread, and caps concurrent streams. Resolves requested names safely inside `media/` (no traversal, no URL inputs). |
| `client.py` | `AudioStreamClient` — the terminal player: requests a file and plays the PCM with PyAudio. |
| `web_client_example/` | The browser player and the WebSocket↔TCP bridge it needs. See its own README. |
| `media/` | The only directory the server will stream from. Ships with `club_music.ogg` and `retro.flac`. |

### server.py

- **One instance per client, each on its own thread**, tracked in a registry
  guarded by a lock.
- **Capacity cap** (`--max-instances`, default 4). Each live stream is one
  ffmpeg process, so the cap bounds simultaneous transcodes. The check and the
  registration happen under a single lock hold so connections can't race past
  it. Note that because PCM is sent as fast as the socket accepts it, an
  instance lives only as long as the *transfer*, not the listener's playback.
- **Safe file resolution** — a client names a file, never a path. Anything with
  a separator, a parent reference (`..`), or a leading dot is refused, and the
  resolved path must stay inside `media/`. This also blocks ffmpeg URL inputs,
  so a client can't make the server fetch arbitrary URLs.
- **Clean shutdown** — stops accepting, then tears down every live instance and
  joins its thread.

### client.py (terminal)

- Requests a file, validates the advertised format before opening PortAudio
  (rejects out-of-range channel counts / sample rates), then plays the stream.
- Silences ALSA's device-probe noise on Linux via a no-op libasound error
  handler.

### web_client_example/ (browser)

A browser can't open a raw TCP socket, so `bridge.py` accepts a WebSocket and
relays bytes verbatim to a per-connection TCP link to `server.py`. The page
(`index.html`) speaks the same protocol, decodes the PCM, and plays it with the
Web Audio API — with **seek, pause/resume, and replay**, all client-side since
the whole song buffers in about a second. Full details in
[`web_client_example/README.md`](web_client_example/README.md).

## Running it

Install dependencies (ffmpeg must be on `PATH`):

```bash
pip install -r requirements.txt
```

**Terminal client:**

```bash
python3 server.py                 # listens on 0.0.0.0:5001
python3 client.py club_music.ogg  # in another terminal
```

**Browser client** (three terminals, from this directory):

```bash
python3 server.py
python3 web_client_example/bridge.py
python3 -m http.server 8000 --directory web_client_example
# then open http://localhost:8000
```

### Useful flags

- `server.py`: `--host`, `--port`, `--max-instances`
- `client.py`: `filename` (positional), `--host`, `--port`
- `bridge.py`: `--ws-host`, `--ws-port`, `--tcp-host`, `--tcp-port`
