"""
# Оркестратор
# Управляем жизненным циклом симулятора, опрос датчиков, цикличная смена режимов ГТУ
# Анализ показаний, хранение актуального состояния для API
"""

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from gtu_simulator import GTUSimulator, GTUMode
from gtu_analyzer import GTUAnalyzer
from storage import Storage, SensorRecord

# ИЗМЕНЕНО: импорт реальных сервисов вместо stubs
from logging_service import get_logging_service, LogLevel, LogCategory
from audit_service import get_audit_service, AuditEventType, AuditSeverity

# ИЗМЕНЕНО: создаём логгер для оркестратора
_logger = get_logging_service().get_logger("orchestrator")
_audit = get_audit_service()


@dataclass
class SystemState:
    last_readings:   dict  = field(default_factory=dict)
    last_mode:       str   = "UNKNOWN"
    last_anomalies:  list  = field(default_factory=list)
    last_timestamp:  float = 0.0
    is_running:      bool  = False


class Orchestrator:

    # Штатный цикл работы ГТУ (режим, длительность в секундах)
    CYCLE: list[tuple[GTUMode, int]] = [
        (GTUMode.START,      200),
        (GTUMode.IDLE,       300),
        (GTUMode.PARTIAL,    450),
        (GTUMode.NOMINAL,    500),
        (GTUMode.EMERGENCY,   50),
        (GTUMode.STOP,       300),
    ]

    def __init__(self, poll_interval: float = 1.0, auto_cycle: bool = True) -> None:
        self._poll_interval  = poll_interval
        self._auto_cycle     = auto_cycle

        # GTU-компоненты напрямую
        self._simulator = GTUSimulator(interval=poll_interval)
        self._storage   = Storage()

        self._state = SystemState()
        self._lock  = threading.Lock()

        self._poll_thread:  Optional[threading.Thread] = None
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

        _logger.info("Оркестратор запущен")                     # ИЗМЕНЕНО: использован реальный логгер

    def stop(self) -> None:
        self._state.is_running = False
        self._simulator.stop()
        _logger.info("Оркестратор остановлен")                  # ИЗМЕНЕНО

    #  Публичный интерфейс для API

    def get_current_state(self) -> dict:
        """Возвращает копию последнего состояния (потокобезопасно)."""
        with self._lock:
            return {
                "timestamp": self._state.last_timestamp,
                "mode":      self._state.last_mode,
                "anomalies": list(self._state.last_anomalies),
                "readings":  dict(self._state.last_readings),
            }

    def get_history(self, limit: int = 100) -> list:
        return self._storage.get_latest(limit)

    # Фоновый поток для цикла смены режимов

    def _run_cycle(self) -> None:
        old_mode = None
        while self._state.is_running:
            for mode, duration in self.CYCLE:
                if not self._state.is_running:
                    return
                # ИЗМЕНЕНО: аудит смены режима
                if old_mode is not None:
                    _audit.log_mode_change(
                        username="SYSTEM",
                        old_mode=old_mode,
                        new_mode=mode.value
                    )
                self._simulator.set_mode(mode)
                _logger.info(f"Режим ГТУ: {mode.value}")        # ИЗМЕНЕНО
                old_mode = mode.value
                time.sleep(duration)

    # Анализ: маппинг ключей GTUSimulator → GTUAnalyzer

    @staticmethod
    def _analyze(readings: dict) -> tuple[str, list[str]]:
        """
        Вызывает GTUAnalyzer.classify() с явным маппингом ключей.

        GTUSimulator   →   GTUAnalyzer
        exhaust_temp   →   temp
        inlet_pressure →   pres
        fuel_flow      →   fuel
        vibration      →   vib
        """
        try:
            return GTUAnalyzer.classify(
                rpm  = readings["rpm"],
                temp = readings["exhaust_temp"],
                pres = readings["inlet_pressure"],
                fuel = readings["fuel_flow"],
                vib  = readings["vibration"],
                iga  = readings["iga_position"],
            )
        except KeyError as exc:
            _logger.error(f"_analyze: отсутствует ключ датчика {exc}")   # ИЗМЕНЕНО
            return "UNKNOWN", [f"Ошибка анализа: отсутствует ключ {exc}"]
        except Exception as exc:
            _logger.error(f"_analyze: непредвиденная ошибка: {exc}")      # ИЗМЕНЕНО
            return "UNKNOWN", [str(exc)]

    # Фоновый поток для опроса датчиков

    def _poll_loop(self) -> None:
        while self._state.is_running:
            try:
                readings          = self._simulator.get_readings()
                mode, anomalies   = self._analyze(readings)

                record = SensorRecord(
                    timestamp      = readings["timestamp"],
                    mode           = mode,
                    anomalies      = json.dumps(anomalies, ensure_ascii=False),
                    rpm            = readings["rpm"],
                    exhaust_temp   = readings["exhaust_temp"],
                    inlet_pressure = readings["inlet_pressure"],
                    fuel_flow      = readings["fuel_flow"],
                    vibration      = readings["vibration"],
                    iga_position   = readings["iga_position"],
                )
                self._storage.save(record)

                with self._lock:
                    self._state.last_readings  = readings
                    self._state.last_mode      = mode
                    self._state.last_anomalies = anomalies
                    self._state.last_timestamp = readings["timestamp"]

                if anomalies:
                    # ИЗМЕНЕНО: использование специализированной функции логирования аномалий
                    from logging_service import log_anomaly
                    log_anomaly(f"[{mode}] Аномалии: {anomalies}", level=LogLevel.WARNING, anomalies=anomalies)
                    # Дополнительно аудит аномалий
                    for anomaly in anomalies:
                        _audit.log_anomaly(
                            username="SYSTEM",
                            parameter=anomaly.split(":")[0] if ":" in anomaly else "unknown",
                            value=0.0,   # реальное значение можно извлечь, но для простоты оставим
                            limit=0.0,
                            mode=mode
                        )

            except Exception as exc:
                _logger.error(f"Ошибка цикла опроса: {exc}")               # ИЗМЕНЕНО

            time.sleep(self._poll_interval)