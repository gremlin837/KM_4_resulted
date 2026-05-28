"""
Заглушки сервисов

Интерфейсы фиксированы для последующей интеграции.
"""

# ── Logger ────────────────────────────────────────────────────────────────────

class LoggerStub:
    """Заглушка логгера. Пишет в stdout; заменяется реальным модулем."""

    def info(self, message: str, **kwargs) -> None:
        print(f"[INFO]  {message}")

    def warning(self, message: str, **kwargs) -> None:
        print(f"[WARN]  {message}")

    def error(self, message: str, **kwargs) -> None:
        print(f"[ERROR] {message}")

    def debug(self, message: str, **kwargs) -> None:
        pass  # в заглушке debug подавляется


# ── AuditService ──────────────────────────────────────────────────────────────

class AuditServiceStub:
    """
    Заглушка аудита.
    Ожидаемый интерфейс для реальной реализации:
      log_event(user_id, action, details) -> None
    """

    def log_event(self, user_id: int, action: str, details: str = "") -> None:
        """Заглушка: событие аудита игнорируется."""
        pass


# ── Singleton-экземпляры (заменяются при интеграции реальных модулей) ─────────

logger: LoggerStub = LoggerStub()
audit_service: AuditServiceStub = AuditServiceStub()