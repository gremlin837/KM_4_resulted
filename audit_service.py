import json
import sqlite3
import hashlib
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path
from contextlib import contextmanager


class AuditEventType(Enum):
    # Аутентификация и авторизация
    LOGIN_SUCCESS = "LOGIN_SUCCESS"
    LOGIN_FAILED = "LOGIN_FAILED"
    LOGOUT = "LOGOUT"
    PASSWORD_CHANGE = "PASSWORD_CHANGE"
    PASSWORD_RESET = "PASSWORD_RESET"
    ACCOUNT_LOCKED = "ACCOUNT_LOCKED"
    ACCOUNT_UNLOCKED = "ACCOUNT_UNLOCKED"
    
    # Операции с данными
    DATA_READ = "DATA_READ"
    DATA_WRITE = "DATA_WRITE"
    DATA_DELETE = "DATA_DELETE"
    CONFIG_CHANGE = "CONFIG_CHANGE"
    
    # Критические события ГТУ
    MODE_CHANGED = "MODE_CHANGED"
    ANOMALY_DETECTED = "ANOMALY_DETECTED"
    EMERGENCY_MODE = "EMERGENCY_MODE"
    SYSTEM_SHUTDOWN = "SYSTEM_SHUTDOWN"
    SYSTEM_STARTUP = "SYSTEM_STARTUP"
    
    # Административные действия
    USER_CREATED = "USER_CREATED"
    USER_DELETED = "USER_DELETED"
    PERMISSION_CHANGED = "PERMISSION_CHANGED"
    
    # Безопасность
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    UNAUTHORIZED_ACCESS = "UNAUTHORIZED_ACCESS"
    SUSPICIOUS_ACTIVITY = "SUSPICIOUS_ACTIVITY"


class AuditSeverity(Enum):
    LOW = "LOW"                 # Информационные события
    MEDIUM = "MEDIUM"           # Важные события
    HIGH = "HIGH"               # Критические события
    CRITICAL = "CRITICAL"       # Требуют немедленного внимания


@dataclass
class AuditEvent:
    event_type: AuditEventType
    severity: AuditSeverity
    username: str
    description: str
    ip_address: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    id: Optional[int] = None
    timestamp: Optional[str] = None
    checksum: Optional[str] = None
    
    def __post_init__(self):    # Автоматическая установка timestamp при создании
        if self.timestamp is None:
            self.timestamp = datetime.utcnow().isoformat()


class AuditStorage:    # Абстракция хранилища событий аудита
    def save(self, event: AuditEvent) -> int:
        raise NotImplementedError
    
    def get_by_id(self, event_id: int) -> Optional[AuditEvent]:
        raise NotImplementedError
    
    def search(
        self,
        event_type: Optional[AuditEventType] = None,
        username: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        severity: Optional[AuditSeverity] = None,
        limit: int = 100
    ) -> List[AuditEvent]:
        # Поиск событий по критериям
        raise NotImplementedError
    
    def verify_integrity(self, event_id: int) -> bool:
        # Проверить целостность записи
        raise NotImplementedError


class SQLiteAuditStorage(AuditStorage):    # Реализация хранилища на SQLite
    def __init__(self, db_path: str = "audit.db"):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self) -> None:    # Создание таблиц и индексов
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    username TEXT NOT NULL,
                    ip_address TEXT,
                    description TEXT NOT NULL,
                    details TEXT,
                    checksum TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Индексы для ускорения поиска
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_timestamp "
                "ON audit_events(timestamp)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_event_type "
                "ON audit_events(event_type)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_username "
                "ON audit_events(username)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_severity "
                "ON audit_events(severity)"
            )
            
            conn.commit()
    
    @contextmanager
    def _get_connection(self):    # Context manager для безопасной работы с БД
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def _calculate_checksum(self, event: AuditEvent) -> str:    # Сериализация события без checksum
        data = {
            'timestamp': event.timestamp,
            'event_type': event.event_type.value,
            'severity': event.severity.value,
            'username': event.username,
            'ip_address': event.ip_address,
            'description': event.description,
            'details': event.details
        }
        
        json_str = json.dumps(data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(json_str.encode('utf-8')).hexdigest()
    
    def save(self, event: AuditEvent) -> int:    # Сохраняет событие в БД с вычислением контрольной суммы
        event.checksum = self._calculate_checksum(event)
        
        with self._get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO audit_events 
                (timestamp, event_type, severity, username, ip_address, 
                 description, details, checksum)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event.timestamp,
                event.event_type.value,
                event.severity.value,
                event.username,
                event.ip_address,
                event.description,
                json.dumps(event.details) if event.details else None,
                event.checksum
            ))
            conn.commit()
            return cursor.lastrowid
    
    def get_by_id(self, event_id: int) -> Optional[AuditEvent]:    # Получает событие по ID
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM audit_events WHERE id = ?",
                (event_id,)
            ).fetchone()
            
            if not row:
                return None
            
            return self._row_to_event(row)
    
    def search(
        self,
        event_type: Optional[AuditEventType] = None,
        username: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        severity: Optional[AuditSeverity] = None,
        limit: int = 100
    ) -> List[AuditEvent]:

        query = "SELECT * FROM audit_events WHERE 1=1"    # Поиск событий по критериям
        params = []
        
        if event_type:
            query += " AND event_type = ?"
            params.append(event_type.value)
        
        if username:
            query += " AND username = ?"
            params.append(username)
        
        if start_date:
            query += " AND timestamp >= ?"
            params.append(start_date)
        
        if end_date:
            query += " AND timestamp <= ?"
            params.append(end_date)
        
        if severity:
            query += " AND severity = ?"
            params.append(severity.value)
        
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_event(row) for row in rows]
    
    def verify_integrity(self, event_id: int) -> bool:    # Проверяет целостность записи по контрольной сумме
        event = self.get_by_id(event_id)
        if not event:
            return False
        
        stored_checksum = event.checksum
        event.checksum = None   # Временно удаляем для пересчета
        calculated_checksum = self._calculate_checksum(event)
        
        return stored_checksum == calculated_checksum
    
    def _row_to_event(self, row: sqlite3.Row) -> AuditEvent:   # Конвертирует строку БД в AuditEvent
        return AuditEvent(
            id=row['id'],
            timestamp=row['timestamp'],
            event_type=AuditEventType(row['event_type']),
            severity=AuditSeverity(row['severity']),
            username=row['username'],
            ip_address=row['ip_address'],
            description=row['description'],
            details=json.loads(row['details']) if row['details'] else None,
            checksum=row['checksum']
        )


