# Инструкция по запуску тестов

# Тесты логов:
# python -m unittest unit_tests.TestLoggingService -v

# Тесты аудита:
# python -m unittest unit_tests.TestAuditService -v

# Тесты интеграции:
# python -m unittest unit_tests.TestLoggingAuditIntegration -v

import unittest
import tempfile
import shutil
import os
import time
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from logging_service import (   # Импорты тестируемых модулей
    LoggingService,
    LoggerConfig,
    LogLevel,
    LogCategory,
    CustomFormatter,
    get_logging_service,
    log_system,
    log_auth,
    log_sensor,
    log_anomaly
)

from audit_service import (
    AuditService,
    AuditEvent,
    AuditEventType,
    AuditSeverity,
    SQLiteAuditStorage,
    AuditStorage,
    get_audit_service
)


# ТЕСТЫ СИСТЕМЫ ЛОГИРОВАНИЯ

class TestLoggerConfig(unittest.TestCase):
    
    def test_default_config(self):
        config = LoggerConfig()
        
        self.assertEqual(config.log_dir, "logs")
        self.assertEqual(config.max_file_size, 10 * 1024 * 1024)
        self.assertEqual(config.backup_count, 5)
        self.assertEqual(config.console_level, LogLevel.INFO)
        self.assertEqual(config.file_level, LogLevel.DEBUG)
        self.assertTrue(config.enable_console)
        self.assertTrue(config.enable_file)
    
    def test_custom_config(self):
        config = LoggerConfig(
            log_dir="custom_logs",
            max_file_size=5 * 1024 * 1024,
            backup_count=3,
            console_level=LogLevel.WARNING,
            file_level=LogLevel.ERROR,
            enable_console=False
        )
        
        self.assertEqual(config.log_dir, "custom_logs")
        self.assertEqual(config.max_file_size, 5 * 1024 * 1024)
        self.assertEqual(config.backup_count, 3)
        self.assertEqual(config.console_level, LogLevel.WARNING)
        self.assertEqual(config.file_level, LogLevel.ERROR)
        self.assertFalse(config.enable_console)


class TestCustomFormatter(unittest.TestCase):
    
    def test_formatter_with_colors(self):
        formatter = CustomFormatter(
            fmt='%(levelname)s | %(message)s',
            use_colors=True
        )
        
        import logging
        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="test.py",
            lineno=10,
            msg="Test error",
            args=(),
            exc_info=None
        )
        
        formatted = formatter.format(record)
        
        # Проверка наличия ANSI кодов
        self.assertIn('\033[', formatted)
        self.assertIn('ERROR', formatted)
        self.assertIn('Test error', formatted)
    
    def test_formatter_without_colors(self):
        formatter = CustomFormatter(
            fmt='%(levelname)s | %(message)s',
            use_colors=False
        )
        
        import logging
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test info",
            args=(),
            exc_info=None
        )
        
        formatted = formatter.format(record)
        
        # Проверка отсутствия ANSI кодов
        self.assertNotIn('\033[', formatted)
        self.assertIn('INFO', formatted)
        self.assertIn('Test info', formatted)


