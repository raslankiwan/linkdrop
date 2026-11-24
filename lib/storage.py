"""Keep display filenames out of Blob's signed object paths."""
import re
import uuid
from pathlib import Path

def storage_path(filename):
    suffix=Path(filename).suffix.lower()
    if not re.fullmatch(r'\.[a-z0-9]{1,10}',suffix): suffix='.bin'
    return f'downloads/{uuid.uuid4().hex}/media{suffix}'

def named_path(filename):
    """Blob key that keeps a readable ASCII name, used for converted files."""
    suffix=storage_path(filename).rsplit('/',1)[1][len('media'):]
    compound=re.search(r'\.tar\.(gz|bz2|xz)$',filename.lower())
    stem=Path(filename).name[:-len(compound.group(0))] if compound else Path(filename).stem
    if compound: suffix=compound.group(0)
    slug=re.sub(r'[^A-Za-z0-9._-]+','-',stem).strip('-._')[:80] or 'file'
    return f'downloads/{uuid.uuid4().hex}/{slug}{suffix}'
