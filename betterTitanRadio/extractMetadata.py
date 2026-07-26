# this file is going to extract the metadata from mp3 files using tiny tag. It's mostly just going to test if this works and can get pushed to the s3 bucket

import os
import django
import sys 

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cpsc454proj.settings')
django.setup()

from tinytag import TinyTag
from django.core.files.base import File
from django.core.files.storage import default_storage

path = "betterTitanRadio\data\music\FIDLAR - Gimmie Something.mp3"

data = TinyTag.get(path)



print(f"this is the song path:{path} and this is the metadata, hopefully: {data.as_dict()}")

with open(path, 'rb') as f:
    default_storage.save('songs/FIDLAR - Gimmie Something.mp3', File(f) )