class AuditService:    # Сервис аудита действий пользователей и системных событий
    def __init__(self, storage: Optional[AuditStorage] = None):
        self.storage = storage or SQLiteAuditStorage()
    
    def log_event(    # Логирует событие аудита
        self,
        event_type: AuditEventType,
        username: str,
        description: str,
        severity: AuditSeverity = AuditSeverity.MEDIUM,
        ip_address: Optional[str] = None,
        **details: Any
    ) -> int:
        event = AuditEvent(
            event_type=event_type,
            severity=severity,
            username=username,
            ip_address=ip_address,
            description=description,
            details=details if details else None
        )
        
        return self.storage.save(event)
    
    def log_login_success(    # Логирует успешный вход
        self,
        username: str,
        ip_address: Optional[str] = None
    ) -> int:
        return self.log_event(
            AuditEventType.LOGIN_SUCCESS,
            username,
            f"Пользователь {username} успешно вошел в систему",
            AuditSeverity.LOW,
            ip_address
        )
    
    def log_login_failed(    # Логирует неудачную попытку входа
        self,
        username: str,
        reason: str,
        ip_address: Optional[str] = None
    ) -> int:
        return self.log_event(
            AuditEventType.LOGIN_FAILED,
            username,
            f"Неудачная попытка входа: {reason}",
            AuditSeverity.MEDIUM,
            ip_address,
            reason=reason
        )
    
    def log_logout(self, username: str) -> int:    # Логирует выход из системы

        return self.log_event(
            AuditEventType.LOGOUT,
            username,
            f"Пользователь {username} вышел из системы",
            AuditSeverity.LOW
        )
    
    def log_password_change(    # Логирует смену пароля
        self,
        username: str,
        changed_by: str
    ) -> int:
        return self.log_event(
            AuditEventType.PASSWORD_CHANGE,
            changed_by,
            f"Пароль пользователя {username} был изменен",
            AuditSeverity.MEDIUM,
            target_user=username
        )
    
    def log_anomaly(    # Логирует обнаружение аномалии
        self,
        username: str,
        parameter: str,
        value: float,
        limit: float,
        mode: str
    ) -> int:
        return self.log_event(
            AuditEventType.ANOMALY_DETECTED,
            username,
            f"Аномалия: {parameter} = {value} (лимит: {limit})",
            AuditSeverity.HIGH,
            parameter=parameter,
            value=value,
            limit=limit,
            mode=mode
        )
    
    def log_mode_change(    # Логирует смену режима работы ГТУ
        self,
        username: str,
        old_mode: str,
        new_mode: str
    ) -> int:
        severity = (
            AuditSeverity.CRITICAL
            if new_mode == "EMERGENCY"
            else AuditSeverity.MEDIUM
        )
        
        return self.log_event(
            AuditEventType.MODE_CHANGED,
            username,
            f"Режим изменен: {old_mode} → {new_mode}",
            severity,
            old_mode=old_mode,
            new_mode=new_mode
        )
    
    def log_unauthorized_access(    # Логирует попытку неавторизованного доступа
        self,
        username: str,
        resource: str,
        ip_address: Optional[str] = None
    ) -> int:
        return self.log_event(
            AuditEventType.UNAUTHORIZED_ACCESS,
            username,
            f"Попытка доступа к {resource} без прав",
            AuditSeverity.HIGH,
            ip_address,
            resource=resource
        )
    
    def search_events(    # Поиск событий аудита
        self,
        event_type: Optional[AuditEventType] = None,
        username: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        severity: Optional[AuditSeverity] = None,
        limit: int = 100
    ) -> List[AuditEvent]:
        return self.storage.search(
            event_type, username, start_date, end_date, severity, limit
        )
    
    def verify_event_integrity(self, event_id: int) -> bool:    # Проверяет целостность события
        return self.storage.verify_integrity(event_id)
    
    def get_user_activity(
        self,
        username: str,
        days: int = 7
    ) -> List[AuditEvent]:
        start_date = (
            datetime.utcnow() - 
            __import__('datetime').timedelta(days=days)
        ).isoformat()
        
        return self.search_events(
            username=username,
            start_date=start_date,
            limit=1000
        )
    
    def get_critical_events(self, hours: int = 24) -> List[AuditEvent]:    # Получает критические события за период

        start_date = (
            datetime.utcnow() - 
            __import__('datetime').timedelta(hours=hours)
        ).isoformat()
        
        return self.search_events(
            severity=AuditSeverity.CRITICAL,
            start_date=start_date,
            limit=1000
        )


# Глобальный экземпляр сервиса
_audit_service: Optional[AuditService] = None


def get_audit_service(    # Получить глобальный экземпляр сервиса аудита
    storage: Optional[AuditStorage] = None
) -> AuditService:
    global _audit_service
    if _audit_service is None:
        _audit_service = AuditService(storage)
    return _audit_service
