import re

def validate_youtube_url(url: str) -> bool:
    """
    Validate that the URL is a proper YouTube URL
    
    :param url: URL to validate
    :return: True if valid, False otherwise
    """
    patterns = [
        r'^(https?:\/\/)?(www\.)?(youtube\.com|youtu\.?be)\/.+$',
        r'^(https?:\/\/)?(www\.)?youtube\.com\/watch\?v=[\w-]+',
        r'^(https?:\/\/)?(www\.)?youtu\.be\/[\w-]+'
    ]
    
    return any(re.match(pattern, url) for pattern in patterns)
