def format_words(n: int) -> str:
    if n == -1:
        return "Unlimited"
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M words"
    if n >= 1_000:
        return f"{n//1_000}K words"
    return f"{n} words"

def get_word_urgency(remaining: int, total: int):
    if total == -1:
        return {"urgency": "unlimited", "color": "#8b5cf6", "pct": 100}
    if remaining <= 0:
        return {"urgency": "empty", "color": "#ef4444", "pct": 0}
    pct = remaining / total
    if pct <= 0.10:
        return {"urgency": "critical", "color": "#ef4444", "pct": round(pct * 100, 1)}
    if pct <= 0.20:
        return {"urgency": "low", "color": "#f59e0b", "pct": round(pct * 100, 1)}
    return {"urgency": "good", "color": "#10b981", "pct": round(pct * 100, 1)}
