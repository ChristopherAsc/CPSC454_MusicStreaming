import io
import wave

import ffmpeg
import pyaudio

with open('retro.flac', 'rb') as f:
    flac_bytes = f.read()

wav_bytes, _ = (
    ffmpeg
    .input('pipe:')
    .output('pipe:', format='wav')
    .run(input=flac_bytes, capture_stdout=True)
)

with wave.open(io.BytesIO(wav_bytes)) as wf:
    p = pyaudio.PyAudio()
    stream = p.open(
        format=p.get_format_from_width(wf.getsampwidth()),
        channels=wf.getnchannels(),
        rate=wf.getframerate(),
        output=True,
    )

    chunk = 1024
    data = wf.readframes(chunk)
    while data:
        stream.write(data)
        data = wf.readframes(chunk)

    stream.stop_stream()
    stream.close()
    p.terminate()

