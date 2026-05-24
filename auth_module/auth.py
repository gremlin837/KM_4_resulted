"""Основная система аутентификации."""

import re
import time
from typing import Dict, List, Tuple, Optional

from .config import AuthConfig
from .exceptions import (
    RateLimitExceeded,
    UserNotFound,
    InvalidPassword,
    AccountLocked,
    PasswordValidation,
    PermissionDenied,
)
from .hasher import BcryptHasher
from .interfaces import UserRepository
from .token_service import TokenService
from .models import User


class AuthSystem:

    def __init__(
            self,
            user_repository: UserRepository,
            hasher: BcryptHasher = None,
            token_service: TokenService = None,
            config: AuthConfig = None
    ):
        self.repo = user_repository
        self.hasher = hasher or BcryptHasher(config)
        self.token_service = token_service
        self.config = config or AuthConfig()
        self._rate_limit_store: Dict[str, List[float]] = {}
        self._cache: Dict[str, User] = {}

    # Rate limiting

    def check_rate_limit(self, client_ip: str) -> None:
        """    Проверяет лимит запросов """
        now = time.time()
        window = self.config.rate_limit_window
        max_req = self.config.rate_limit_max

        if client_ip not in self._rate_limit_store:
            self._rate_limit_store[client_ip] = []

        # Очищаем старые записи
        self._rate_limit_store[client_ip] = [
            t for t in self._rate_limit_store[client_ip] if now - t < window
        ]

        if len(self._rate_limit_store[client_ip]) >= max_req:
            raise RateLimitExceeded(
                f"Превышен лимит ({max_req} запросов за {window} сек)"
            )

        self._rate_limit_store[client_ip].append(now)

    # Работа с кешем

    def _load_user(self, username: str) -> Optional[User]:
        """Загружает пользователя из репозитория в кеш."""
        if username in self._cache:
            return self._cache[username]

        data = self.repo.get_user(username)
        if not data:
            return None

        user = User(
            username=username,
            password_hash=data['hash'],
            is_admin=bool(data['is_admin']),
            failed_attempts=data['failed'],
            locked_until=data['locked_until'],
            need_change_password=bool(data['need_change'])
        )
        self._cache[username] = user
        return user

    def _save_user(self, user: User) -> None:
        """Сохраняет пользователя в репозиторий."""
        self.repo.update_user(
            user.username,
            hash=user.password_hash,
            is_admin=user.is_admin,
            failed=user.failed_attempts,
            locked_until=user.locked_until,
            need_change=user.need_change_password
        )

    def _invalidate_cache(self, username: str) -> None:
        """Инвалидирует кеш для пользователя."""
        self._cache.pop(username, None)

    # Валидация пароля

    def _validate_password(self, password: str, is_admin: bool) -> None:
        """        Проверяет пароль на соответствие требованиям """

        min_len = self.config.admin_min_length if is_admin else self.config.user_min_length

        if len(password) < min_len:
            raise PasswordValidation(f"Минимальная длина: {min_len}")

        if not re.search(r'[A-Z]', password):
            raise PasswordValidation("Нужна хотя бы одна заглавная буква")

        if not re.search(r'[a-z]', password):
            raise PasswordValidation("Нужна хотя бы одна строчная буква")

        if not re.search(r'[0-9]', password):
            raise PasswordValidation("Нужна хотя бы одна цифра")

        pattern = rf'[{re.escape(self.config.special_chars)}]'
        if not re.search(pattern, password):
            raise PasswordValidation(
                f"Нужен хотя бы один спецсимвол ({self.config.special_chars})"
            )

    def _check_password_contains_username(
            self, password: str, username: str) -> None:
        """Проверяет, что пароль не содержит логин."""
        if username.lower() in password.lower():
            raise PasswordValidation("Пароль не должен содержать логин")

    # Основные методы

    def authenticate(
            self,
            username: str,
            password: str,
            client_ip: str = None
    ) -> Tuple[User, str]:
        """        Аутентификация пользователя    """

        if client_ip:
            self.check_rate_limit(client_ip)

        user = self._load_user(username)
        if not user:
            raise UserNotFound("Неверный логин или пароль")

        # Проверка блокировки
        now = int(time.time())
        if user.locked_until > now:
            rem = int((user.locked_until - now) / 60)
            raise AccountLocked(
                f"Аккаунт заблокирован. Осталось ~{rem} мин.")
        elif user.locked_until:
            # Разблокировка по истечении времени
            user.failed_attempts = 0
            user.locked_until = 0
            self._save_user(user)

        # Проверка пароля
        if not self.hasher.verify_password(password, user.password_hash):
            user.failed_attempts += 1
            if user.failed_attempts >= self.config.max_attempts:
                user.locked_until = int(
                    time.time() + self.config.lockout_minutes * 60)
                self._save_user(user)
                self._invalidate_cache(username)
                raise AccountLocked(
                    f"Аккаунт заблокирован на {
                        self.config.lockout_minutes} мин.")
            self._save_user(user)
            remaining = self.config.max_attempts - user.failed_attempts
            raise InvalidPassword(
                f"Неверный пароль. Осталось попыток: {remaining}")

        # Успешный вход
        user.failed_attempts = 0
        user.locked_until = 0
        self.repo.update_user(
            username,
            last_login=int(
                time.time() +
                self.config.time_offset *
                3600))
        self._save_user(user)

        if user.need_change_password:
            return user, "Требуется смена пароля при первом входе"

        return user, "Успешный вход"

    def change_password(self, user: User, new_password: str) -> None:
        """     Смена пароля.       """
        self._validate_password(new_password, user.is_admin)
        self._check_password_contains_username(new_password, user.username)

        hashed = self.hasher.hash_password(new_password)
        user.password_hash = hashed['hash']
        user.need_change_password = False
        self._save_user(user)

    def create_token(self, user: User) -> str:
        """Создаёт JWT для пользователя."""
        if not self.token_service:
            raise RuntimeError(
                "TokenService не настроен. Передайте token_service в конструктор.")
        return self.token_service.create(user.username, user.is_admin)

    def verify_token(self, token: str) -> Optional[dict]:
        """Проверяет JWT """
        if not self.token_service:
            raise RuntimeError("TokenService не настроен")
        return self.token_service.verify(token)

    # Административные методы

    def reset_user_password(
            self,
            admin_user: User,
            target_username: str,
            new_password: str
    ) -> None:
        """    Сброс пароля пользователя администратором    """
        if not admin_user.is_admin:
            raise PermissionDenied("Недостаточно прав для сброса пароля")

        target = self._load_user(target_username)
        if not target:
            raise UserNotFound(
                f"Пользователь {target_username} не найден")

        self._validate_password(new_password, target.is_admin)
        self._check_password_contains_username(new_password, target_username)

        hashed = self.hasher.hash_password(new_password)
        target.password_hash = hashed['hash']
        target.need_change_password = True
        self._save_user(target)
        self._invalidate_cache(target_username)

    def set_user_lock(
            self,
            admin_user: User,
            target_username: str,
            lock: bool) -> None:
        """    Блокировка/разблокировка пользователя """
        if not admin_user.is_admin:
            raise PermissionDenied("Недостаточно прав")

        target = self._load_user(target_username)
        if not target:
            raise UserNotFound(
                f"Пользователь {target_username} не найден")

        if lock:
            target.locked_until = int(time.time()) + 365 * 24 * 3600  # на год
        else:
            target.locked_until = 0
            target.failed_attempts = 0

        self._save_user(target)
        self._invalidate_cache(target_username)

    def create_admin_if_empty(self) -> bool:
        """Создаёт администратора по умолчанию, если нет пользователей."""
        if not self.repo.all_users():
            hashed = self.hasher.hash_password("Admin@12345")
            self.repo.create_user("admin", hashed['hash'], True)
            print("Создан тестовый аккаунт: admin / Admin@12345")
            return True
        return False

    def get_user_from_token(self, token: str) -> Optional[User]:
        """Получает пользователя из JWT """
        payload = self.verify_token(token)
        if not payload:
            return None
        username = payload.get("sub")
        if not username:
            return None
        return self._load_user(username)
