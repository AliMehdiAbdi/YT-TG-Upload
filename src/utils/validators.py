import os
from typing import Optional, Tuple


def validate_cookies_path(path: str) -> Tuple[bool, Optional[str]]:
    """
    Validate a Netscape-format cookies file path.
    
    :param path: User-supplied path
    :return: (ok, error_message). error_message is None when ok.
    """
    if not path or not path.strip():
        return True, None

    path = path.strip().strip('"').strip("'")

    if not os.path.exists(path):
        return False, f"Cookie file not found: {path}"

    if not os.path.isfile(path):
        return False, f"Cookie path is not a file: {path}"

    if not os.access(path, os.R_OK):
        return False, f"Cookie file is not readable: {path}"

    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            head = f.read(512)
    except OSError as e:
        return False, f"Could not read cookie file: {e}"

    if not head.strip():
        return False, "Cookie file is empty"

    # Netscape cookies typically start with a comment or a tab-separated domain line
    first_line = head.splitlines()[0].strip() if head.splitlines() else ''
    looks_netscape = (
        first_line.startswith('#')
        or first_line.startswith('.')
        or '\t' in first_line
    )
    if not looks_netscape:
        return False, (
            "Cookie file does not look like Netscape format "
            "(expected # Netscape header or tab-separated lines)"
        )

    return True, None