class TestLoggingService(unittest.TestCase):
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config = LoggerConfig(
            log_dir=self.temp_dir,
            enable_console=False,  # Отключаем консоль для тестов
            enable_file=True
        )
        # Сброс singleton для каждого теста
        LoggingService._instance = None
        LoggingService._initialized = False
        self.service = LoggingService(self.config)
    
    def tearDown(self):
        self.service.shutdown()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_singleton_pattern(self):
        service1 = LoggingService(self.config)
        service2 = LoggingService(self.config)
        
        self.assertIs(service1, service2)
    
    def test_log_directory_creation(self):
        self.assertTrue(os.path.exists(self.temp_dir))
        self.assertTrue(os.path.isdir(self.temp_dir))
    
    def test_get_logger(self):
        logger = self.service.get_logger("test_module")
        
        self.assertIsNotNone(logger)
        self.assertEqual(logger.name, "test_module")
        self.assertFalse(logger.propagate)
    
    def test_logger_caching(self):
        logger1 = self.service.get_logger("test_module")
        logger2 = self.service.get_logger("test_module")
        
        self.assertIs(logger1, logger2)
    
    def test_log_event(self):
        self.service.log_event(
            LogCategory.SYSTEM,
            LogLevel.INFO,
            "Test message",
            key1="value1",
            key2="value2"
        )
        
        # Проверка создания файла лога
        log_files = list(Path(self.temp_dir).glob("SYSTEM_*.log"))
        self.assertGreater(len(log_files), 0)
        
        # Проверка содержимого
        with open(log_files[0], 'r', encoding='utf-8') as f:
            content = f.read()
            self.assertIn("Test message", content)
            self.assertIn("key1=value1", content)
            self.assertIn("key2=value2", content)
    
    def test_log_levels(self):
        logger = self.service.get_logger("test_levels")
        
        logger.debug("Debug message")
        logger.info("Info message")
        logger.warning("Warning message")
        logger.error("Error message")
        logger.critical("Critical message")
        
        # Все сообщения должны быть записаны (file_level=DEBUG)
        log_files = list(Path(self.temp_dir).glob("test_levels_*.log"))
        self.assertGreater(len(log_files), 0)
        
        with open(log_files[0], 'r', encoding='utf-8') as f:
            content = f.read()
            self.assertIn("Debug message", content)
            self.assertIn("Info message", content)
            self.assertIn("Warning message", content)
            self.assertIn("Error message", content)
            self.assertIn("Critical message", content)
    
    def test_file_rotation(self):
        logger = self.service.get_logger("rotation_test")
        
        # Генерация большого количества логов
        for i in range(100):
            logger.info(f"Log message {i}" * 100)
        
        # Проверка создания файла
        log_files = list(Path(self.temp_dir).glob("rotation_test_*.log*"))
        self.assertGreater(len(log_files), 0)


class TestConvenienceFunctions(unittest.TestCase):
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        config = LoggerConfig(
            log_dir=self.temp_dir,
            enable_console=False
        )
        LoggingService._instance = None
        LoggingService._initialized = False
        self.service = LoggingService(config)
    
    def tearDown(self):
        self.service.shutdown()
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_log_system(self):
        log_system("System started", version="1.0.0")
        
        log_files = list(Path(self.temp_dir).glob("SYSTEM_*.log"))
        self.assertGreater(len(log_files), 0)
        
        with open(log_files[0], 'r', encoding='utf-8') as f:
            content = f.read()
            self.assertIn("System started", content)
            self.assertIn("version=1.0.0", content)
    
    def test_log_auth(self):
        log_auth("Login attempt", username="admin", ip="192.168.1.1")
        
        log_files = list(Path(self.temp_dir).glob("AUTH_*.log"))
        self.assertGreater(len(log_files), 0)
    
    def test_log_sensor(self):
        log_sensor("Sensor reading", rpm=3000, temp=400)
        
        log_files = list(Path(self.temp_dir).glob("SENSOR_*.log"))
        self.assertGreater(len(log_files), 0)
    
    def test_log_anomaly(self):
        log_anomaly("Vibration exceeded", value=5.2, limit=4.25)
        
        log_files = list(Path(self.temp_dir).glob("ANOMALY_*.log"))
        self.assertGreater(len(log_files), 0)


#______________________________________________________________________________________

# ТЕСТЫ СИСТЕМЫ АУДИТА

