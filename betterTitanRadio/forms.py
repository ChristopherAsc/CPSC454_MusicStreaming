from pathlib import Path

from django import forms


ALLOWED_AUDIO_EXTENSIONS = {
    ".mp3",
}


class TrackUploadForm(forms.Form):
    file = forms.FileField()

    def clean_file(self):
        uploaded = self.cleaned_data["file"]
        extension = Path(uploaded.name).suffix.lower()

        if extension not in ALLOWED_AUDIO_EXTENSIONS:
            raise forms.ValidationError(
                "Unsupported audio format."
            )

        return uploaded