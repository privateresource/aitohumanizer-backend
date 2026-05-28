import os

_file_cache: dict[str, str] = {}
_BASE_PATH = os.path.dirname(os.path.abspath(__file__))


def _read_file(path: str) -> str:
    if path not in _file_cache:
        with open(path, "r") as f:
            _file_cache[path] = f.read().strip()
    return _file_cache[path]


def build_system_prompt(_mode: str = "standard") -> str:
    return _read_file(os.path.join(_BASE_PATH, "base.md"))


def build_paraphraser_prompt(mode: str = "standard") -> str:
    base = _read_file(os.path.join(_BASE_PATH, "paraphraser_base.md"))
    mode_file = os.path.join(_BASE_PATH, "modes", f"paraphrase_{mode}.md")
    try:
        mode_instruction = _read_file(mode_file)
    except FileNotFoundError:
        mode_instruction = _read_file(os.path.join(_BASE_PATH, "modes", "paraphrase_standard.md"))
    return f"{base}\n\n{mode_instruction}"


def build_pass_system_prompt(pass_number: int) -> str:
    return _read_file(os.path.join(_BASE_PATH, f"pass{pass_number}_system.md"))


def build_pass_user_prompt(pass_number: int, input_text: str) -> str:
    template = _read_file(os.path.join(_BASE_PATH, f"pass{pass_number}_user.md"))
    return template.replace("{input_text}", input_text)


def build_pass2_user_prompt(input_text: str, style_instruction: str) -> str:
    template = _read_file(os.path.join(_BASE_PATH, "pass2_user.md"))
    return template.replace("{style_instruction}", style_instruction).replace("{input_text}", input_text)


def reload_prompt_cache():
    _file_cache.clear()
