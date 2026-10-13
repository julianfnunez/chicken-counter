"""Load bundled, non-secret defaults without overriding container environment."""
import os
from pathlib import Path
import shlex

def load_defaults(path):
    for raw in Path(path).read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, value = line.split("=", 1)
        parts = shlex.split(value, comments=True)
        os.environ.setdefault(key.strip(), " ".join(parts))

if __name__ == "__main__":
    import sys
    load_defaults("/app/.env")
    os.execvp(sys.argv[1], sys.argv[1:])
