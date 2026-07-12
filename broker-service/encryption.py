import os

from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()

_fernet = Fernet(os.getenv("BROKER_ENCRYPTION_KEY", "").encode())


def decrypt_secret(ciphertext: str) -> str:
    return _fernet.decrypt(ciphertext.encode()).decode()
