import threading
from pathlib import Path
from jmcomic import create_option_by_file

OPTION_PATH = Path(__file__).parent.parent / "option.yml"
_option_cache = None
_option_lock = threading.Lock()


def get_option():
    global _option_cache
    if _option_cache is None:
        with _option_lock:
            if _option_cache is None:
                _option_cache = create_option_by_file(str(OPTION_PATH))
    return _option_cache
