"""для тестов"""

from typing import Optional, Dict, Any, List

from .interfaces import UserRepository


class InMemoryUserRepository(UserRepository):


    def __init__(self):
        self._users: Dict[str, Dict[str, Any]] = {}

    def get_user(self, username: str) -> Optional[Dict[str, Any]]:
        user = self._users.get(username)
        if not user:
            return None
        return user.copy()

    def update_user(self, username: str, **fields) -> None:
        if username in self._users:
            self._users[username].update(fields)

    def create_user(self, username: str, password_hash: str, is_admin: bool) -> None:
        self._users[username] = {
            'hash': password_hash,
            'is_admin': is_admin,
            'failed': 0,
            'locked_until': 0,
            'need_change': False
        }

    def all_users(self) -> List[str]:
        return list(self._users.keys())