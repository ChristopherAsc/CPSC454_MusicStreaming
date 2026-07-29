/**
 * PcmStreamPlayer -- plays the raw-PCM stream served by `manage.py runstreamserver`.
 *
 * Wire protocol (must match betterTitanRadio/streaming/protocol.py):
 *   Request : uint16 length (big-endian) + that many ASCII bytes of sha256 hex.
 *   Status  : uint8. 0 = OK, 1 = not found, 2 = bad request, 3 = server error.
 *   Header  : uint32 channels + uint32 rate, big-endian. Sent only on OK.
 *   Payload : raw signed 16-bit little-endian PCM until the connection closes.
 *
 * A browser cannot open a raw TCP socket, so this talks to the WebSocket bridge,
 * which relays bytes verbatim to the TCP server.
 *
 * The public surface deliberately mirrors the slice of HTMLAudioElement that the
 * dashboard already drives (play/pause/currentTime/duration/volume plus the
 * matching events), so the existing transport UI works against either one. The
 * one addition is `loadTrack(sha256)` in place of assigning `src`: this player
 * addresses a track by content hash, never by URL.
 *
 * Seeking is entirely client-side. The server sends the whole song as fast as
 * the socket accepts it, so within about a second the browser holds all the PCM
 * and a seek is just a re-anchoring of the playback clock -- no reconnect.
 */

const STATUS_TEXT = {
    1: "no track with that sha256",
    2: "malformed request",
    3: "the track could not be decoded",
};
const HEADER_SIZE = 8;

function concatBytes(a, b) {
    if (a.length === 0) return b;
    if (b.length === 0) return a;
    const out = new Uint8Array(a.length + b.length);
    out.set(a, 0);
    out.set(b, a.length);
    return out;
}

class PcmStreamPlayer extends EventTarget {
    constructor(bridgeUrl) {
        super();
        this.bridgeUrl = bridgeUrl;

        this.audioCtx = null;
        this.gainNode = null;
        this.ws = null;

        this.sha256 = null;
        this.channels = 0;
        this.rate = 0;

        // Received PCM, kept as frame-aligned segments so any already-buffered
        // position can be rebuilt into an AudioBuffer on demand.
        this.segments = [];
        this.leftover = new Uint8Array(0);
        this.totalFrames = 0;
        this.fullyBuffered = false;

        this.sources = new Set();
        this.playing = false;
        this.anchorFrame = 0;   // song frame the current playback run began at
        this.anchorTime = 0;    // audioCtx.currentTime when that run began
        this.scheduledFrame = 0; // next frame not yet handed to a source
        this.pausedFrame = 0;

        this._phase = "idle";           // idle | handshake | pcm
        this._handshake = new Uint8Array(0);
        this._volume = 1;
        this._endedFired = false;

        this._tick = this._tick.bind(this);
        requestAnimationFrame(this._tick);
    }

    // --- HTMLAudioElement-like surface ------------------------------------

    get duration() {
        return this.rate ? this.totalFrames / this.rate : 0;
    }

    get currentTime() {
        return this.rate ? this._currentFrame() / this.rate : 0;
    }

    set currentTime(seconds) {
        if (!this.rate) return;
        this.seekToFrame(Math.round(seconds * this.rate));
    }

    get paused() {
        return !this.playing;
    }

    get volume() {
        return this._volume;
    }

    set volume(level) {
        this._volume = Math.max(0, Math.min(1, Number(level) || 0));
        if (this.gainNode) this.gainNode.gain.value = this._volume;
        this.dispatchEvent(new Event("volumechange"));
    }

    /** 2 once the stream header has arrived, mirroring HAVE_CURRENT_DATA. */
    get readyState() {
        return this.rate ? 2 : 0;
    }

    play() {
        if (!this.sha256) return Promise.resolve();

        // Resuming at the very end replays from the start, matching how the
        // dashboard's play button behaves on a finished track.
        const from = this.pausedFrame >= this.totalFrames && this.fullyBuffered
            ? 0
            : this.pausedFrame;

        if (this.audioCtx && this.audioCtx.state === "suspended") {
            this.audioCtx.resume();
        }
        if (this.rate) {
            this._playFrom(from);
            this.dispatchEvent(new Event("play"));
        } else {
            // Header has not arrived yet; _startPlayback runs on arrival.
            this.playing = true;
        }
        return Promise.resolve();
    }

