import subprocess
import threading

import ffmpeg


class AudioEncoder:
    """Decodes an audio file to raw PCM via ffmpeg, exposing the result as a readable stream.

    Reads its input from a file **object**, not a path. Django's FileField may
    be backed by local disk or by S3, and only local storage exposes a usable
    path -- but every backend yields a readable file object. Feeding ffmpeg
    through stdin (which it already did) makes the two cases identical.

    The caller supplies channels/rate because it has already probed the source
    to build the protocol header; passing them through as the output format
    keeps the PCM matching what the client was told to expect.
    """

    CHUNK_SIZE = 64 * 1024

    def __init__(self, output_format='s16le', codec='pcm_s16le'):
        self._output_format = output_format
        self._codec = codec
        self._source = None
        self._process = None
        self._feed_thread = None
        self._stop_event = threading.Event()
        self.channels = None
        self.rate = None

    def open(self, source, channels, rate):
        """Start decoding `source` and return the readable PCM stream.

        Takes ownership of `source`: close() closes it.
        """
        self._source = source
        self.channels = channels
        self.rate = rate

        stream_spec = (
            ffmpeg
            .input('pipe:')
            .output(
                'pipe:',
                format=self._output_format,
                acodec=self._codec,
                ac=channels,
                ar=rate,
            )
            # ffmpeg writes to stderr, which is inherited by our process. Left
            # at its defaults every instance dumps a build banner and a running
            # progress line, burying the program's own output -- and with one
            # ffmpeg per client that noise multiplies. Keep real errors only.
            .global_args('-hide_banner', '-loglevel', 'error', '-nostats')
        )
        args = ffmpeg.compile(stream_spec)
        # Run ffmpeg in its own process group so a terminal signal (e.g.
        # Ctrl-C) only reaches us, not the ffmpeg child too -- we terminate
        # it ourselves in close(). Otherwise both processes receive the raw
        # signal directly and ffmpeg's own signal handling (which force-exits
        # after a few repeated signals) fights with ours.
        self._process = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            start_new_session=True,
        )

        self._stop_event.clear()
        self._feed_thread = threading.Thread(target=self._feed_stdin, daemon=True)
        self._feed_thread.start()

        return self._process.stdout

    def _feed_stdin(self):
        # Feed ffmpeg's stdin on a separate thread so writing input and reading
        # decoded output happen concurrently instead of one blocking the other.
        try:
            while not self._stop_event.is_set():
                chunk = self._source.read(self.CHUNK_SIZE)
                if not chunk:
                    break
                self._process.stdin.write(chunk)
        except (BrokenPipeError, ValueError, OSError):
            pass
        finally:
            # This thread owns stdin; close it here (guarded, since a final
            # flush to a dead ffmpeg raises BrokenPipeError) so the main thread
            # never has to touch the BufferedWriter this thread may be blocked
            # inside -- that cross-thread close is exactly what used to deadlock.
            try:
                self._process.stdin.close()
            except (BrokenPipeError, ValueError, OSError):
                pass

    def close(self):
        """Stop encoding (even mid-stream) and release the ffmpeg process and source.

        Teardown order matters -- do NOT reorder these steps:
          1. ffmpeg process -- kill first; this collapses the pipes and frees
             the feed thread, so nothing else is still blocked on them.
          2. feed thread    -- join only after ffmpeg is dead; it closes its
             own stdin as it unwinds (never closed from here -- see below).
          3. stdout pipe    -- safe to close once no thread is reading it.
          4. source object  -- last; nothing else depends on it anymore.
        """
        self._stop_event.set()

        # 1. Kill ffmpeg FIRST. This tears down both pipes at the kernel level,
        #    so a feed thread blocked writing to a full stdin pipe is unblocked
        #    (BrokenPipeError) and releases the stdin buffer lock, instead of
        #    deadlocking against a close() from this thread.
        if self._process is not None:
            if self._process.poll() is None:
                self._process.kill()
            self._process.wait()

        # 2. Now that ffmpeg is dead the feed thread falls out of its write and
        #    closes stdin itself; wait for it before releasing anything else.
        if self._feed_thread is not None:
            self._feed_thread.join(timeout=1)
            self._feed_thread = None

        # 3. stdout is no longer being read, so it is safe to close here.
        if self._process is not None:
            if self._process.stdout and not self._process.stdout.closed:
                self._process.stdout.close()
            self._process = None

        # 4. Close the source last.
        if self._source is not None:
            try:
                self._source.close()
            except (ValueError, OSError):
                pass
            self._source = None
