from app.core.db import users_collection

LOCAL_USER_EMAIL = "local@tradingai.dev"


async def get_current_user() -> dict:
    """Single-user local app: no login, every request acts as this one auto-provisioned user."""
    user = await users_collection.find_one({"email": LOCAL_USER_EMAIL})
    if user is None:
        await users_collection.update_one(
            {"email": LOCAL_USER_EMAIL},
            {"$setOnInsert": {"email": LOCAL_USER_EMAIL, "is_active": True}},
            upsert=True,
        )
        user = await users_collection.find_one({"email": LOCAL_USER_EMAIL})
    return user
