import re

PATTERNS = [
    (re.compile(r'(?i)(token["\']?\s*[:=]\s*["\']?)([a-zA-Z0-9_\-\.]{8,})', re.IGNORECASE), r'\1[REDACTED]'),
    (re.compile(r'(?i)(password["\']?\s*[:=]\s*["\']?)([^\s"\']{3,})', re.IGNORECASE), r'\1[REDACTED]'),
    (re.compile(r'(?i)(bearer\s+)([a-zA-Z0-9_\-\.]{8,})', re.IGNORECASE), r'\1[REDACTED]'),
    (re.compile(r'(?i)(api[_-]?key["\']?\s*[:=]\s*["\']?)([a-zA-Z0-9_\-\.]{8,})', re.IGNORECASE), r'\1[REDACTED]'),
    (re.compile(r'(?i)(secret["\']?\s*[:=]\s*["\']?)([a-zA-Z0-9_\-\.]{8,})', re.IGNORECASE), r'\1[REDACTED]'),
]

def redact(text: str) -> str:
    if not text:
        return text
    for pattern, replacement in PATTERNS:
        text = pattern.sub(replacement, text)
    return text
