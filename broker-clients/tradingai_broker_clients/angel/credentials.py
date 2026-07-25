"""Angel One credential resolution — one convention (`ANGELONE_*`) for every service.

Previously the backend read pydantic `angelone_*` settings while prelive-service read a
different set of names (`ANGEL_API_KEY` etc.) OR an encrypted Mongo `broker_credentials`
doc. That's two naming schemes and two storage mechanisms to keep in sync for one account.
Angel's TOTP re-login is cheap and stateless (unlike Dhan's one-token-per-account rule),
so env-var-only resolution is sufficient everywhere and the Mongo-encrypted path is retired.
"""

import os
from dataclasses import dataclass

DEFAULT_BASE_URL = "https://apiconnect.angelone.in"


@dataclass(frozen=True)
class AngelCredentials:
    api_key: str = ""
    client_code: str = ""
    pin: str = ""
    totp_secret: str = ""
    # Angel enforces IP whitelisting: the public IP header must match a registered host
    # (the AWS box). Off-whitelist (local dev) login simply fails — that's expected.
    public_ip: str = ""
    base_url: str = DEFAULT_BASE_URL

    def configured(self) -> bool:
        return bool(self.api_key and self.client_code and self.pin and self.totp_secret)

    @classmethod
    def from_env(cls) -> "AngelCredentials":
        return cls(
            api_key=os.getenv("ANGELONE_API_KEY", ""),
            client_code=os.getenv("ANGELONE_CLIENT_CODE", ""),
            pin=os.getenv("ANGELONE_PIN", ""),
            totp_secret=os.getenv("ANGELONE_TOTP_SECRET", ""),
            public_ip=os.getenv("ANGELONE_PUBLIC_IP", ""),
            base_url=os.getenv("ANGELONE_BASE_URL", DEFAULT_BASE_URL),
        )
