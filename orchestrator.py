"""
Оркестратор – управляет опросом датчиков, анализом, сохранением и сменой режимов.
Зависимости (симулятор, хранилище, логгер, аудит) передаются извне.
"""

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Optional, Protocol, Any

from gtu_simulator import GTUSimulator, GTUMode
from gtu_analyzer import GTUAnalyzer
from storage import Storage, SensorRecord
from logging_service import get_logging_service
from audit_service import get_audit_service


# Протоколы для инверсии зависимостей
class LoggerProtocol(Protocol):
    def info(self, msg: str, *args, **kwargs) -> None: ...
    def error(self, msg: str, *args, **kwargs) -> None: ...
    def warning(self, msg: str, *args, **kwargs) -> None: ...

class AuditProtocol(Protocol):
    def log_mode_change(self, username: str, old_mode: str, new_mode: str) -> Any: ...
    def log_anomaly(self, username: str, parameter: str, value: float, limit: float, mode: str) -> Any: ...


@dataclass
class SystemState:
    last_readings: dict = field(default_factory=dict)
    last_mode: str = "UNKNOWN"
    last_anomalies: list = field(default_factory=list)
    last_timestamp: float = 0.0
    is_running: bool = False


class Orchestrator:
    """
    Оркестратор с возможностью внедрения зависимостей.
    """

    CYCLE: list[tuple[GTUMode, int]] = [
        (GTUMode.START, 200),
        (GTUMode.IDLE, 300),
        (GTUMode.PARTIAL, 450),
        (GTUMode.NOMINAL, 500),
        (GTUMode.EMERGENCY, 50),
        (GTUMode.STOP, 300),
    ]

    def __init__(
        self,
        poll_interval: float = 1.0,
        auto_cycle: bool = True,
        simulator: Optional[GTUSimulator] = None,
        storage: Optional[Storage] = None,
        logger: Optional[LoggerProtocol] = None,
        audit: Optional[AuditProtocol] = None,
    ) -> None:
        self._poll_interval = poll_interval
        self._auto_cycle = auto_cycle

        # Внедрённые зависимости
        self._simulator = simulator or GTUSimulator(interval=poll_interval)
        self._storage = storage or Storage()

        # Логгер и аудит – если не переданы, берём реальные сервисы
        if logger is None:
            logger = get_logging_service().get_logger("orchestrator")
        if audit is None:
            audit = get_audit_service()
        self._logger = logger
        self._audit = audit

        self._state = SystemState()
        self._lock = threading.Lock()
        self._poll_thread: Optional[threading.Thread] = None
        self._cycle_thread: Optional[threading.Thread] = None

    # Управление жизненным циклом
    def start(self) -> None:
        if self._state.is_running:
            return
        self._state.is_running = True

        if self._auto_cycle:
            self._cycle_thread = threading.Thread(
                target=self._run_cycle, daemon=True, name="GTUCycle"
            )
            self._cycle_thread.start()

        self._poll_thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="GTUPoll"
        )
        self._poll_thread.start()
        self._logger.info("Оркестратор запущен")

    def stop(self) -> None:
        self._state.is_running = False
        self._simulator.stop()
        self._logger.info("Оркестратор остановлен")

    # Публичный интерфейс
    def get_current_state(self) -> dict:
        with self._lock:
            return {
                "timestamp": self._state.last_timestamp,
                "mode": self._state.last_mode,
                "anomalies": list(self._state.last_anomalies),
                "readings": dict(self._state.last_readings),
            }

    def get_history(self, limit: int = 100) -> list:
        return self._storage.get_latest(limit)

    # Внутренние методы
    def _run_cycle(self) -> None:
        old_mode = None
        while self._state.is_running:
            for mode, duration in self.CYCLE:
                if not self._state.is_running:
                    return
                if old_mode is not None:
                    self._audit.log_mode_change(
                        username="SYSTEM",
                        old_mode=old_mode,
                        new_mode=mode.value
                    )
                self._simulator.set_mode(mode)
                self._logger.info(f"Режим ГТУ: {mode.value}")
                old_mode = mode.value
                time.sleep(duration)

    @staticmethod
    def _analyze(readings: dict) -> tuple[str, list[str]]:
        try:
            return GTUAnalyzer.classify(
                rpm=readings["rpm"],
                temp=readings["exhaust_temp"],
                pres=readings["inlet_pressure"],
                fuel=readings["fuel_flow"],
                vib=readings["vibration"],
                iga=readings["iga_position"],
            )
        except KeyError as exc:
            # Возвращаем "UNKNOWN" и сообщение об отсутствующем ключе
            return "UNKNOWN", [f"Отсутствует ключ датчика: {exc}"]
        except Exception as exc:
            return "UNKNOWN", [str(exc)]

    def _poll_loop(self) -> None:
        while self._state.is_running:
            try:
                readings = self._simulator.get_readings()
                mode, anomalies = self._analyze(readings)

                record = SensorRecord(
                    timestamp=readings["timestamp"],
                    mode=mode,
                    anomalies=json.dumps(anomalies, ensure_ascii=False),
                    rpm=readings["rpm"],
                    exhaust_temp=readings["exhaust_temp"],
                    inlet_pressure=readings["inlet_pressure"],
                    fuel_flow=readings["fuel_flow"],
                    vibration=readings["vibration"],
                    iga_position=readings["iga_position"],
                )
                self._storage.save(record)

                with self._lock:
                    self._state.last_readings = readings
                    self._state.last_mode = mode
                    self._state.last_anomalies = anomalies
                    self._state.last_timestamp = readings["timestamp"]

                if anomalies:
                    self._logger.warning(f"[{mode}] Аномалии: {anomalies}")
                    for anomaly in anomalies:
                        param = anomaly.split(":")[0] if ":" in anomaly else "unknown"
                        self._audit.log_anomaly(
                            username="SYSTEM",
                            parameter=param,
                            value=0.0,
                            limit=0.0,
                            mode=mode
                        )
            except KeyError as exc:
                self._logger.error(f"_analyze: отсутствует ключ датчика {exc}")
            except Exception as exc:
                self._logger.error(f"Ошибка цикла опроса: {exc}")

            time.sleep(self._poll_interval)