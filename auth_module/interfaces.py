"""Абстрактные интерфейсы для зависимостей."""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List


class UserRepository(ABC):
    """абстрактно под бдшку"""

    @abstractmethod
    def get_user(self, username: str) -> Optional[Dict[str, Any]]:
        """
        юзер по имени

        hash, is_admin, failed, locked_until, need_change или none если не найден """
        pass

    @abstractmethod
    def update_user(self, username: str, **fields) -> None:
        """Обновить поля пользователя."""
        pass

    @abstractmethod
    def create_user(
            self,
            username: str,
            password_hash: str,
            is_admin: bool) -> None:
        """Создать нового пользователя."""
        pass

    @abstractmethod
    def all_users(self) -> List[str]:
        """Получить список всех имен пользователей."""
        pass
