"""
Единая система аутентификации
Объединяет: config, exceptions, hasher, interfaces, memory_repository, models, token_service, auth
"""

import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple
import threading
import sqlite3
import bcrypt
import jwt


# ИСКЛЮЧЕНИЯ

class AuthError(Exception):
    """Базовое исключение для ошибок аутентификации"""
    pass


class UserNotFound(AuthError):
    """Пользователь не найден"""
    pass


class InvalidPassword(AuthError):
    """Неверный пароль"""
    pass


class AccountLocked(AuthError):
    """Аккаунт заблокирован"""
    pass


class RateLimitExceeded(AuthError):
    """Превышен лимит запросов"""
    pass


class PermissionDenied(AuthError):
    """Недостаточно прав"""
    pass


class PasswordValidation(AuthError):
    """Пароль не соответствует требованиям"""
    pass


# КОНФИГУРАЦИЯ

@dataclass
class AuthConfig:
    """Настройки системы аутентификации"""

    # Bcrypt
    bcrypt_rounds: int = 12

    # Rate limiting
    rate_limit_window: int = 60  # секунд
    rate_limit_max: int = 5  # запросов за окно

    # Требования к паролю
    admin_min_length: int = 8
    user_min_length: int = 6
    special_chars: str = "!@#$%^&*"

    # Блокировка
    max_attempts: int = 3
    lockout_minutes: int = 5

    # JWT
    jwt_secret: str = "сменить в проде"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440  # 24 часа

    # Разное
    time_offset: int = 3  # часов для last_login


# МОДЕЛИ ДАННЫХ

@dataclass
class User:
    """Модель пользователя"""
    username: str
    password_hash: str
    is_admin: bool
    failed_attempts: int = 0
    locked_until: int = 0
    need_change_password: bool = False

    def is_locked(self) -> bool:
        """Проверяет, заблокирован ли пользователь"""
        return self.locked_until > int(time.time())

    def remaining_lockout_minutes(self) -> int:
        """Возвращает оставшееся время блокировки в минутах"""
        if not self.is_locked():
            return 0
        return int((self.locked_until - int(time.time())) / 60)


# ИНТЕРФЕЙСЫ


class UserRepository(ABC):
    """Абстрактный интерфейс для хранилища пользователей"""

    @abstractmethod
    def get_user(self, username: str) -> Optional[Dict[str, Any]]:
        """
        Получить пользователя по имени.
        Возвращает: hash, is_admin, failed, locked_until, need_change
        """
        pass

    @abstractmethod
    def update_user(self, username: str, **fields) -> None:
        """Обновить поля пользователя"""
        pass

    @abstractmethod
    def create_user(
            self,
            username: str,
            password_hash: str,
            is_admin: bool) -> None:
        """Создать нового пользователя"""
        pass

    @abstractmethod
    def all_users(self) -> List[str]:
        """Получить список всех имён пользователей"""
        pass


# ХЕШИРОВАНИЕ ПАРОЛЕЙ (BCRYPT)

class BcryptHasher:
    """Хеширование и проверка паролей с помощью bcrypt"""

    def __init__(self, config: AuthConfig = None):
        self.rounds = (config or AuthConfig()).bcrypt_rounds

    def hash_password(self, password: str) -> Dict[str, str]:
        """Хеширует пароль"""
        return {
            'hash': bcrypt.hashpw(
                password.encode(),
                bcrypt.gensalt(rounds=self.rounds)
            ).decode()
        }

    def verify_password(self, password: str, stored_hash: str) -> bool:
        """Проверяет пароль на соответствие хешу"""
        return bcrypt.checkpw(password.encode(), stored_hash.encode())


# JWT ТОКЕНЫ

class TokenService:
    """Создание и проверка JWT токенов"""

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
        """Создать JWT токен"""
        payload = {
            "sub": username,
            "is_admin": is_admin,
            "exp": datetime.utcnow() + timedelta(minutes=self.expire_minutes),
            "iat": datetime.utcnow()
        }
        return jwt.encode(payload, self.secret, algorithm=self.algorithm)

    def verify(self, token: str) -> Optional[dict]:
        """Проверить и декодировать JWT токен"""
        try:
            return jwt.decode(token, self.secret, algorithms=[self.algorithm])
        except Exception:
            return None