    pause() {
        if (!this.playing) return;
        this.pausedFrame = this._currentFrame();
        this.playing = false;
        this._stopSources();
        this.dispatchEvent(new Event("pause"));
    }

    // --- Stream control ---------------------------------------------------

    /**
     * Connect to the bridge and request `sha256`.
     *
     * Must be called from a user gesture: creating an AudioContext outside one
     * leaves it suspended under the browser's autoplay policy.
     */
    loadTrack(sha256) {
        if (!/^[0-9a-fA-F]{64}$/.test(sha256 || "")) {
            this._fail(`"${sha256}" is not a sha256 digest`);
            return;
        }

        this.stop();
        this.sha256 = sha256;
        this._endedFired = false;

        this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        this.gainNode = this.audioCtx.createGain();
        this.gainNode.gain.value = this._volume;
        this.gainNode.connect(this.audioCtx.destination);

        const ws = new WebSocket(this.bridgeUrl);
        ws.binaryType = "arraybuffer";
        this.ws = ws;
        this._phase = "handshake";
        this._handshake = new Uint8Array(0);

        ws.onopen = () => {
            const digest = new TextEncoder().encode(sha256.toLowerCase());
            const frame = new Uint8Array(2 + digest.length);
            new DataView(frame.buffer).setUint16(0, digest.length, false);
            frame.set(digest, 2);
            ws.send(frame);
        };

        ws.onmessage = (event) => this._onBytes(new Uint8Array(event.data));

        ws.onclose = () => {
            // A clean close means the whole song has been delivered. Keep the
            // buffer so the listener can still seek, pause and replay from it.
            if (this.rate) {
                this.fullyBuffered = true;
                this.dispatchEvent(new Event("canplaythrough"));
            }
        };

        ws.onerror = () => this._fail("cannot reach the stream bridge");
    }

    /** Tear down the connection and audio graph, discarding the buffer. */
    stop() {
        if (this.ws) {
            this.ws.onopen = this.ws.onmessage = this.ws.onclose = this.ws.onerror = null;
            try { this.ws.close(); } catch (e) { /* already closing */ }
            this.ws = null;
        }
        this._stopSources();
        if (this.audioCtx) {
            try { this.audioCtx.close(); } catch (e) { /* already closed */ }
            this.audioCtx = null;
            this.gainNode = null;
        }

        this.sha256 = null;
        this.channels = this.rate = 0;
        this.segments = [];
        this.leftover = new Uint8Array(0);
        this.totalFrames = 0;
        this.fullyBuffered = false;
        this.playing = false;
        this.anchorFrame = this.anchorTime = 0;
        this.scheduledFrame = this.pausedFrame = 0;
        this._phase = "idle";
        this._handshake = new Uint8Array(0);
    }

    seekToFrame(frame) {
        if (!this.rate) return;
        const target = Math.max(0, Math.min(frame, this.totalFrames));
        if (this.playing) {
            this._playFrom(target);
        } else {
            this.pausedFrame = target;
        }
        this.dispatchEvent(new Event("timeupdate"));
    }

    // --- Protocol ---------------------------------------------------------

    _onBytes(chunk) {
        if (this._phase === "handshake") {
            this._handshake = concatBytes(this._handshake, chunk);
            this._parseHandshake();
        } else if (this._phase === "pcm") {
            this._appendPcm(chunk);
        }
    }

    _parseHandshake() {
        const buf = this._handshake;
        if (buf.length < 1) return;

        const status = buf[0];
        if (status !== 0) {
            this._fail(STATUS_TEXT[status] || `unknown status ${status}`);
            return;
        }
        if (buf.length < 1 + HEADER_SIZE) return; // wait for the whole header

        const view = new DataView(buf.buffer, buf.byteOffset + 1, HEADER_SIZE);
        this.channels = view.getUint32(0, false);
        this.rate = view.getUint32(4, false);
        this.bytesPerFrame = 2 * this.channels;

        const rest = buf.subarray(1 + HEADER_SIZE);
        this._handshake = new Uint8Array(0);
        this._phase = "pcm";

        this.dispatchEvent(new Event("loadedmetadata"));
        this._playFrom(0);
        this.dispatchEvent(new Event("play"));

        if (rest.length) this._appendPcm(rest);
    }

