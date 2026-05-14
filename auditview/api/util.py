import os


def safe_path(root_path, rel_path):
    """Return resolved absolute path if rel_path stays within root_path, else None."""
    root = os.path.realpath(root_path)
    target = os.path.realpath(os.path.join(root_path, rel_path))
    if target != root and not target.startswith(root + os.sep):
        return None
    return target
