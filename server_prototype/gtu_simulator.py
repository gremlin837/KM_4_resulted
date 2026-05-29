
#!/usr/bin/env python3
import time
import random
import signal
import sys
import threading
from enum import Enum

class GTUMode(Enum):
    STOP = "STOP"
    START = "START"
    IDLE = "IDLE"
    PARTIAL = "PARTIAL"
    NOMINAL = "NOMINAL"
    EMERGENCY = "EMERGENCY"

class GTUSimulator:
    _PARAMS = {
        GTUMode.STOP: {
            "rpm": (0, 0, 0, 0),
            "exhaust_temp": (20, 15, 30, 1.0),
            "inlet_pressure": (101.3, 100, 102, 0.5),
            "fuel_flow": (0, 0, 0, 0),
            "vibration": (0, 0, 0.2, 0.05),
            "iga_position": (0, 0, 0, 0)
        },
        GTUMode.START: {
            "rpm": (1500, 0, 3000, 50),
            "exhaust_temp": (200, 20, 400, 15),
            "inlet_pressure": (110, 100, 120, 1.0),
            "fuel_flow": (250, 0, 500, 20),
            "vibration": (1.0, 0.5, 2.0, 0.1),
            "iga_position": (50, 0, 100, 5)
        },
        GTUMode.IDLE: {
            "rpm": (3000, 2900, 3100, 20),
            "exhaust_temp": (400, 380, 420, 8),
            "inlet_pressure": (120, 115, 125, 1.0),
            "fuel_flow": (500, 480, 520, 10),
            "vibration": (2.0, 1.8, 2.3, 0.1),
            "iga_position": (20, 18, 22, 1)
        },
        GTUMode.PARTIAL: {
            "rpm": (5500, 4000, 7000, 100),
            "exhaust_temp": (500, 400, 600, 20),
            "inlet_pressure": (130, 120, 140, 2),
            "fuel_flow": (1000, 500, 1500, 50),
            "vibration": (3.0, 2.0, 4.0, 0.2),
            "iga_position": (50, 20, 80, 3)
        },
        GTUMode.NOMINAL: {
            "rpm": (8000, 7800, 8200, 30),
            "exhaust_temp": (650, 630, 670, 10),
            "inlet_pressure": (150, 148, 152, 1),
            "fuel_flow": (2000, 1950, 2050, 30),
            "vibration": (4.0, 3.8, 4.3, 0.1),
            "iga_position": (100, 98, 100, 0.5)
        },
        GTUMode.EMERGENCY: {
            "rpm": (8200, 8000, 8500, 50),
            "exhaust_temp": (780, 750, 820, 15),
            "inlet_pressure": (140, 130, 150, 3),
            "fuel_flow": (2500, 2300, 2700, 100),
            "vibration": (8.5, 7.0, 10.0, 0.5),
            "iga_position": (100, 95, 100, 2)
        }
    }

    def __init__(self, interval=10.0):
        self.interval = interval
        self.current_mode = GTUMode.STOP
        self._running = True

    def set_mode(self, mode: GTUMode):
        self.current_mode = mode

    def _gen_value(self, mean, min_val, max_val, sigma):
        if sigma == 0:
            return mean
        val = random.gauss(mean, sigma)
        return max(min_val, min(max_val, val))

    def get_readings(self):
        params = self._PARAMS[self.current_mode]
        readings = {}
        for name, (mean, minv, maxv, sigma) in params.items():
            readings[name] = round(self._gen_value(mean, minv, maxv, sigma), 2)
        readings["timestamp"] = time.time()
        return readings

    def run(self):
        while self._running:
            data = self.get_readings()
            print(f"{data['timestamp']:.1f} | "
                  f"об/мин={data['rpm']} | T={data['exhaust_temp']}°C | "
                  f"P={data['inlet_pressure']}кПа | "
                  f"топливо={data['fuel_flow']}кг/ч | "
                  f"вибрация={data['vibration']}мм/с | "
                  f"IGA={data['iga_position']}%")
            time.sleep(self.interval)

    def stop(self):
        self._running = False

# -------------------------------------------------------------------
def main():
    # Настройки
    CYCLE = [              # последовательность (режим, длительность_сек)
        (GTUMode.START, 200),
        (GTUMode.IDLE, 300),
        (GTUMode.PARTIAL, 450),
        (GTUMode.NOMINAL, 500),
        (GTUMode.EMERGENCY, 50),
        (GTUMode.STOP, 300)
    ]

    sim = GTUSimulator(interval = 1)

    # Фоновый поток для циклической смены режимов
    def cycle_worker():
        while True:
            for mode, duration in CYCLE:
                sim.set_mode(mode)
                time.sleep(duration)

    thread = threading.Thread(target=cycle_worker, daemon=True)
    thread.start()

    # Обработка Ctrl+C
    def shutdown(signum, frame):
        print("\nОстановка симулятора...", file=sys.stderr)
        sim.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # бесконечная генерация
    sim.run()

if __name__ == "__main__":
    main()