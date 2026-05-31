"""
FastAPI-сервер. REST API для клиентской части.

Эндпоинты:
  POST /api/auth/login            — аутентификация, возврат JWT
  POST /api/auth/change-password  — смена пароля
  GET  /api/status                — текущее состояние ГТУ       [требует токен]
  GET  /api/history               — история из БД               [требует токен]
  GET  /health                    — проверка работоспособности
"""

from contextlib import asynccontextmanager
from typing import Optional
import re

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import socket

from orchestrator import Orchestrator
from auth_system_united import (
    AuthSystem, AuthConfig,
    BcryptHasher, TokenService,
    SQLiteUserRepository,
    User,
    UserNotFound, InvalidPassword, AccountLocked,
    RateLimitExceeded, PasswordValidation, PermissionDenied,
)

# ИЗМЕНЕНО: импорт реальных сервисов вместо stubs
from logging_service import get_logging_service, LogLevel, LogCategory
from audit_service import get_audit_service, AuditEventType, AuditSeverity

# ИЗМЕНЕНО: создание экземпляров
_logger = get_logging_service().get_logger("server")
_audit = get_audit_service()


def _validate_new_password(password: str, is_admin: bool, config: AuthConfig) -> None:
    """Валидация пароля по правилам AuthConfig (вынесена из AuthSystem)."""
    min_len = config.admin_min_length if is_admin else config.user_min_length
    if len(password) < min_len:
        raise PasswordValidation(f"Минимальная длина: {min_len}")
    if not re.search(r'[A-Z]', password):
        raise PasswordValidation("Нужна хотя бы одна заглавная буква")
    if not re.search(r'[a-z]', password):
        raise PasswordValidation("Нужна хотя бы одна строчная буква")
    if not re.search(r'[0-9]', password):
        raise PasswordValidation("Нужна хотя бы одна цифра")
    pattern = rf'[{re.escape(config.special_chars)}]'
    if not re.search(pattern, password):
        raise PasswordValidation(f"Нужен хотя бы один спецсимвол ({config.special_chars})")


# Инициализация AuthSystem

def _build_auth_system() -> AuthSystem:
    config = AuthConfig(
        jwt_secret="ЗАМЕНИТЕ_В_ПРОДЕ_НА_СЛУЧАЙНУЮ_СТРОКУ",
        bcrypt_rounds=12,
    )
    repo = SQLiteUserRepository("gtu_auth.db")
    hasher = BcryptHasher(config)
    token_svc = TokenService(config.jwt_secret, config.jwt_algorithm, config.jwt_expire_minutes)
    system = AuthSystem(repo, hasher, token_svc, config)
    system.create_admin_if_empty()   # создаёт admin/Admin@12345 при первом запуске
    return system


_auth_system  = _build_auth_system()
_orchestrator = Orchestrator(poll_interval=1.0, auto_cycle=True)


# Lifespan

@asynccontextmanager
async def lifespan(app: FastAPI):
    _orchestrator.start()
    _logger.info("Сервер запущен")          # ИЗМЕНЕНО
    yield
    _orchestrator.stop()
    _logger.info("Сервер завершает работу") # ИЗМЕНЕНО


# Приложение

