import os
import re
import unicodedata
from pathlib import Path
from typing import Tuple

NAME_RE = re.compile(r"^((\d{4})-\d{2}-\d{2})_(\d+)_(.+)$")


def sanitize_filename(name: str) -> str:
    name = os.path.basename(name or "")
    name = "".join(c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c))
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return name or "attachment.pdf"


def scan_output(out_path: Path) -> Tuple[dict, set]:
    max_seq: dict = {}
    identities: set = set()
    if not out_path.is_dir():
        return max_seq, identities
    for entry in out_path.iterdir():
        match = NAME_RE.match(entry.name)
        if not match:
            continue
        date_str, year, seq, name_part = match.groups()
        year, seq = int(year), int(seq)
        if seq > max_seq.get(year, 0):
            max_seq[year] = seq
        identities.add((date_str, name_part))
    return max_seq, identities
