"""Mount the human review app without importing or invoking any model code."""
import importlib.util
import os
import threading
from pathlib import Path
_MODULE_PATH = Path(os.environ.get("BREAKTAIL_REVIEW_MODULE", Path(__file__).with_name("breaktail_review.py")))
_app = None
_lock = threading.Lock()
def handle_review(handler):
    global _app
    if handler.path.split('?',1)[0] != '/review' and not handler.path.startswith('/review/'):
        return False
    with _lock:
        if _app is None:
            spec = importlib.util.spec_from_file_location('breaktail_human_review', _MODULE_PATH)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            _app = module.ReviewApp()
    return _app.handle(handler)
