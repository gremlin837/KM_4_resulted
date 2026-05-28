from dataclasses import dataclass


@dataclass
class AuthConfig:
    """Настройки системы аутентификации."""

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