# ОСНОВНАЯ СИСТЕМА АУТЕНТИФИКАЦИИ

class AuthSystem:
    """Основная система аутентификации"""

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
        """Проверяет лимит запросов от IP-адреса"""
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
        """Загружает пользователя из репозитория в кеш"""
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
            need_change_password=bool(data.get('need_change', False))
        )
        self._cache[username] = user
        return user

    def _save_user(self, user: User) -> None:
        """Сохраняет пользователя в репозиторий"""
        self.repo.update_user(
            user.username,
            hash=user.password_hash,
            is_admin=user.is_admin,
            failed=user.failed_attempts,
            locked_until=user.locked_until,
            need_change=user.need_change_password
        )

    def _invalidate_cache(self, username: str) -> None:
        """Инвалидирует кеш для пользователя"""
        self._cache.pop(username, None)

    def refresh_user(self, username: str) -> Optional[User]:
        """Принудительно обновляет пользователя из БД, инвалидируя кэш"""
        self._invalidate_cache(username)
        return self._load_user(username)

    # Валидация пароля

    def _validate_password(self, password: str, is_admin: bool) -> None:
        """Проверяет пароль на соответствие требованиям"""
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
        """Проверяет, что пароль не содержит логин"""
        if username.lower() in password.lower():
            raise PasswordValidation("Пароль не должен содержать логин")

    # Основные методы
    def authenticate(
            self,
            username: str,
            password: str,
            client_ip: str = None
    ) -> Tuple[User, str]:
        """Аутентификация пользователя"""
        if client_ip:
            self.check_rate_limit(client_ip)

        user = self._load_user(username)
        if not user:
            raise UserNotFound("Неверный логин или пароль")

        # Проверка блокировки
        now = int(time.time())
        if user.locked_until > now:
            rem = int((user.locked_until - now) / 60)
            raise AccountLocked(f"Аккаунт заблокирован. Осталось ~{rem} мин.")
        elif user.locked_until:
            # Разблокировка по истечении времени
            user.failed_attempts = 0
            user.locked_until = 0

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

        # Успешный вход - сброс счетчиков
        user.failed_attempts = 0
        user.locked_until = 0

        # Обновляем last_login (с обработкой ошибок)
        try:
            self.repo.update_user(
                username,
                last_login=int(time.time() + self.config.time_offset * 3600)
            )
        except Exception:
            # Игнорируем ошибку, если колонки last_login нет в БД
            pass

        # Сохраняем изменения (только один раз)
        self._save_user(user)

        if user.need_change_password:
            return user, "Требуется смена пароля при первом входе"

        return user, "Успешный вход"

    def change_password(self, user: User, new_password: str) -> None:
        """Смена пароля пользователем"""
        self._validate_password(new_password, user.is_admin)
        self._check_password_contains_username(new_password, user.username)

        hashed = self.hasher.hash_password(new_password)
        user.password_hash = hashed['hash']
        user.need_change_password = False
        self._save_user(user)
        # Инвалидируем кэш, чтобы при следующем запросе загрузить актуальные
        # данные
        self._invalidate_cache(user.username)

    def create_token(self, user: User) -> str:
        """Создаёт JWT для пользователя"""
        if not self.token_service:
            raise RuntimeError(
                "TokenService не настроен. Передайте token_service в конструктор.")
        return self.token_service.create(user.username, user.is_admin)

    def verify_token(self, token: str) -> Optional[dict]:
        """Проверяет JWT токен"""
        if not self.token_service:
            raise RuntimeError("TokenService не настроен")
        return self.token_service.verify(token)

    def get_user_from_token(self, token: str) -> Optional[User]:
        """Получает пользователя из JWT токена"""
        payload = self.verify_token(token)
        if not payload:
            return None
        username = payload.get("sub")
        if not username:
            return None
        return self._load_user(username)

    # Административные методы

    def reset_user_password(
            self,
            admin_user: User,
            target_username: str,
            new_password: str
    ) -> None:
        """Сброс пароля пользователя администратором"""
        if not admin_user.is_admin:
            raise PermissionDenied("Недостаточно прав для сброса пароля")

        target = self._load_user(target_username)
        if not target:
            raise UserNotFound(f"Пользователь {target_username} не найден")

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
            lock: bool
    ) -> None:
        """Блокировка/разблокировка пользователя администратором"""
        if not admin_user.is_admin:
            raise PermissionDenied("Недостаточно прав")

        target = self._load_user(target_username)
        if not target:
            raise UserNotFound(f"Пользователь {target_username} не найден")

        if lock:
            target.locked_until = int(time.time()) + 365 * 24 * 3600  # на год
        else:
            target.locked_until = 0
            target.failed_attempts = 0

        self._save_user(target)
        self._invalidate_cache(target_username)

    def create_admin_if_empty(self) -> bool:
        """Создаёт администратора по умолчанию, если нет пользователей"""
        if not self.repo.all_users():
            hashed = self.hasher.hash_password("Admin@12345")
            self.repo.create_user("admin", hashed['hash'], True)
            print("Создан тестовый аккаунт: admin / Admin@12345")
            return True
        return False


