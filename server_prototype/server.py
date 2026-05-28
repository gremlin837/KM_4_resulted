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
from stubs import audit_service, logger


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
    logger.info("Сервер запущен")
    yield
    _orchestrator.stop()
    logger.info("Сервер завершает работу")


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
        raise HTTPException(status_code=401, detail="Требуется токен авторизации")
    token = authorization.split(" ", 1)[1]
    user = _auth_system.get_user_from_token(token)
    if not user:
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
        audit_service.log_event(
            user_id=0, action="login",
            details=f"login={body.login} ip={client_ip}"
        )
        return {
            "token": token,
            "message": message,
            "need_change_password": user.need_change_password,
            "is_admin": user.is_admin,
        }
    except RateLimitExceeded as e:
        raise HTTPException(status_code=429, detail=str(e))
    except AccountLocked as e:
        raise HTTPException(status_code=423, detail=str(e))
    except (UserNotFound, InvalidPassword) as e:
        # Единственное сообщение — не раскрываем, что именно неверно
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

    audit_service.log_event(
        user_id=0, action="change_password",
        details=f"user={current_user.username}"
    )
    return {"message": "Пароль успешно изменён"}


#  Эндпоинты мониторинга

@app.get("/api/status", summary="Текущее состояние ГТУ")
def get_status(current_user: User = Depends(get_current_user)):
    """Возвращает последние показания датчиков, режим и аномалии."""
    state = _orchestrator.get_current_state()
    if not state["readings"]:
        raise HTTPException(status_code=503, detail="Данные ещё не получены от датчиков")
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
    return _orchestrator.get_history(limit)


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
        logger.warning(f"Порт 8000 занят, используется порт {port}")
    logger.info(f"Сервер запускается на http://0.0.0.0:{port}")
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)