    // Keep only whole frames: a frame split across two WebSocket messages must
    // not be cut mid-sample.
    _appendPcm(chunk) {
        const data = concatBytes(this.leftover, chunk);
        const frameCount = Math.floor(data.length / this.bytesPerFrame);
        const usableBytes = frameCount * this.bytesPerFrame;
        // Copy rather than retain a view into `chunk`.
        this.leftover = data.slice(usableBytes);
        if (frameCount === 0) return;

        this.segments.push({
            start: this.totalFrames,
            frames: frameCount,
            data: data.slice(0, usableBytes),
        });
        this.totalFrames += frameCount;
        if (this.playing) this._pump();
    }

    // --- Playback ---------------------------------------------------------

    // Decode frames [f0, f1) across the retained segments into one AudioBuffer,
    // de-interleaving PCM ([ch0,ch1,ch0,ch1,...]) into one array per channel.
    _buildBuffer(f0, f1) {
        const n = f1 - f0;
        const buffer = this.audioCtx.createBuffer(this.channels, n, this.rate);
        const outs = [];
        for (let ch = 0; ch < this.channels; ch++) outs.push(buffer.getChannelData(ch));

        for (const seg of this.segments) {
            const segEnd = seg.start + seg.frames;
            if (segEnd <= f0 || seg.start >= f1) continue; // no overlap
            const from = Math.max(f0, seg.start);
            const to = Math.min(f1, segEnd);
            const view = new DataView(seg.data.buffer, seg.data.byteOffset, seg.data.byteLength);
            for (let frame = from; frame < to; frame++) {
                const local = frame - seg.start;
                const out = frame - f0;
                if (out >= n) continue;
                for (let ch = 0; ch < this.channels; ch++) {
                    outs[ch][out] = view.getInt16((local * this.channels + ch) * 2, true) / 32768;
                }
            }
        }
        return buffer;
    }

    // Schedule everything received but not yet scheduled, as one source placed
    // on the timeline so it lines up seamlessly with what is already playing.
    _pump() {
        if (!this.playing || this.scheduledFrame >= this.totalFrames) return;
        const f0 = this.scheduledFrame;
        const f1 = this.totalFrames;

        let startAt = this.anchorTime + (f0 - this.anchorFrame) / this.rate;
        if (startAt < this.audioCtx.currentTime) {
            // Fell behind the clock (an underrun); re-anchor so the reported
            // position stays true.
            this.anchorFrame = f0;
            this.anchorTime = this.audioCtx.currentTime;
            startAt = this.audioCtx.currentTime;
        }

        const source = this.audioCtx.createBufferSource();
        source.buffer = this._buildBuffer(f0, f1);
        source.connect(this.gainNode);
        source.onended = () => { this.sources.delete(source); source.disconnect(); };
        source.start(startAt);
        this.sources.add(source);
        this.scheduledFrame = f1;
    }

    _stopSources() {
        for (const source of this.sources) {
            source.onended = null;
            try { source.stop(); } catch (e) { /* not started */ }
            source.disconnect();
        }
        this.sources.clear();
    }

    /** (Re)start playback at `frame` -- the heart of play, resume and seek. */
    _playFrom(frame) {
        const target = Math.max(0, Math.min(frame, this.totalFrames));
        this._stopSources();
        this.anchorFrame = target;
        this.anchorTime = this.audioCtx.currentTime;
        this.scheduledFrame = target;
        this.playing = true;
        this._endedFired = false;
        this._pump();
    }

    _currentFrame() {
        if (!this.playing) return this.pausedFrame;
        const frame = this.anchorFrame
            + (this.audioCtx.currentTime - this.anchorTime) * this.rate;
        return Math.max(0, Math.min(Math.round(frame), this.totalFrames));
    }

    _fail(message) {
        this.dispatchEvent(new CustomEvent("error", { detail: message }));
        this.stop();
    }

    // Drive timeupdate from the audio clock, the same way an <audio> element does.
    _tick() {
        if (this.rate && this.playing) {
            this.dispatchEvent(new Event("timeupdate"));

            if (this.fullyBuffered && this._currentFrame() >= this.totalFrames) {
                this.pausedFrame = this.totalFrames;
                this.playing = false;
                this._stopSources();
                if (!this._endedFired) {
                    this._endedFired = true;
                    this.dispatchEvent(new Event("ended"));
                }
            }
        }
        requestAnimationFrame(this._tick);
    }
}

window.PcmStreamPlayer = PcmStreamPlayer;
