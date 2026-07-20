from django.shortcuts import render


def home(request):
    tracks = [
        {
            'title': 'Titan Nights',
            'artist': 'Campus Radio',
            'source': 'Andrew/Music/Campus',
            'format': 'MP3',
            'size': '8.4 MB',
            'duration': '3:42',
            'status': 'Ready',
            'accent': '#ef476f',
        },
        {
            'title': 'Study Session',
            'artist': 'Lo-Fi Department',
            'source': 'Shared/Study',
            'format': 'WAV',
            'size': '24.1 MB',
            'duration': '2:58',
            'status': 'Ready',
            'accent': '#06d6a0',
        },
        {
            'title': 'Late Lab',
            'artist': 'Debug Mode',
            'source': 'Cameron/Uploads',
            'format': 'MP3',
            'size': '9.7 MB',
            'duration': '4:16',
            'status': 'Encoding',
            'accent': '#ffd166',
        },
        {
            'title': 'Cloud City',
            'artist': 'CPSC 454',
            'source': 'AWS/Music',
            'format': 'FLAC',
            'size': '31.8 MB',
            'duration': '3:25',
            'status': 'Ready',
            'accent': '#118ab2',
        },
    ]

    metrics = [
        {'label': 'Stream latency', 'value': '42 ms', 'trend': 'Local demo target'},
        {'label': 'Buffering time', 'value': '0.8 s', 'trend': 'Last playback'},
        {'label': 'Library size', 'value': '4 tracks', 'trend': 'Demo database'},
        {'label': 'Server status', 'value': 'Online', 'trend': 'Django dev server'},
    ]

    upload_queue = [
        {'name': 'weekend-drive.mp3', 'state': 'Queued'},
        {'name': 'lecture-break.wav', 'state': 'Scanning'},
        {'name': 'titan-radio-id.mp3', 'state': 'Uploaded'},
    ]

    return render(
        request,
        'music/home.html',
        {
            'tracks': tracks,
            'metrics': metrics,
            'upload_queue': upload_queue,
        },
    )
