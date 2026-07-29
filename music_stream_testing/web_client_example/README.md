# Web Client Example

A browser-based player for the raw-PCM stream served by `server.py`. Enter a
file name, click **Play**, and the page plays back the PCM the server streams,
using the Web Audio API. You can **seek** (drag the bar), **pause/resume**, and
replay without reconnecting.

## Why a bridge is needed

A browser cannot open a raw TCP socket — JavaScript only gets HTTP and
WebSockets. So the page cannot talk to `server.py` directly. `bridge.py` sits in
between: it accepts a WebSocket from the page and, per connection, opens a plain
TCP connection to the server, then relays bytes verbatim in both directions.

```
  browser  ──WebSocket──▶  bridge.py  ──TCP──▶  server.py
   (page)  ◀──────────────           ◀────────  (raw PCM)
```

The bridge never parses the protocol — it just copies bytes — so the page speaks
the exact same wire format (`request → status → header → PCM`) it would over
TCP. All the protocol parsing and PCM decoding lives in `index.html`.

## Running it

Three processes, in three terminals, from the project root:

```bash
# 1. The audio server (unchanged)
python3 server.py

# 2. The WebSocket bridge
pip install -r web_client_example/requirements.txt
python3 web_client_example/bridge.py

# 3. Serve the page (browsers restrict file:// pages, so serve over HTTP)
python3 -m http.server 8000 --directory web_client_example
```

Then open <http://localhost:8000> and click **Play**. `club_music.ogg` and
`retro.flac` are in the server's `media/` folder by default.

## Options

`bridge.py` takes `--ws-host`, `--ws-port`, `--tcp-host`, and `--tcp-port` if
the server or the page live somewhere other than the defaults
(`ws://127.0.0.1:8765` → `tcp 127.0.0.1:5001`). The page's **Bridge host/port**
fields must match `--ws-host`/`--ws-port`.

## How the page plays PCM

The server sends signed 16-bit little-endian PCM as fast as the socket accepts
it, so the whole song arrives in about a second. The page:

1. sends the length-prefixed file-name request,
2. reads the 1-byte status and, on OK, the 8-byte `channels`/`rate` header,
3. converts each block of PCM to floats, de-interleaves it per channel, and
   schedules it on the Web Audio timeline so blocks play back-to-back with no
   gaps — buffering the rest of the song ahead of the playback clock.

## How seeking works

Seeking is **entirely client-side** — `server.py` and `protocol.py` are
unchanged. Because the server sends the whole song as fast as the socket
accepts it, the browser holds all the decoded PCM within about a second, so
there is nothing to fetch when you seek.

The page retains the received PCM as frame-aligned segments and derives the play
position from the audio clock (`frame = anchor + elapsed × rate`). A seek, a
pause, and a resume are the same operation underneath: stop the scheduled audio
sources and re-anchor playback to a new frame. That means you can seek anywhere
already buffered, pause/resume, and replay after the song ends — all without
reconnecting.

The trade-off is the flip side of the "send as fast as possible" server: the
whole song lives in browser memory, and you can only seek into what has
buffered (nearly the entire track, almost immediately). Seeking a very long
track, or one streamed in real time, would instead need a seek request in the
protocol so the server could restart ffmpeg at an offset (`-ss`).