class TestAuditEvent(unittest.TestCase):
    
    def test_event_creation(self):
        event = AuditEvent(
            event_type=AuditEventType.LOGIN_SUCCESS,
            severity=AuditSeverity.LOW,
            username="admin",
            description="User logged in"
        )
        
        self.assertEqual(event.event_type, AuditEventType.LOGIN_SUCCESS)
        self.assertEqual(event.severity, AuditSeverity.LOW)
        self.assertEqual(event.username, "admin")
        self.assertEqual(event.description, "User logged in")
        self.assertIsNotNone(event.timestamp)
    
    def test_event_with_details(self):
        event = AuditEvent(
            event_type=AuditEventType.ANOMALY_DETECTED,
            severity=AuditSeverity.HIGH,
            username="system",
            description="Temperature exceeded",
            ip_address="192.168.1.100",
            details={"parameter": "temp", "value": 680, "limit": 670}
        )
        
        self.assertEqual(event.ip_address, "192.168.1.100")
        self.assertIsNotNone(event.details)
        self.assertEqual(event.details["parameter"], "temp")
        self.assertEqual(event.details["value"], 680)
    
    def test_timestamp_auto_generation(self):
        event1 = AuditEvent(
            event_type=AuditEventType.LOGIN_SUCCESS,
            severity=AuditSeverity.LOW,
            username="user1",
            description="Test"
        )
        
        time.sleep(0.01)  # Небольшая задержка
        
        event2 = AuditEvent(
            event_type=AuditEventType.LOGIN_SUCCESS,
            severity=AuditSeverity.LOW,
            username="user2",
            description="Test"
        )
        
        self.assertNotEqual(event1.timestamp, event2.timestamp)
        self.assertLess(event1.timestamp, event2.timestamp)


