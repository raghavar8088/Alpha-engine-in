"""Store Angel One credentials, encrypted, in the shared broker_credentials collection.

Interactive by design. Pasting a multi-line shell block that contains `read` prompts
does not work in a browser SSH terminal — the pasted lines get consumed as answers to
the prompts instead of running as commands — and putting secrets in a one-line command
leaves them in shell history and the process list. Prompting from inside a single
already-running process avoids both problems: the command line carries no secrets, and
the prompts only start once the command is fully entered.

    docker exec -it alpha-engine-backend-1 python /app/store_angel_credentials.py

Values come from the SmartAPI developer portal / your Angel One login:
    api_key       SmartAPI app's API key
    client_id     Angel One client code (e.g. R12345678)
    PIN           the login PIN (called `password` in some config dumps)
    totp_secret   the TOTP seed used to generate 2FA codes

The TOTP seed is a permanent second factor — treat it like a password. It is written
encrypted with the app's BROKER_ENCRYPTION_KEY, the same Fernet scheme used for the Dhan
token, and is never logged or echoed.

Nothing else in this repo reads angel_one_config.py; that file is gitignored and stays
on whatever machine it lives on.
"""

import os
import sys
from getpass import getpass


def main() -> int:
    try:
        import pymongo
        from cryptography.fernet import Fernet
    except ImportError as exc:
        print(f"missing dependency: {exc}")
        return 1

    key = os.environ.get("BROKER_ENCRYPTION_KEY")
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("MONGO_DB_NAME", "tradingai")
    if not key or not mongo_url:
        print("BROKER_ENCRYPTION_KEY and MONGO_URL must be set (run this inside the "
              "backend container, which already has them)")
        return 1

    print("Angel One standby-feed credentials (input is hidden; Ctrl-C to abort)\n")
    client_id = input("  client_id  : ").strip()
    api_key = getpass("  api_key    : ").strip()
    pin = getpass("  PIN        : ").strip()
    totp = getpass("  totp_secret: ").strip()

    missing = [n for n, v in
               (("client_id", client_id), ("api_key", api_key), ("PIN", pin),
                ("totp_secret", totp)) if not v]
    if missing:
        print(f"\naborted — empty value(s): {', '.join(missing)}")
        return 1

    # Fail before writing if the seed is unusable, rather than storing something that
    # only breaks later at login time when the desk actually needs the standby.
    try:
        import base64

        base64.b32decode(totp.upper() + "=" * ((8 - len(totp) % 8) % 8))
    except Exception:
        print("\naborted — totp_secret is not valid base32; check for typos/spaces")
        return 1

    f = Fernet(key.encode())
    db = pymongo.MongoClient(mongo_url)[db_name]
    db["broker_credentials"].replace_one(
        {"broker": "angelone"},
        {
            "broker": "angelone",
            "client_id": client_id,
            "api_key_encrypted": f.encrypt(api_key.encode()).decode(),
            "pin_encrypted": f.encrypt(pin.encode()).decode(),
            "totp_secret_encrypted": f.encrypt(totp.encode()).decode(),
        },
        upsert=True,
    )
    doc = db["broker_credentials"].find_one({"broker": "angelone"})
    print(f"\nstored for client {doc['client_id']} — "
          f"{len([k for k in doc if k.endswith('_encrypted')])} fields encrypted")
    print("the selling desk will pick up the standby feed on its next start")
    return 0


if __name__ == "__main__":
    sys.exit(main())
