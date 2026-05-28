import os

_skill_cache = None
SKILL_RELATIVE_PATH = "BackEnd/SKILL.md"


def _resolve_skill_path() -> str:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        parent = os.path.dirname(current_dir)
        candidate = os.path.join(parent, SKILL_RELATIVE_PATH)
        if os.path.isfile(candidate):
            return candidate
        current_dir = parent
    return os.path.join(current_dir, SKILL_RELATIVE_PATH)


def load_skill() -> str:
    global _skill_cache
    path = _resolve_skill_path()
    try:
        with open(path, "r") as f:
            _skill_cache = f.read()
        return _skill_cache
    except FileNotFoundError:
        return ""


def get_skill_content() -> str:
    if _skill_cache is None:
        return load_skill()
    return _skill_cache


def reload_skill() -> str:
    global _skill_cache
    _skill_cache = None
    return load_skill()