class SQLiteUserRepository(UserRepository):
    """
    Постоянное хранилище пользователей на SQLite.
    Потокобезопасно через threading.Lock.
    """

    _CREATE_SQL = """
        CREATE TABLE IF NOT EXISTS users (
            username     TEXT    PRIMARY KEY,
            hash         TEXT    NOT NULL,
            is_admin     INTEGER NOT NULL DEFAULT 0,
            failed       INTEGER NOT NULL DEFAULT 0,
            locked_until INTEGER NOT NULL DEFAULT 0,
            need_change  INTEGER NOT NULL DEFAULT 0,
            last_login   INTEGER NOT NULL DEFAULT 0
        )
    """

    def __init__(self, db_path: str = "gtu_auth.db") -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.execute(self._CREATE_SQL)
            self._migrate_schema(conn)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        """Добавляет отсутствующие колонки в таблицу users"""
        cursor = conn.execute("PRAGMA table_info(users)")
        existing_columns = [col[1] for col in cursor.fetchall()]

        # Проверяем наличие всех необходимых колонок
        required_columns = ['last_login']
        for col in required_columns:
            if col not in existing_columns:
                conn.execute(
                    f"ALTER TABLE users ADD COLUMN {col} INTEGER NOT NULL DEFAULT 0")
                print(f"Добавлена колонка {col} в таблицу users")

    def get_user(self, username: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            with self._connect() as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.execute(
                    "SELECT * FROM users WHERE username = ?", (username,)
                )
                row = cur.fetchone()
        return dict(row) if row else None

    def update_user(self, username: str, **fields) -> None:
        allowed = {
            "hash",
            "is_admin",
            "failed",
            "locked_until",
            "need_change",
            "last_login"}
        filtered = {k: v for k, v in fields.items() if k in allowed}
        if not filtered:
            return

        # Проверяем существование колонок перед обновлением
        with self._lock:
            with self._connect() as conn:
                # Получаем список существующих колонок
                cursor = conn.execute("PRAGMA table_info(users)")
                existing_columns = [col[1] for col in cursor.fetchall()]

                # Фильтруем только существующие колонки
                filtered = {
                    k: v for k,
                    v in filtered.items() if k in existing_columns}
                if not filtered:
                    return

                set_clause = ", ".join(f"{k} = ?" for k in filtered)
                values = list(filtered.values()) + [username]
                conn.execute(
                    f"UPDATE users SET {set_clause} WHERE username = ?", values
                )

    def create_user(
            self,
            username: str,
            password_hash: str,
            is_admin: bool) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO users (username, hash, is_admin) VALUES (?, ?, ?)",
                    (username, password_hash, int(is_admin)),
                )

    def all_users(self) -> List[str]:
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute("SELECT username FROM users")
                return [row[0] for row in cur.fetchall()]
