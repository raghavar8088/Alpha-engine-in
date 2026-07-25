"""Backend Angel One client — now a thin wrapper over the shared `tradingai-broker-clients`
package, so backend, prelive-service and market-data-service all use ONE Angel
implementation instead of three drifting copies.

Kept as a module (rather than importing the package at every call site) so existing
imports keep working unchanged:

    from app.services.angel_client import angel_client, AngelAPIError

The backend resolves credentials from its pydantic settings (its `.env` is loaded by
BaseSettings, which `AngelCredentials.from_env()` reading `os.environ` would not see), so
it builds the credentials explicitly and hands them to the shared client. Everything else
— session/login, batched LTP/FULL quotes, candles — lives in the package.

Angel One is a market-DATA standby only; orders stay on Dhan.
"""

from tradingai_broker_clients.angel import AngelAPIError, AngelClient, AngelCredentials

from app.core.config import settings

__all__ = ["angel_client", "AngelClient", "AngelCredentials", "AngelAPIError"]

angel_client = AngelClient(
    AngelCredentials(
        api_key=settings.angelone_api_key,
        client_code=settings.angelone_client_code,
        pin=settings.angelone_pin,
        totp_secret=settings.angelone_totp_secret,
        public_ip=settings.angelone_public_ip,
        base_url=settings.angelone_base_url,
    )
)
