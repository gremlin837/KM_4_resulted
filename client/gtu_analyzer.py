"""
Модуль выполняет валидацию как всех параметров(минимальное и максимальное значения),
так и определяет режим работы ГТУ
"""

# JSON с диапазонами для каждого режима работы ГТУ
MODE_LIMITS = {
    "STOP":      {"rpm": (0, 0), "T": (16.5, 28.5), "P": (100.2, 101.8), "fuel": (0, 0), "vib": (0.02, 0.18), "iga": (0, 0)},
    "START":     {"rpm": (300, 2700), "T": (58, 362), "P": (102, 118), "fuel": (50, 450), "vib": (0.65, 1.85), "iga": (10, 90)},
    "IDLE":      {"rpm": (2920, 3080), "T": (384, 416), "P": (116, 124), "fuel": (484, 516), "vib": (1.85, 2.25), "iga": (18.4, 21.6)},
    "PARTIAL":   {"rpm": (4300, 6700), "T": (420, 580), "P": (122, 138), "fuel": (600, 1400), "vib": (2.2, 3.8), "iga": (26, 74)},
    "NOMINAL":   {"rpm": (7840, 8160), "T": (634, 666), "P": (148.4, 151.6), "fuel": (1960, 2040), "vib": (3.85, 4.25), "iga": (98.2, 99.8)}
}

class GTUAnalyzer:

    """ Класс как статический анализатор (не сохраняет состояние)
    принимает мгновенные показания шести датчиков и возвращает:
     1) текущий режим работы ГТУ
     2) список выявленных отклонений от нормы list[str]
    """

    @staticmethod
    def classify(rpm, temp, pres, fuel, vib, iga):
        # Первичная классификация по оборотам (основной индикатор)
        if rpm == 0:
            mode = "STOP"
        elif rpm < 300:
            mode = "TRANSITION" # Переходный режим (промежуточное состояние оборотов ГТУ)
        elif rpm <= 2700:
            mode = "START"
        elif rpm < 2920:
            mode = "TRANSITION"
        elif rpm <= 3080:
            mode = "IDLE"
        elif rpm < 4300:
            mode = "TRANSITION"
        elif rpm <= 6700:
            mode = "PARTIAL"
        elif rpm < 7840:
            mode = "TRANSITION"
        elif rpm <= 8160:
            mode = "NOMINAL"
        else:
            mode = "EMERGENCY"

        # Валидация параметров против нормативов выбранного режима
        anomalies = []
        params_map = [
            ("Об/мин", rpm, "rpm"),
            ("Температура, °C", temp, "T"),
            ("Давление, кПа", pres, "P"),
            ("Топливо, кг/ч", fuel, "fuel"),
            ("Вибрация, мм/с", vib, "vib"),
            ("IGA, %", iga, "iga")
        ]

        limits = MODE_LIMITS.get(mode) # Получение вложенного словаря из MODE_LIMITS
        # Кортеж (Max_normal, Min_normal). Если режим не найден, вернет None
        # ядро валидации
        if limits:
            for name, val, key in params_map:
                if key in limits:
                    mn, mx = limits[key]
                    if val < mn or val > mx:
                        anomalies.append(f"{name}: {val:.1f} ∉ [{mn:.1f}-{mx:.1f}]")

        return mode, anomalies