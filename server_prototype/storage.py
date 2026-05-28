"""
Хранилище данных на SQLite.
Схема: Timestamp | Mode | Anomalies | <показания датчиков>
"""

import sqlite3
import threading
import json
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class SensorRecord:
    timestamp: float
    mode: str
    anomalies: str          # JSON-список строк аномалий
    rpm: float
    exhaust_temp: float
    inlet_pressure: float
    fuel_flow: float
    vibration: float
    iga_position: float


class Storage:
    """
    Хранилище результатов анализа.
    Один экземпляр разделяется оркестратором и API.
    """

    _CREATE_SQL = """
        CREATE TABLE IF NOT EXISTS sensor_records (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp     REAL    NOT NULL,
            mode          TEXT    NOT NULL,
            anomalies     TEXT    NOT NULL,
            rpm           REAL,
            exhaust_temp  REAL,
            inlet_pressure REAL,
            fuel_flow     REAL,
            vibration     REAL,
            iga_position  REAL
        )
    """

    def __init__(self, db_path: str = "gtu_data.db") -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    # Инициализация

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(self._CREATE_SQL)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    # Запись

    def save(self, record: SensorRecord) -> None:
        sql = """
            INSERT INTO sensor_records
              (timestamp, mode, anomalies,
               rpm, exhaust_temp, inlet_pressure, fuel_flow, vibration, iga_position)
            VALUES (?,?,?,?,?,?,?,?,?)
        """
        with self._lock:
            with self._connect() as conn:
                conn.execute(sql, (
                    record.timestamp, record.mode, record.anomalies,
                    record.rpm, record.exhaust_temp, record.inlet_pressure,
                    record.fuel_flow, record.vibration, record.iga_position,
                ))

    # Чтение

    def get_latest(self, limit: int = 100) -> List[dict]:
        sql = """
            SELECT timestamp, mode, anomalies,
                   rpm, exhaust_temp, inlet_pressure, fuel_flow, vibration, iga_position
            FROM sensor_records
            ORDER BY timestamp DESC
            LIMIT ?
        """
        with self._lock:
            with self._connect() as conn:
                cursor = conn.execute(sql, (limit,))
                cols = [d[0] for d in cursor.description]
                rows = cursor.fetchall()
        records = []
        for row in rows:
            rec = dict(zip(cols, row))
            # Превращаем anomalies обратно в список для удобства клиента
            try:
                rec["anomalies"] = json.loads(rec["anomalies"])
            except (json.JSONDecodeError, TypeError):
                pass
            records.append(rec)
        return records

    def get_last_record(self) -> Optional[dict]:
        records = self.get_latest(1)
        return records[0] if records else None