app = FastAPI(
    title="GTU Monitoring Server",
    description="Сервер мониторинга ГТУ (КМ №4)",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# Pydantic-схемы

class LoginRequest(BaseModel):
    login: str
    password: str

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


# Зависимость: текущий пользователь

def get_current_user(authorization: Optional[str] = Header(default=None)) -> User:
    """
    Извлекает Bearer-токен, верифицирует JWT, возвращает объект User.
    Выбрасывает HTTP 401 при невалидном/отсутствующем токене.
    """
    if not authorization or not authorization.startswith("Bearer "):
        # ИЗМЕНЕНО: логируем попытку несанкционированного доступа
        _audit.log_unauthorized_access(
            username="unknown",
            resource="API",
            ip_address=None
        )
        raise HTTPException(status_code=401, detail="Требуется токен авторизации")
    token = authorization.split(" ", 1)[1]
    user = _auth_system.get_user_from_token(token)
    if not user:
        _audit.log_unauthorized_access(
            username="unknown",
            resource="API",
            ip_address=None
        )
        raise HTTPException(status_code=401, detail="Токен недействителен или истёк")
    return user


def get_admin_user(current_user: User = Depends(get_current_user)) -> User:
    """Расширение зависимости: только для администраторов."""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    return current_user


# Эндпоинты аутентификации

@app.post("/api/auth/login", summary="Аутентификация, получение JWT")
def login(body: LoginRequest, request: Request):
    """
    Принимает логин/пароль, возвращает JWT-токен.
    Учитывает блокировку аккаунта, счётчик неудачных попыток и rate limit по IP.
    """
    client_ip = request.client.host if request.client else "unknown"
    try:
        user, message = _auth_system.authenticate(body.login, body.password, client_ip)
        token = _auth_system.create_token(user)
        # ИЗМЕНЕНО: аудит успешного входа
        _audit.log_login_success(username=user.username, ip_address=client_ip)
        return {
            "token": token,
            "message": message,
            "need_change_password": user.need_change_password,
            "is_admin": user.is_admin,
        }
    except RateLimitExceeded as e:
        # ИЗМЕНЕНО: логируем превышение лимита
        _audit.log_event(
            event_type=AuditEventType.RATE_LIMIT_EXCEEDED,
            username=body.login,
            description=f"Rate limit exceeded for IP {client_ip}",
            severity=AuditSeverity.MEDIUM,
            ip_address=client_ip
        )
        raise HTTPException(status_code=429, detail=str(e))
    except AccountLocked as e:
        _audit.log_login_failed(username=body.login, reason="Account locked", ip_address=client_ip)
        raise HTTPException(status_code=423, detail=str(e))
    except (UserNotFound, InvalidPassword) as e:
        _audit.log_login_failed(username=body.login, reason="Invalid credentials", ip_address=client_ip)
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")


@app.post("/api/auth/change-password", summary="Смена пароля")
def change_password(body: ChangePasswordRequest,
                    current_user: User = Depends(get_current_user)):
    """
    Пользователь меняет собственный пароль.
    Проверяет текущий пароль, затем валидирует и сохраняет новый.
    """
    # Проверяем текущий пароль
    if not _auth_system.hasher.verify_password(body.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Текущий пароль неверен")
    try:
        _auth_system.change_password(current_user, body.new_password)
    except PasswordValidation as e:
        raise HTTPException(status_code=422, detail=str(e))

    # ИЗМЕНЕНО: аудит смены пароля
    _audit.log_password_change(username=current_user.username, changed_by=current_user.username)
    return {"message": "Пароль успешно изменён"}


#  Эндпоинты мониторинга

@app.get("/api/status", summary="Текущее состояние ГТУ")
def get_status(current_user: User = Depends(get_current_user)):
    """Возвращает последние показания датчиков, режим и аномалии."""
    state = _orchestrator.get_current_state()
    if not state["readings"]:
        raise HTTPException(status_code=503, detail="Данные ещё не получены от датчиков")
    # ИЗМЕНЕНО: логируем чтение данных
    _audit.log_event(
        event_type=AuditEventType.DATA_READ,
        username=current_user.username,
        description=f"User {current_user.username} requested current status",
        severity=AuditSeverity.LOW
    )
    return state


@app.get("/api/history", summary="История записей из хранилища")
def get_history(limit: int = 100,
                current_user: User = Depends(get_current_user)):
    """
    Возвращает до `limit` последних записей.
    Формат: Timestamp / Режим / Аномалии / Показания датчиков.
    """
    if not (1 <= limit <= 1000):
        raise HTTPException(status_code=400, detail="limit должен быть от 1 до 1000")
    # ИЗМЕНЕНО: логируем чтение истории
    _audit.log_event(
        event_type=AuditEventType.DATA_READ,
        username=current_user.username,
        description=f"User {current_user.username} requested history (limit={limit})",
        severity=AuditSeverity.LOW
    )
    return _orchestrator.get_history(limit)


@app.get("/api/audit", summary="Получить последние события аудита")
def get_audit_events(
        limit: int = 50,
        current_user: User = Depends(get_current_user)
):
    """Возвращает последние события аудита (требуется авторизация)."""
    if not (1 <= limit <= 200):
        raise HTTPException(status_code=400, detail="limit от 1 до 200")
    from audit_service import get_audit_service
    audit = get_audit_service()

    # Фильтрация: админ видит всё, обычный пользователь — только свои логи
    if current_user.is_admin:
        events = audit.search_events(limit=limit)
    else:
        events = audit.search_events(username=current_user.username, limit=limit)

    result = []
    for ev in events:
        result.append({
            "id": ev.id,
            "timestamp": ev.timestamp,
            "event_type": ev.event_type.value,
            "severity": ev.severity.value,
            "username": ev.username,
            "ip_address": ev.ip_address,
            "description": ev.description,
            "details": ev.details,
        })
    return result

@app.post("/api/admin/create-user", summary="Создание нового пользователя (только админ)")
def create_user(
    username: str,
    password: str,
    admin_user: User = Depends(get_admin_user)
):
    """
    Создаёт обычного пользователя (is_admin=False). Пароль должен удовлетворять требованиям.
    """
    # Проверка, что пользователь не существует
    existing = _auth_system.repo.get_user(username)
    if existing:
        raise HTTPException(status_code=400, detail="Пользователь уже существует")

    # Валидация пароля (используем внутренний метод AuthSystem)
    try:
        # Временно создаём "заглушку" пользователя, чтобы вызвать _validate_password
        # или проще: вызвать статический метод валидации. Создадим отдельную функцию.
        _validate_new_password(password, is_admin=False, config=_auth_system.config)
        hashed = _auth_system.hasher.hash_password(password)
        _auth_system.repo.create_user(username, hashed['hash'], is_admin=False)
        # Логируем действие
        _audit.log_event(
            event_type=AuditEventType.USER_CREATED,
            username=admin_user.username,
            description=f"Администратор {admin_user.username} создал пользователя {username}",
            severity=AuditSeverity.MEDIUM
        )
        return {"message": f"Пользователь {username} успешно создан"}
    except PasswordValidation as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# Проверка работоспособности

@app.get("/health", summary="Проверка работоспособности")
def health():
    return {"status": "ok"}


# Проверка свободного порта
def _get_free_port(preferred: int = 8000) -> int:
    """Возвращает порт если свободен, иначе любой свободный."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("0.0.0.0", preferred))
            return preferred
        except OSError:
            s.bind(("0.0.0.0", 0))
            return s.getsockname()[1]


if __name__ == "__main__":
    port = _get_free_port(8000)
    if port != 8000:
        _logger.warning(f"Порт 8000 занят, используется порт {port}")   # ИЗМЕНЕНО
    _logger.info(f"Сервер запускается на http://0.0.0.0:{port}")        # ИЗМЕНЕНО
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)