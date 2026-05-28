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
}

PLAN_LIMITS = {
    "free": {"words_per_month": 1000, "words_per_request": 500, "modes": ["standard"]},
    "starter": {"words_per_month": 15000, "words_per_request": 1500, "modes": ["standard"]},
    "creator": {"words_per_month": 75000, "words_per_request": 3000, "modes": ["standard", "academic", "casual"]},
    "pro": {"words_per_month": 250000, "words_per_request": 3000, "modes": ["standard", "academic", "casual", "turbo"]},
    "unlimited": {"words_per_month": -1, "words_per_request": 3000, "modes": ["standard", "academic", "casual", "turbo"]},
}

ANON_LIMITS = {
    "max_words": 500,
    "max_requests_per_session": 1,
}
