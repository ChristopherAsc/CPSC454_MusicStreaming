"""Template context shared by every page."""

from django.conf import settings


def streaming(request):
    """Expose the WebSocket bridge URL to templates.

    The player has to be told where the bridge is, and that address differs
    between a laptop and the EC2 host. Passing it through settings keeps the
    deployment detail out of the JavaScript.
    """
    return {'stream_bridge_url': settings.STREAM_BRIDGE_URL}
