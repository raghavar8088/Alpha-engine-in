"""The per-request user, resolved once per process instead of once per request.

This is a single-user local app: `get_current_user` has always returned the same
auto-provisioned document, and FastAPI calls it as a dependency on nearly every endpoint.
That meant a `find_one` against Atlas before any endpoint did its own work — a round trip
on the critical path of every uncached request in the application, to fetch a document
that cannot change.

Cached for the life of the process. The invalidation story is simple because there is
nothing to invalidate: one user, created once, never edited by this app. `reset_user_cache`
exists so a test or a future multi-user path can drop it explicitly rather than needing a
restart.
"""

from app.core.db import users_collection

LOCAL_USER_EMAIL = "local@tradingai.dev"

_cached_user: dict | None = None


def reset_user_cache() -> None:
    """Forget the cached user. For tests, and for anything that edits the row."""
    global _cached_user
    _cached_user = None


async def get_current_user() -> dict:
    """Single-user local app: no login, every request acts as this one auto-provisioned user."""
    global _cached_user
    if _cached_user is not None:
        return _cached_user

    user = await users_collection.find_one({"email": LOCAL_USER_EMAIL})
    if user is None:
        await users_collection.update_one(
            {"email": LOCAL_USER_EMAIL},
            {"$setOnInsert": {"email": LOCAL_USER_EMAIL, "is_active": True}},
            upsert=True,
        )
        user = await users_collection.find_one({"email": LOCAL_USER_EMAIL})
    _cached_user = user
    return user
