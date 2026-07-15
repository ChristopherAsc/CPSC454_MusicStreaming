import threading

import ffmpeg
import pyaudio

FILE_INPUT = 'club_music.ogg'

with open(FILE_INPUT, 'rb') as f:
    flac_bytes = f.read()

probe = ffmpeg.probe('retro.flac')
audio_info = next(s for s in probe['streams'] if s['codec_type'] == 'audio')
channels = int(audio_info['channels'])
rate = int(audio_info['sample_rate'])

process = (
    ffmpeg
    .input('pipe:')
    .output('pipe:', format='s16le', acodec='pcm_s16le', ac=channels, ar=rate)
    .run_async(pipe_stdin=True, pipe_stdout=True)
)

# Feed ffmpeg's stdin on a separate thread so writing input and reading
# decoded output happen concurrently instead of one blocking the other.
def feed_stdin():
    process.stdin.write(flac_bytes)
    process.stdin.close()

threading.Thread(target=feed_stdin, daemon=True).start()

p = pyaudio.PyAudio()
stream = p.open(format=pyaudio.paInt16, channels=channels, rate=rate, output=True)

chunk_size = 1024 * channels * 2  # 1024 frames of 16-bit samples
while True:
    data = process.stdout.read(chunk_size)
    if not data:
        break
    stream.write(data)

stream.stop_stream()
stream.close()
p.terminate()
process.wait()

