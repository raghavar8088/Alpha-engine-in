import sys
import pyotp
sys.path.insert(0, r"d:\INDIAN MARKET")

from angel_one_config import ANGEL_ONE_CONFIG
from SmartApi import SmartConnect

cfg = ANGEL_ONE_CONFIG

# Validate credentials are filled in
missing = [k for k in ("api_key", "client_id", "password", "totp_secret") if not cfg.get(k)]
if missing:
    print(f"[ERROR] Missing credentials in angel_one_config.py: {missing}")
    sys.exit(1)

print("Connecting to Angel One SmartAPI...")

obj = SmartConnect(api_key=cfg["api_key"])

totp = pyotp.TOTP(cfg["totp_secret"]).now()
print(f"Generated TOTP: {totp}")

data = obj.generateSession(cfg["client_id"], cfg["password"], totp)

if data["status"]:
    print("\n✓ Login successful!")
    print(f"  Client ID  : {cfg['client_id']}")
    refresh_token = data["data"]["refreshToken"]
    profile = obj.getProfile(refresh_token)
    if profile["status"]:
        p = profile["data"]
        print(f"  Name       : {p.get('name')}")
        print(f"  Email      : {p.get('email')}")
        print(f"  Exchanges  : {p.get('exchanges')}")
        print(f"  Products   : {p.get('products')}")
    print("\nFeed token :", obj.getfeedToken())
else:
    print(f"\n[ERROR] Login failed: {data.get('message')}")
