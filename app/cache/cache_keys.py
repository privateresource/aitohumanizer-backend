ALL_PLANS_KEY       = "plans:all"
PUBLIC_PLANS_KEY    = "plans:public"
PLAN_PREFIX         = "plan:"

ALL_COUPONS_KEY     = "coupons:all"
COUPON_PREFIX       = "coupon:"

SYSTEM_CONFIG_KEY   = "system:config"
LLM_PROVIDERS_KEY   = "llm:providers"
LT_SERVERS_KEY      = "languagetool:servers"

def plan_key(slug: str) -> str:
    return f"plan:{slug}"

def tool_limits_key(slug: str) -> str:
    return f"plan:{slug}:tools"

def plan_features_key(slug: str) -> str:
    return f"plan:{slug}:features"

def coupon_key(code: str) -> str:
    return f"coupon:{code.upper()}"