class TestSQLiteAuditStorage(unittest.TestCase):
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_audit.db")
        self.storage = SQLiteAuditStorage(self.db_path)
    
    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_database_initialization(self):
        self.assertTrue(os.path.exists(self.db_path))
        
        # Проверка структуры таблицы
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()
        
        self.assertIn("audit_events", tables)
    
    def test_save_event(self):
        event = AuditEvent(
            event_type=AuditEventType.LOGIN_SUCCESS,
            severity=AuditSeverity.LOW,
            username="admin",
            description="Test login"
        )
        
        event_id = self.storage.save(event)
        
        self.assertIsNotNone(event_id)
        self.assertGreater(event_id, 0)
    
    def test_get_by_id(self):
        original_event = AuditEvent(
            event_type=AuditEventType.PASSWORD_CHANGE,
            severity=AuditSeverity.MEDIUM,
            username="user1",
            description="Password changed",
            ip_address="192.168.1.1"
        )
        
        event_id = self.storage.save(original_event)
        retrieved_event = self.storage.get_by_id(event_id)
        
        self.assertIsNotNone(retrieved_event)
        self.assertEqual(retrieved_event.event_type, original_event.event_type)
        self.assertEqual(retrieved_event.username, original_event.username)
        self.assertEqual(retrieved_event.description, original_event.description)
        self.assertEqual(retrieved_event.ip_address, original_event.ip_address)
    
    def test_get_nonexistent_event(self):
        event = self.storage.get_by_id(99999)
        self.assertIsNone(event)
    
    def test_checksum_calculation(self):
        event = AuditEvent(
            event_type=AuditEventType.LOGIN_SUCCESS,
            severity=AuditSeverity.LOW,
            username="admin",
            description="Test"
        )
        
        event_id = self.storage.save(event)
        retrieved = self.storage.get_by_id(event_id)
        
        self.assertIsNotNone(retrieved.checksum)
        self.assertEqual(len(retrieved.checksum), 64)  # SHA-256 hex
    
    def test_verify_integrity_valid(self):
        event = AuditEvent(
            event_type=AuditEventType.LOGIN_SUCCESS,
            severity=AuditSeverity.LOW,
            username="admin",
            description="Test"
        )
        
        event_id = self.storage.save(event)
        is_valid = self.storage.verify_integrity(event_id)
        
        self.assertTrue(is_valid)
    
    def test_verify_integrity_tampered(self):
        event = AuditEvent(
            event_type=AuditEventType.LOGIN_SUCCESS,
            severity=AuditSeverity.LOW,
            username="admin",
            description="Original"
        )
        
        event_id = self.storage.save(event)
        
        # Изменение записи напрямую в БД (Ярик не справился с троянами)
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE audit_events SET description = ? WHERE id = ?",
            ("Tampered", event_id)
        )
        conn.commit()
        conn.close()
        
        is_valid = self.storage.verify_integrity(event_id)
        
        self.assertFalse(is_valid)
    
    def test_search_by_event_type(self):
        # Создание нескольких событий
        for i in range(3):
            self.storage.save(AuditEvent(
                event_type=AuditEventType.LOGIN_SUCCESS,
                severity=AuditSeverity.LOW,
                username=f"user{i}",
                description=f"Login {i}"
            ))
        
        self.storage.save(AuditEvent(
            event_type=AuditEventType.LOGIN_FAILED,
            severity=AuditSeverity.MEDIUM,
            username="hacker",
            description="Failed login"
        ))
        
        # Поиск успешных входов
        results = self.storage.search(
            event_type=AuditEventType.LOGIN_SUCCESS
        )
        
        self.assertEqual(len(results), 3)
        for event in results:
            self.assertEqual(event.event_type, AuditEventType.LOGIN_SUCCESS)
    
    def test_search_by_username(self):
        self.storage.save(AuditEvent(
            event_type=AuditEventType.LOGIN_SUCCESS,
            severity=AuditSeverity.LOW,
            username="admin",
            description="Login 1"
        ))
        
        self.storage.save(AuditEvent(
            event_type=AuditEventType.LOGOUT,
            severity=AuditSeverity.LOW,
            username="admin",
            description="Logout"
        ))
        
        self.storage.save(AuditEvent(
            event_type=AuditEventType.LOGIN_SUCCESS,
            severity=AuditSeverity.LOW,
            username="user1",
            description="Login 2"
        ))
        
        results = self.storage.search(username="admin")
        
        self.assertEqual(len(results), 2)
        for event in results:
            self.assertEqual(event.username, "admin")
    
    def test_search_by_severity(self):
        self.storage.save(AuditEvent(
            event_type=AuditEventType.LOGIN_SUCCESS,
            severity=AuditSeverity.LOW,
            username="user1",
            description="Low event"
        ))
        
        self.storage.save(AuditEvent(
            event_type=AuditEventType.ANOMALY_DETECTED,
            severity=AuditSeverity.CRITICAL,
            username="system",
            description="Critical event"
        ))
        
        results = self.storage.search(severity=AuditSeverity.CRITICAL)
        
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].severity, AuditSeverity.CRITICAL)
    
    def test_search_with_limit(self):
        # Создание 10 событий
        for i in range(10):
            self.storage.save(AuditEvent(
                event_type=AuditEventType.LOGIN_SUCCESS,
                severity=AuditSeverity.LOW,
                username=f"user{i}",
                description=f"Login {i}"
            ))
        
        results = self.storage.search(limit=5)
        
        self.assertEqual(len(results), 5)
    
    def test_search_by_date_range(self):
        now = datetime.utcnow()
        yesterday = (now - timedelta(days=1)).isoformat()
        tomorrow = (now + timedelta(days=1)).isoformat()
        
        self.storage.save(AuditEvent(
            event_type=AuditEventType.LOGIN_SUCCESS,
            severity=AuditSeverity.LOW,
            username="user1",
            description="Recent login"
        ))
        
        results = self.storage.search(
            start_date=yesterday,
            end_date=tomorrow
        )
        
        self.assertGreater(len(results), 0)


