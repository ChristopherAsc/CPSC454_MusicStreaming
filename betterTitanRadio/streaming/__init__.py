"""Raw-PCM audio streaming, integrated with the Django track library.

A TCP server (``server.py``) decodes tracks to raw PCM with ffmpeg and streams
them to connecting clients. Clients identify a track by its **sha256**, which
the server looks up in the ``Track`` table -- so the wire protocol never carries
a file name or a path.

The browser reaches the TCP server through the WebSocket bridge in
``bridge.py``. Both are started by the ``runstreamserver`` management command.
"""
