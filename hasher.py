class BcryptHasher:
    """Хеширование паролей"""

    def __init__(self):
        self.rounds = config.bcrypt_rounds

    def hash_password(self, pwd: str) -> dict:
        return {
            'hash': bcrypt.hashpw(
                pwd.encode(), bcrypt.gensalt(rounds=self.rounds)
            ).decode()
        }

    def verify_password(self, pwd: str, stored: str) -> bool:
        return bcrypt.checkpw(pwd.encode(), stored.encode())