class TestAuditService(unittest.TestCase):
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_audit.db")
        storage = SQLiteAuditStorage(self.db_path)
        self.service = AuditService(storage)
    
    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_log_event(self):
        event_id = self.service.log_event(
            AuditEventType.LOGIN_SUCCESS,
            "admin",
            "User logged in",
            ip_address="192.168.1.1"
        )
        
        self.assertIsNotNone(event_id)
        self.assertGreater(event_id, 0)
    
    def test_log_login_success(self):
        event_id = self.service.log_login_success("admin", "192.168.1.1")
        
        event = self.service.storage.get_by_id(event_id)
        
        self.assertEqual(event.event_type, AuditEventType.LOGIN_SUCCESS)
        self.assertEqual(event.username, "admin")
        self.assertEqual(event.ip_address, "192.168.1.1")
        self.assertEqual(event.severity, AuditSeverity.LOW)
    
    def test_log_login_failed(self):
        event_id = self.service.log_login_failed(
            "hacker",
            "Invalid password",
            "192.168.1.100"
        )
        
        event = self.service.storage.get_by_id(event_id)
        
        self.assertEqual(event.event_type, AuditEventType.LOGIN_FAILED)
        self.assertEqual(event.severity, AuditSeverity.MEDIUM)
        self.assertIn("Invalid password", event.description)
    
    def test_log_anomaly(self):
        event_id = self.service.log_anomaly(
            "system",
            "vibration",
            5.2,
            4.25,
            "NOMINAL"
        )
        
        event = self.service.storage.get_by_id(event_id)
        
        self.assertEqual(event.event_type, AuditEventType.ANOMALY_DETECTED)
        self.assertEqual(event.severity, AuditSeverity.HIGH)
        self.assertIsNotNone(event.details)
        self.assertEqual(event.details["parameter"], "vibration")
        self.assertEqual(event.details["value"], 5.2)
    
    def test_log_mode_change_normal(self):
        event_id = self.service.log_mode_change(
            "operator",
            "IDLE",
            "PARTIAL"
        )
        
        event = self.service.storage.get_by_id(event_id)
        
        self.assertEqual(event.event_type, AuditEventType.MODE_CHANGED)
        self.assertEqual(event.severity, AuditSeverity.MEDIUM)
    
    def test_log_mode_change_emergency(self):
        event_id = self.service.log_mode_change(
            "system",
            "NOMINAL",
            "EMERGENCY"
        )
        
        event = self.service.storage.get_by_id(event_id)
        
        self.assertEqual(event.severity, AuditSeverity.CRITICAL)
    
    def test_search_events(self):
        # Создание тестовых событий
        self.service.log_login_success("admin", "192.168.1.1")
        self.service.log_login_failed("user1", "Wrong password", "192.168.1.2")
        self.service.log_login_success("user2", "192.168.1.3")
        
        # Поиск успешных входов
        results = self.service.search_events(
            event_type=AuditEventType.LOGIN_SUCCESS
        )
        
        self.assertEqual(len(results), 2)
    
    def test_get_user_activity(self):
        # Создание событий для разных пользователей
        self.service.log_login_success("admin", "192.168.1.1")
        self.service.log_logout("admin")
        self.service.log_login_success("user1", "192.168.1.2")
        
        # Получение активности admin
        activity = self.service.get_user_activity("admin", days=1)
        
        self.assertEqual(len(activity), 2)
        for event in activity:
            self.assertEqual(event.username, "admin")
    
    def test_get_critical_events(self):
        # Создание событий разной критичности
        self.service.log_login_success("user1", "192.168.1.1")  # LOW
        self.service.log_mode_change("system", "NOMINAL", "EMERGENCY")  # CRITICAL
        self.service.log_anomaly("system", "temp", 700, 670, "NOMINAL")  # HIGH
        
        # Получение только критических
        critical = self.service.get_critical_events(hours=24)
        
        self.assertEqual(len(critical), 1)
        self.assertEqual(critical[0].severity, AuditSeverity.CRITICAL)
    
    def test_verify_event_integrity(self):
        event_id = self.service.log_login_success("admin", "192.168.1.1")
        
        is_valid = self.service.verify_event_integrity(event_id)
        
        self.assertTrue(is_valid)


#_________________________________________________________________________________

# ИНТЕГРАЦИОННЫЕ ТЕСТЫ

