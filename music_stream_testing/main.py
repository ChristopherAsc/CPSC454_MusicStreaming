import signal
import threading

import pyaudio

from encoder import AudioEncoder

shutdown_event = threading.Event()


def handle_shutdown_signal(signum, frame):
    shutdown_event.set()


signal.signal(signal.SIGINT, handle_shutdown_signal)
signal.signal(signal.SIGTERM, handle_shutdown_signal)

FILE_INPUT = 'club_music.ogg'

encoder = AudioEncoder()
pcm_stream = encoder.open(FILE_INPUT)


def read_callback(in_data, frame_count, time_info, status):
    try:
        data = pcm_stream.read(frame_count * encoder.channels * 2)
    except (ValueError, OSError):
        # Stream was closed underneath us during shutdown; end cleanly.
        return (None, pyaudio.paComplete)
    if not data:
        return (None, pyaudio.paComplete)
    return (data, pyaudio.paContinue)


p = pyaudio.PyAudio()
stream = p.open(
    format=pyaudio.paInt16,
    channels=encoder.channels,
    rate=encoder.rate,
    output=True,
    stream_callback=read_callback,
)

# Playback itself runs on PyAudio's own thread via the callback above, so the
# main thread only ever blocks in short, reliably signal-interruptible waits
# instead of a long blocking read/write call that might not hand control back
# to the interpreter promptly when a signal arrives.
stream.start_stream()
try:
    while stream.is_active() and not shutdown_event.is_set():
        shutdown_event.wait(timeout=0.1)
finally:
    # Teardown order matters -- do NOT reorder:
    #   1. encoder  -- close first; this kills ffmpeg. If the PyAudio callback
    #      is blocked in pcm_stream.read() on a live-but-stalled ffmpeg,
    #      stopping the stream first would wait forever for that callback to
    #      return. Killing ffmpeg makes the read hit EOF so the callback ends.
    #   2. stream    -- only now safe to stop (guarded: an aborted stream can
    #      raise) and close.
    #   3. PyAudio   -- terminate last, after its stream is gone.
    encoder.close()
    try:
        stream.stop_stream()
    except (ValueError, OSError):
        pass
    stream.close()
    p.terminate()

