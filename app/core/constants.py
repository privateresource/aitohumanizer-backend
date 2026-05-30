ROLE_HIERARCHY = {
    "superadmin": 100,
    "admin": 80,
    "manager": 60,
    "author": 40,
    "user": 20,
}

WORD_COSTS = {
    "standard": 1,
    "academic": 1,
    "casual": 1,
    "turbo": 1,
    "creative": 1,
    "professional": 1,
    "fluency": 1,
    "formal": 1,
    "shorten": 1,
    "expand": 1,
}

PLAN_LIMITS = {
    "guest": {"words_per_month": 500, "words_per_request": 500, "modes": ["standard"]},
    "free": {"words_per_month": 1000, "words_per_request": 500, "modes": ["standard"]},
    "starter": {"words_per_month": 10000, "words_per_request": 1500, "modes": ["standard"]},
    "creator": {"words_per_month": 30000, "words_per_request": 3000, "modes": ["standard", "academic", "casual", "creative", "professional"]},
    "pro": {"words_per_month": 250000, "words_per_request": 3000, "modes": ["standard", "academic", "casual", "creative", "professional", "turbo"]},
    "unlimited": {"words_per_month": -1, "words_per_request": 3000, "modes": ["standard", "academic", "casual", "creative", "professional", "turbo"]},
}

ANON_LIMITS = {
    "max_words": 500,
    "max_requests_per_session": 1,
}
