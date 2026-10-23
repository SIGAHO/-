"""UTF-8 at the process boundary, including inherited CP932 redirected streams."""
import sys


def configure_stdio():
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')


def clean_input(text):
    if not isinstance(text, str):
        raise ValueError('input must be a string')
    # Replace lone surrogates, preserving valid Japanese, emoji and replacement characters.
    return text.encode('utf-8', errors='replace').decode('utf-8')
