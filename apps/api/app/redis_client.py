"""Redis connection management.

A single connection pool is created per process from REDIS_URL. Phase 1 only
uses Redis for the health check; queue/cache consumers added in later phases
should reuse this client rather than opening their own pool.
"""
import redis

from app.config import get_settings

settings = get_settings()

redis_client = redis.Redis.from_url(
    settings.redis_url, socket_connect_timeout=2, socket_timeout=2
)