class TestLoggingAuditIntegration(unittest.TestCase):
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        
        # Логирование - создаем директорию явно
        self.log_dir = os.path.join(self.temp_dir, "logs")
        os.makedirs(self.log_dir, exist_ok=True)
        
        log_config = LoggerConfig(
            log_dir=self.log_dir,
            enable_console=False,
            enable_file=True
        )
        
        # ВАЖНО: Сбрасываем глобальный singleton
        import logging_service
        logging_service._logging_service = None
        LoggingService._instance = None
        LoggingService._initialized = False
        
        # Создаем новый экземпляр
        self.logging_service = LoggingService(log_config)
        
        # Устанавливаем его как глобальный
        logging_service._logging_service = self.logging_service
        
        # Аудит
        db_path = os.path.join(self.temp_dir, "audit.db")
        storage = SQLiteAuditStorage(db_path)
        self.audit_service = AuditService(storage)
    
    def tearDown(self):
        self.logging_service.shutdown()
        
        # Сбрасываем глобальный singleton
        import logging_service
        logging_service._logging_service = None
        LoggingService._instance = None
        LoggingService._initialized = False
        
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_login_scenario(self):
        username = "test_user"
        ip = "192.168.1.100"
        
        # Логирование - используем напрямую наш сервис
        self.logging_service.log_event(
            LogCategory.AUTH,
            LogLevel.INFO,
            f"Login attempt",
            username=username,
            ip=ip
        )
        
        # Аудит
        event_id = self.audit_service.log_login_success(username, ip)
        
        # Даем время на запись
        time.sleep(0.1)
        
        # Проверка логов
        log_files = list(Path(self.log_dir).glob("AUTH_*.log"))
        self.assertGreater(len(log_files), 0, 
                          f"No log files found in {self.log_dir}. "
                          f"Contents: {list(Path(self.log_dir).iterdir())}")
        
        # Проверка аудита
        event = self.audit_service.storage.get_by_id(event_id)
        self.assertIsNotNone(event)
        self.assertEqual(event.username, username)
    
    def test_anomaly_detection_scenario(self):
        parameter = "vibration"
        value = 5.2
        limit = 4.25
        
        # Логирование - используем напрямую наш сервис
        self.logging_service.log_event(
            LogCategory.ANOMALY,
            LogLevel.ERROR,
            f"Anomaly detected: {parameter}",
            value=value,
            limit=limit
        )
        
        # Аудит
        event_id = self.audit_service.log_anomaly(
            "system",
            parameter,
            value,
            limit,
            "NOMINAL"
        )
        
        # Даем время на запись
        time.sleep(0.1)
        
        # Проверка логов
        log_files = list(Path(self.log_dir).glob("ANOMALY_*.log"))
        self.assertGreater(len(log_files), 0,
                          f"No ANOMALY log files found in {self.log_dir}. "
                          f"Available: {list(Path(self.log_dir).glob('*.log'))}")
        
        with open(log_files[0], 'r', encoding='utf-8') as f:
            content = f.read()
            self.assertIn(parameter, content)
            self.assertIn(str(value), content)
        
        # Проверка аудита
        event = self.audit_service.storage.get_by_id(event_id)
        self.assertEqual(event.severity, AuditSeverity.HIGH)
        self.assertEqual(event.details["parameter"], parameter)
    
    def test_mode_change_scenario(self):
        old_mode = "IDLE"
        new_mode = "PARTIAL"
        operator = "operator1"
        
        # Логирование - используем напрямую наш сервис
        self.logging_service.log_event(
            LogCategory.MODE_CHANGE,
            LogLevel.INFO,
            f"Mode changed: {old_mode} -> {new_mode}",
            operator=operator
        )
        
        # Аудит
        event_id = self.audit_service.log_mode_change(
            operator,
            old_mode,
            new_mode
        )
        
        # Даем время на запись
        time.sleep(0.1)
        
        # Проверка логов
        log_files = list(Path(self.log_dir).glob("MODE_CHANGE_*.log"))
        
        # Отладочная информация
        if len(log_files) == 0:
            all_files = list(Path(self.log_dir).glob("*"))
            print(f"\nDEBUG: log_dir = {self.log_dir}")
            print(f"DEBUG: log_dir exists = {os.path.exists(self.log_dir)}")
            print(f"DEBUG: all files in log_dir = {all_files}")
            
            # Проверяем, что логгер создан
            logger = self.logging_service.get_logger("MODE_CHANGE")
            print(f"DEBUG: logger = {logger}")
            print(f"DEBUG: logger.handlers = {logger.handlers}")
            for handler in logger.handlers:
                print(f"DEBUG: handler = {handler}")
                if hasattr(handler, 'baseFilename'):
                    print(f"DEBUG: handler.baseFilename = {handler.baseFilename}")
        
        self.assertGreater(len(log_files), 0,
                          f"No MODE_CHANGE log files found in {self.log_dir}. "
                          f"Available files: {list(Path(self.log_dir).glob('*.log'))}")
        
        # Проверка содержимого лога
        with open(log_files[0], 'r', encoding='utf-8') as f:
            content = f.read()
            self.assertIn(old_mode, content)
            self.assertIn(new_mode, content)
        
        # Проверка аудита
        event = self.audit_service.storage.get_by_id(event_id)
        self.assertEqual(event.event_type, AuditEventType.MODE_CHANGED)
        self.assertEqual(event.details["old_mode"], old_mode)
        self.assertEqual(event.details["new_mode"], new_mode)

