"""Keep display filenames out of Blob's signed object paths."""
import re
import uuid
from pathlib import Path

def storage_path(filename):
    suffix=Path(filename).suffix.lower()
    if not re.fullmatch(r'\.[a-z0-9]{1,10}',suffix): suffix='.bin'
    return f'downloads/{uuid.uuid4().hex}/media{suffix}'
