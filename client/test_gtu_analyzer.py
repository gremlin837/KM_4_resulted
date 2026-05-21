
"""
Юнит-тесты для модуля классификации режимов и детекции аномалий ГТУ.
"""
import unittest
from gtu_analyzer import GTUAnalyzer, MODE_LIMITS


class TestModeClassification(unittest.TestCase):
    """
    Тестирование первичной классификации режима работы ГТУ.
    режим определяется ТОЛЬКО по rpm
    """

    def test_rpm_classification(self):
        """
            корректно ли программа распознает режим работы по rpm
        """
        cases = [
            # входное rpm, ожидаемый режим
            (0, "STOP"), (150, "TRANSITION"), (1500, "START"),
            (2800, "TRANSITION"), (3000, "IDLE"), (5500, "PARTIAL"),
            (8000, "NOMINAL"), (9000, "EMERGENCY"), (-1, "TRANSITION") # отриц значения = ошибка датчиков, переходное
        ]
        for rpm, expected in cases:
            # вызов анализатора. передаем только rpm, список аномалий не нужен
            mode, _ = GTUAnalyzer.classify(rpm, 20, 101, 0, 0.1, 0)

            # self.assertEqual проверяет точное совпадение двух значений.
            #  Если mode != expected, тест остановится и покажет сообщение об ошибке.
            self.assertEqual(mode, expected, f"Ошибка классификации для rpm={rpm}")

    def test_exact_boundaries(self):
        """
        проверка пограничных значений оборотов
        """
        boundaries = [
            (300, "START"), (2700, "START"),
            (2920, "IDLE"), (3080, "IDLE"),
            (4300, "PARTIAL"), (6700, "PARTIAL"),
            (7840, "NOMINAL"), (8160, "NOMINAL")
        ]
        for rpm, expected in boundaries:
            mode, _ = GTUAnalyzer.classify(rpm, 0, 0, 0, 0, 0)
            self.assertEqual(mode, expected)



class TestAnomalyDetection(unittest.TestCase):
    """Проверяет, правильно ли программа сравнивает показания датчиков
    с нормативами выбранного режима и фиксирует выходы за допуски"""

    def test_normal_operation(self):
        """ Подставляем средние значения режима IDLE, программа не должна выдавать проблем """
        mode, anomalies = GTUAnalyzer.classify(3000, 400, 120, 500, 2.05, 20)
        self.assertEqual(mode, "IDLE")
        self.assertEqual(anomalies, []) #проверка что список аномалий пуст

    def test_boundary_values_are_normal(self):
        """Пограничные значения должны быть инклюзивными(границы мин, мах включаются)
        Подставляем минимальные допустимые значения для режима IDLE
        """
        mode, anomalies = GTUAnalyzer.classify(2920, 384, 116, 484, 1.85, 18.4)
        self.assertEqual(mode, "IDLE")
        self.assertEqual(anomalies, [], "Границы нормативов должны считаться нормой")

    def test_single_anomaly(self):
        """
        Программа должна замечать одну аномалию
        Режим NOMINAL. Все параметры в норме, кроме температуры: 670°C (максимум нормы 666°C)
        Должно вывести 1 аномалию и какой именно параметр вышел за пределы
        """
        mode, anomalies = GTUAnalyzer.classify(8000, 670, 150, 2000, 4.0, 99)
        self.assertEqual(mode, "NOMINAL")
        self.assertEqual(len(anomalies), 1) # ровно 1 ошибка
        self.assertIn("Температура", anomalies[0])

    def test_multiple_anomalies(self):
        """
        Проверить работу при одновременной поломке нескольких систем.
        Программа не должна "терять" ошибки или останавливаться на первой.
        PARTITAL. Топливо ниже нормы, вибрация выше
        в списке должно выдать 2 записи об отклонениях
        """
        mode, anomalies = GTUAnalyzer.classify(5500, 500, 130, 550, 4.2, 50)
        self.assertEqual(mode, "PARTIAL")
        self.assertEqual(len(anomalies), 2)
        # есть ли в списке упоминания обоих параметров
        self.assertTrue(any("Топливо" in a for a in anomalies))
        self.assertTrue(any("Вибрация" in a for a in anomalies))

    def test_transition_skips_validation(self):
        """
        в переходном режиме валидация отключена
        обороты transition, но остальные параметры аварийны
        список аномалий должен быть пуст
        """
        mode, anomalies = GTUAnalyzer.classify(2800, 999, 999, 999, 99, 99)
        self.assertEqual(mode, "TRANSITION")
        self.assertEqual(anomalies, [])

    def test_emergency_skips_validation(self):
        """
        то же самое, но теперь в аварийном режиме
        """
        mode, anomalies = GTUAnalyzer.classify(9500, 999, 999, 999, 99, 99)
        self.assertEqual(mode, "EMERGENCY")
        self.assertEqual(anomalies, [])

    def test_stop_mode_validation(self):
        """В STOP всё должно быть нулевым или близким к нулю"""
        mode, anomalies = GTUAnalyzer.classify(0, 20, 102.5, 0, 0.1, 0)
        self.assertEqual(mode, "STOP")
        self.assertEqual(len(anomalies), 1)
        self.assertIn("Давление", anomalies[0])


class TestIntegration(unittest.TestCase):
    """правильно ли анализатор работает с реальными цифрами, которые генерирует симулятор
    (вывод из Приложения 1). Взяты рандомные значения
    """

    def test_idle_real_sample(self):
        mode, anomalies = GTUAnalyzer.classify(2986.95, 394.75, 119.43, 504.38, 2.15, 19.66)
        self.assertEqual(mode, "IDLE")
        self.assertEqual(anomalies, [])

    def test_nominal_with_anomaly(self):
        mode, anomalies = GTUAnalyzer.classify(8011.94, 665.73, 150.94, 1985.93, 4.29, 99.31)
        self.assertEqual(mode, "NOMINAL")
        self.assertEqual(len(anomalies), 1)
        self.assertIn("Вибрация", anomalies[0])

    def test_start_real_sample(self):
        mode, anomalies = GTUAnalyzer.classify(1543.84, 199.19, 108.12, 213.76, 1.02, 53.16)
        self.assertEqual(mode, "START")
        self.assertEqual(anomalies, [])

    def test_partial_real_sample(self):
        mode, anomalies = GTUAnalyzer.classify(5586.02, 550.72, 130.19, 947.16, 2.81, 51.05)
        self.assertEqual(mode, "PARTIAL")
        self.assertEqual(anomalies, [])


class TestLimitsStructure(unittest.TestCase):
    """Проверяет таблицу MODE_LIMITS.
    """

    def test_modes_exist(self):
        # В таблице есть все 5 обязательных режимов
        expected = {"STOP", "START", "IDLE", "PARTIAL", "NOMINAL"}
        self.assertEqual(set(MODE_LIMITS.keys()), expected)

    def test_params_exist(self):
        # Для каждого режима прописаны все 6 датчиков
        expected_keys = {"rpm", "T", "P", "fuel", "vib", "iga"}
        for mode, params in MODE_LIMITS.items():
            self.assertEqual(set(params.keys()), expected_keys, f"Отсутствуют параметры для {mode}")

    def test_min_less_max(self):
        # Min всегда должен быть ≤ Max
        for mode, params in MODE_LIMITS.items():
            for key, (mn, mx) in params.items():
                self.assertLessEqual(mn, mx, f"Ошибка в {mode}/{key}: Min={mn} > Max={mx}")


if __name__ == "__main__":
    unittest.main()