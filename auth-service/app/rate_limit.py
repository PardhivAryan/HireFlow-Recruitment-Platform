from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from redis import Redis
from redis.exceptions import RedisError

from app.config import settings


redis_client = Redis.from_url(
    settings.redis_url.get_secret_value(),
    decode_responses=True,
    socket_connect_timeout=2,
    socket_timeout=2,
)


def get_redis() -> Redis:
    return redis_client


RedisClient = Annotated[Redis, Depends(get_redis)]


def check_rate_limit(request: Request, redis: Redis, action: str, limit: int) -> None:
    # Read the direct peer address, never a client-supplied forwarding header.
    identifier = request.client.host if request.client is not None else "unknown"
    key = f"{settings.auth_rate_limit_prefix}:{action}:{identifier}"
    try:
        # MULTI/EXEC keeps increment and expiration together. NX sets the TTL only
        # when absent, so later attempts do not extend the current window.
        with redis.pipeline(transaction=True) as pipe:
            pipe.incr(key)
            pipe.expire(key, settings.auth_rate_limit_window_seconds, nx=True)
            pipe.ttl(key)
            attempts, _, remaining = pipe.execute()
    except RedisError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication rate limiting is temporarily unavailable",
        ) from None

    if attempts > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests; try again later",
            headers={"Retry-After": str(max(1, remaining))},
        )


def limit_login(request: Request, redis: RedisClient) -> None:
    check_rate_limit(request, redis, "login", settings.auth_login_rate_limit)


def limit_registration(request: Request, redis: RedisClient) -> None:
    check_rate_limit(request, redis, "register", settings.auth_register_rate_limit)
