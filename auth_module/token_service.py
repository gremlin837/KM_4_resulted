from datetime import datetime, timedelta
from typing import Optional

import jwt


class TokenService:
    """Создание и проверка JWT """

    def __init__(
            self,
            secret: str,
            algorithm: str = "HS256",
            expire_minutes: int = 1440
    ):
        self.secret = secret
        self.algorithm = algorithm
        self.expire_minutes = expire_minutes

    def create(self, username: str, is_admin: bool) -> str:
        """Создать JWT токен."""
        payload = {
            "sub": username,
            "is_admin": is_admin,
            "exp": datetime.utcnow() + timedelta(minutes=self.expire_minutes),
            "iat": datetime.utcnow()
        }
        return jwt.encode(payload, self.secret, algorithm=self.algorithm)

    def verify(self, token: str) -> Optional[dict]:
        """ Проверить токен"""
        try:
            return jwt.decode(token, self.secret, algorithms=[self.algorithm])
        except Exception:
            return None
