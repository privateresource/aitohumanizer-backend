ROLE_PERMISSIONS = {
    "superadmin": ["*"],
    "admin": [
        "dashboard:view", "users:read", "users:write", "users:delete",
        "billing:read", "billing:write", "llm:read", "llm:write",
        "plans:read", "plans:write", "system:read", "system:write",
        "invites:create", "words:adjust",
    ],
    "manager": ["dashboard:view", "users:read", "billing:read", "words:adjust"],
    "author": ["dashboard:view"],
    "user": [],
}

ROLE_HIERARCHY = {
    "superadmin": 100,
    "admin": 80,
    "manager": 60,
    "author": 40,
    "user": 20,
}

def has_permission(role: str, permission: str) -> bool:
    if role == "superadmin":
        return True
    return permission in ROLE_PERMISSIONS.get(role, [])

def minimum_role(required: str) -> str:
    return required

def role_ge(role: str, minimum: str) -> bool:
    return ROLE_HIERARCHY.get(role, 0) >= ROLE_HIERARCHY.get(minimum, 0)