class TestEdgeCases(unittest.TestCase):
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test.db")
        self.storage = SQLiteAuditStorage(self.db_path)
        self.service = AuditService(self.storage)
    
    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_empty_search(self):
        results = self.service.search_events()
        self.assertEqual(len(results), 0)
    
    def test_search_with_no_matches(self):
        self.service.log_login_success("admin", "192.168.1.1")
        
        results = self.service.search_events(
            event_type=AuditEventType.PASSWORD_RESET
        )
        
        self.assertEqual(len(results), 0)
    
    def test_unicode_in_description(self):
        event_id = self.service.log_event(
            AuditEventType.LOGIN_SUCCESS,
            "пользователь",
            "Вход выполнен успешно 🎉",
            details={"сообщение": "тест"}
        )
        
        event = self.storage.get_by_id(event_id)
        
        self.assertIn("Вход", event.description)
        self.assertEqual(event.details["сообщение"], "тест")
    
    def test_very_long_description(self):
        long_desc = "A" * 10000
        
        event_id = self.service.log_event(
            AuditEventType.SUSPICIOUS_ACTIVITY,
            "system",
            long_desc
        )
        
        event = self.storage.get_by_id(event_id)
        self.assertEqual(len(event.description), 10000)
    
    def test_null_ip_address(self):
        event_id = self.service.log_login_success("admin", None)
        
        event = self.storage.get_by_id(event_id)
        self.assertIsNone(event.ip_address)
    
    def test_empty_details(self):
        event_id = self.service.log_event(
            AuditEventType.LOGOUT,
            "user1",
            "User logged out"
        )
        
        event = self.storage.get_by_id(event_id)
        self.assertIsNone(event.details)


#______________________________________________________________________

# ЗАПУСК ТЕСТОВ

def suite():
    test_suite = unittest.TestSuite()
    
    # Логирование
    test_suite.addTest(unittest.makeSuite(TestLoggerConfig))
    test_suite.addTest(unittest.makeSuite(TestCustomFormatter))
    test_suite.addTest(unittest.makeSuite(TestLoggingService))
    test_suite.addTest(unittest.makeSuite(TestConvenienceFunctions))
    
    # Аудит
    test_suite.addTest(unittest.makeSuite(TestAuditEvent))
    test_suite.addTest(unittest.makeSuite(TestSQLiteAuditStorage))
    test_suite.addTest(unittest.makeSuite(TestAuditService))
    
    # Интеграция
    test_suite.addTest(unittest.makeSuite(TestLoggingAuditIntegration))
    test_suite.addTest(unittest.makeSuite(TestEdgeCases))
    
    return test_suite


if __name__ == '__main__':
    # Запуск всех тестов
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite())
