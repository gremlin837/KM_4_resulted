import logging
import logging.handlers
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
from enum import Enum


class LogLevel(Enum):
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    CRITICAL = logging.CRITICAL


class LogCategory(Enum):
    SYSTEM = "SYSTEM"           # системные события
    AUTH = "AUTH"               # авторизация и аутентификация
    SENSOR = "SENSOR"           # данные с датчиков
    ANALYSIS = "ANALYSIS"       # аналитические процессы
    ANOMALY = "ANOMALY"         # аномалии
    MODE_CHANGE = "MODE_CHANGE" # смена режимов работы
    API = "API"                 # API-запросы
    DATABASE = "DATABASE"       # операции с БД
    UI = "UI"                   # пользовательский интерфейс


class CustomFormatter(logging.Formatter):
    COLORS = {
        'DEBUG': '\033[36m',    # Cyan - Debug
        'INFO': '\033[32m',     # Green - Info
        'WARNING': '\033[33m',  # Yellow - Warning
        'ERROR': '\033[31m',    # Red - Error
        'CRITICAL': '\033[35m', # Magenta - Critcal
        'RESET': '\033[0m'      # Reset - Reset
    }
    
    def __init__(self, fmt: str, use_colors: bool = True):
        super().__init__(fmt)
        self.use_colors = use_colors
    
    def format(self, record: logging.LogRecord) -> str:
        if self.use_colors and record.levelname in self.COLORS:
            record.levelname = (
                f"{self.COLORS[record.levelname]}"
                f"{record.levelname}"
                f"{self.COLORS['RESET']}"
            )
        return super().format(record)


class LoggerConfig:
    def __init__(
        self,
        log_dir: str = "logs",                      # директория для файлов логов
        max_file_size: int = 10 * 1024 * 1024,      # максимальный размер файла (10 MB по умолчанию)
        backup_count: int = 5,                      # количество ротируемых копий (5)
        console_level: LogLevel = LogLevel.INFO,    # уровень логов в консоль
        file_level: LogLevel = LogLevel.DEBUG,      # уровень логов в файл
        enable_console: bool = True,                # включить/выключить вывод в консоль
        enable_file: bool = True                    # включить/выключить запись в файл
    ):
        self.log_dir = log_dir
        self.max_file_size = max_file_size
        self.backup_count = backup_count
        self.console_level = console_level
        self.file_level = file_level
        self.enable_console = enable_console
        self.enable_file = enable_file


class LoggingService:
    _instance: Optional['LoggingService'] = None
    _initialized: bool = False
    
    def __new__(cls, config: Optional[LoggerConfig] = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, config: Optional[LoggerConfig] = None):
        if self._initialized:
            return
        
        self.config = config or LoggerConfig()
        self._loggers: Dict[str, logging.Logger] = {}
        self._setup_logging_directory()
        self._initialized = True
    
    def _setup_logging_directory(self) -> None:
        Path(self.config.log_dir).mkdir(parents=True, exist_ok=True)
    
    def _create_console_handler(self) -> logging.Handler:   # создает handler для вывода в консоль
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(self.config.console_level.value)
        
        formatter = CustomFormatter(
            fmt='%(asctime)s | %(levelname)-8s | %(name)-12s | %(message)s',
            use_colors=True
        )
        handler.setFormatter(formatter)
        return handler
    
    def _create_file_handler(self, name: str) -> logging.Handler:   # создает rotating file handler
        log_file = os.path.join(
            self.config.log_dir,
            f"{name}_{datetime.now().strftime('%Y%m%d')}.log"
        )
        
        handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=self.config.max_file_size,
            backupCount=self.config.backup_count,
            encoding='utf-8'
        )
        handler.setLevel(self.config.file_level.value)
        
        formatter = logging.Formatter(
            fmt='%(asctime)s | %(levelname)-8s | %(name)-12s | '
                '%(filename)s:%(lineno)d | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        return handler
    
    def get_logger(self, name: str) -> logging.Logger:   # получает или создает логгер с заданным именем
        if name in self._loggers:
            return self._loggers[name]
        
        logger = logging.getLogger(name)
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()
        
        if self.config.enable_console:
            logger.addHandler(self._create_console_handler())
        
        if self.config.enable_file:
            logger.addHandler(self._create_file_handler(name))
        
        logger.propagate = False
        
        self._loggers[name] = logger
        return logger
    
    def log_event(
        self,
        category: LogCategory,
        level: LogLevel,
        message: str,
        **kwargs: Any
    ) -> None:
        logger = self.get_logger(category.value)
        
        extra_info = " | ".join(
            f"{k}={v}" for k, v in kwargs.items()
        ) if kwargs else ""
        
        full_message = f"{message} {extra_info}".strip()
        
        logger.log(level.value, full_message)
    
    def shutdown(self) -> None:    # корректное завершение работы всех логгеров
        for logger in self._loggers.values():
            for handler in logger.handlers[:]:
                handler.close()
                logger.removeHandler(handler)
        
        self._loggers.clear()
        logging.shutdown()

    # глобальный экземпляр сервиса
_logging_service: Optional[LoggingService] = None


def get_logging_service(
    config: Optional[LoggerConfig] = None
) -> LoggingService:
    global _logging_service
    if _logging_service is None:
        _logging_service = LoggingService(config)
    return _logging_service


def log_system(message: str, level: LogLevel = LogLevel.INFO, **kwargs):    # логирование системных событий
    get_logging_service().log_event(
        LogCategory.SYSTEM, level, message, **kwargs
    )


def log_auth(message: str, level: LogLevel = LogLevel.INFO, **kwargs):  # логирование событий аутентификации
    get_logging_service().log_event(
        LogCategory.AUTH, level, message, **kwargs
    )


def log_sensor(message: str, level: LogLevel = LogLevel.DEBUG, **kwargs):   # логирование опроса датчиков
    get_logging_service().log_event(
        LogCategory.SENSOR, level, message, **kwargs
    )


def log_analysis(message: str, level: LogLevel = LogLevel.INFO, **kwargs):  # логирование анализа данных
    get_logging_service().log_event(
        LogCategory.ANALYSIS, level, message, **kwargs
    )


def log_anomaly(message: str, level: LogLevel = LogLevel.WARNING, **kwargs):    # логирование обнаруженных аномалий
    get_logging_service().log_event(
        LogCategory.ANOMALY, level, message, **kwargs
    )


def log_mode_change(message: str, level: LogLevel = LogLevel.INFO, **kwargs):   # логирование смены режима работы ГТУ
    get_logging_service().log_event(
        LogCategory.MODE_CHANGE, level, message, **kwargs
    )
