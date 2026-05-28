PASS_TEMPERATURES = {
    1: 0.7,   # Pass 1 — Structure Humanizer: balanced rewrites
    2: 0.8,   # Pass 2 — Tone + Imperfection: creative variation
    3: 0.3,   # Pass 3 — Final Polish: conservative edits
}


def get_pass_temperature(pass_number: int) -> float:
    return PASS_TEMPERATURES.get(pass_number, 0.7)
