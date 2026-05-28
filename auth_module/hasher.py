import bcrypt

from .config import AuthConfig


from typing import Dict


class BcryptHasher:
    """Хеширование и проверка """

    def __init__(self, config: AuthConfig = None):
        self.rounds = (config or AuthConfig()).bcrypt_rounds

    def hash_password(self, password: str) -> Dict[str, str]:

        return {
            'hash': bcrypt.hashpw(
                password.encode(),
                bcrypt.gensalt(rounds=self.rounds)
            ).decode()
        }

    def verify_password(self, password: str, stored_hash: str) -> bool:
        return bcrypt.checkpw(password.encode(), stored_hash.encode())
