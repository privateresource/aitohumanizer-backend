import os

_base_path = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(_base_path, "base.md")) as f:
    SYSTEM_PROMPT = f.read()
