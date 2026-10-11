"""Read literal local settings without printing secrets or interpolating variables."""
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def setting(name, default=''):
    if name in os.environ:
        return os.environ[name].strip()
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            match = re.fullmatch(r'\s*' + re.escape(name) + r'\s*=\s*(.*?)\s*', line)
            if match:
                value = match[1]
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                return value.strip()
    return default
