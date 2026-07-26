# this file is going to extract the metadata from mp3 files using tiny tag. It's mostly just going to test if this works and can get pushed to the s3 bucket



from tinytag import TinyTag
path = "betterTitanRadio\data\music\FIDLAR - Gimmie Something.mp3"

data = TinyTag.get(path)



print(f"this is the song path:{path} and this is the metadata, hopefully: {data.as_dict()}")


