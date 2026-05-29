from app.cache.redis_cache import RedisCache
from app.cache.local_cache import LocalCache
from app.core.config import settings

if settings.upstash_redis_url and settings.upstash_redis_token:
    cache = RedisCache()
else:
    cache = LocalCache()
