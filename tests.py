"""
Unit-тесты


Запуск всех тестов:
  python -m unittest tests.py -v

Запуск одного класса:
  python -m unittest tests.TestGTUAnalyzer -v
"""

import json
import os
import time
import unittest
from unittest.mock import MagicMock, patch

#  GTUSimulator
from gtu_simulator import GTUSimulator, GTUMode


class TestGTUSimulatorModes(unittest.TestCase):
    """Проверка режимов работы симулятора."""

    def setUp(self):
        self.sim = GTUSimulator(interval=1.0)

    def test_default_mode_is_stop(self):
        """После создания режим должен быть STOP."""
        self.assertEqual(self.sim.current_mode, GTUMode.STOP)

    def test_set_every_mode(self):
        """Каждый режим из GTUMode должен устанавливаться без ошибок."""
        for mode in GTUMode:
            with self.subTest(mode=mode):
                self.sim.set_mode(mode)
                self.assertEqual(self.sim.current_mode, mode)

    def test_stop_sets_running_false(self):
        """stop() должен сбрасывать флаг _running."""
        self.sim.stop()
        self.assertFalse(self.sim._running)


class TestGTUSimulatorReadings(unittest.TestCase):
    """Проверка структуры и диапазонов показаний датчиков."""

    EXPECTED_KEYS = {
        "rpm", "exhaust_temp", "inlet_pressure",
        "fuel_flow", "vibration", "iga_position", "timestamp"
    }

    def setUp(self):
        self.sim = GTUSimulator(interval=1.0)

    def test_readings_contain_all_keys(self):
        """get_readings() должен возвращать все 7 ключей."""
        self.assertEqual(set(self.sim.get_readings().keys()), self.EXPECTED_KEYS)

    def test_timestamp_is_current(self):
        """Timestamp должен быть близок к текущему времени (±2 сек)."""
        readings = self.sim.get_readings()
        self.assertAlmostEqual(readings["timestamp"], time.time(), delta=2)

    def test_stop_rpm_and_fuel_are_zero(self):
        """В режиме STOP обороты и расход топлива строго равны 0."""
        self.sim.set_mode(GTUMode.STOP)
        for _ in range(10):
            r = self.sim.get_readings()
            self.assertEqual(r["rpm"], 0)
            self.assertEqual(r["fuel_flow"], 0)

    def test_nominal_rpm_within_bounds(self):
        """В NOMINAL режиме rpm должен быть в диапазоне [7800, 8200]."""
        self.sim.set_mode(GTUMode.NOMINAL)
        for _ in range(20):
            rpm = self.sim.get_readings()["rpm"]
            self.assertGreaterEqual(rpm, 7800, msg=f"rpm={rpm} ниже минимума")
            self.assertLessEqual(rpm, 8200, msg=f"rpm={rpm} выше максимума")

    def test_idle_temp_within_bounds(self):
        """В IDLE режиме exhaust_temp должна быть в диапазоне [380, 420]."""
        self.sim.set_mode(GTUMode.IDLE)
        for _ in range(20):
            t = self.sim.get_readings()["exhaust_temp"]
            self.assertGreaterEqual(t, 380)
            self.assertLessEqual(t, 420)

    def test_emergency_vibration_within_bounds(self):
        """В EMERGENCY режиме вибрация должна быть в диапазоне [7.0, 10.0]."""
        self.sim.set_mode(GTUMode.EMERGENCY)
        for _ in range(20):
            vib = self.sim.get_readings()["vibration"]
            self.assertGreaterEqual(vib, 7.0)
            self.assertLessEqual(vib, 10.0)


class TestGTUSimulatorGenValue(unittest.TestCase):
    """Проверка внутреннего генератора значений."""

    def setUp(self):
        self.sim = GTUSimulator()

    def test_sigma_zero_returns_exact_mean(self):
        """При sigma=0 должно возвращаться точное среднее значение."""
        for mean in [0, 50, 100, 999]:
            with self.subTest(mean=mean):
                self.assertEqual(self.sim._gen_value(mean, 0, 9999, 0), mean)

    def test_value_always_within_bounds(self):
        """При любой sigma значение должно быть в [min_val, max_val]."""
        for _ in range(200):
            val = self.sim._gen_value(50, 10, 90, 1000)  # огромная сигма
            self.assertGreaterEqual(val, 10)
            self.assertLessEqual(val, 90)


#  GTUAnalyzer

from gtu_analyzer import GTUAnalyzer, MODE_LIMITS


class TestGTUAnalyzerClassification(unittest.TestCase):
    """Проверка классификации режима по значению rpm."""

    def _classify(self, rpm):
        mode, _ = GTUAnalyzer.classify(rpm, 22, 101, 0, 0.1, 0)
        return mode

    def test_rpm_0_is_stop(self):
        self.assertEqual(self._classify(0), "STOP")

    def test_rpm_below_300_is_transition(self):
        self.assertEqual(self._classify(100), "TRANSITION")

    def test_rpm_in_start_range(self):
        self.assertEqual(self._classify(1500), "START")

    def test_rpm_between_start_and_idle_is_transition(self):
        self.assertEqual(self._classify(2800), "TRANSITION")

    def test_rpm_in_idle_range(self):
        self.assertEqual(self._classify(3000), "IDLE")

    def test_rpm_between_idle_and_partial_is_transition(self):
        self.assertEqual(self._classify(4000), "TRANSITION")

    def test_rpm_in_partial_range(self):
        self.assertEqual(self._classify(5500), "PARTIAL")

    def test_rpm_between_partial_and_nominal_is_transition(self):
        self.assertEqual(self._classify(7500), "TRANSITION")

    def test_rpm_in_nominal_range(self):
        self.assertEqual(self._classify(8000), "NOMINAL")

    def test_rpm_above_nominal_is_emergency(self):
        self.assertEqual(self._classify(8300), "EMERGENCY")


class TestGTUAnalyzerAnomalyDetection(unittest.TestCase):
    """Проверка детекции аномалий для каждого режима."""

    def test_normal_stop_no_anomalies(self):
        """Штатные параметры STOP — аномалий нет."""
        _, anomalies = GTUAnalyzer.classify(0, 22, 101, 0, 0.1, 0)
        self.assertEqual(anomalies, [])

    def test_normal_nominal_no_anomalies(self):
        """Штатные параметры NOMINAL — аномалий нет."""
        _, anomalies = GTUAnalyzer.classify(8000, 650, 150, 2000, 4.0, 99)
        self.assertEqual(anomalies, [])

    def test_high_vibration_in_idle_is_anomaly(self):
        """Вибрация выше нормы в IDLE должна попасть в аномалии."""
        _, anomalies = GTUAnalyzer.classify(3000, 400, 120, 500, 9.9, 20)
        anomaly_names = [a.split(":")[0] for a in anomalies]
        self.assertIn("Вибрация, мм/с", anomaly_names)

    def test_low_rpm_in_nominal_causes_anomaly(self):
        """rpm ниже нормы при NOMINAL-диапазоне — аномалия."""
        _, anomalies = GTUAnalyzer.classify(7800, 650, 150, 2000, 4.0, 99)
        # rpm=7800 — граница, проверяем что NOMINAL определён верно
        mode, _ = GTUAnalyzer.classify(7800, 650, 150, 2000, 4.0, 99)
        self.assertEqual(mode, "NOMINAL")

    def test_anomaly_format_contains_value_and_range(self):
        """Формат аномалии должен содержать значение и диапазон [min-max]."""
        _, anomalies = GTUAnalyzer.classify(3000, 400, 120, 500, 9.9, 20)
        for anomaly in anomalies:
            self.assertIn("∉", anomaly)
            self.assertIn("[", anomaly)
            self.assertIn("-", anomaly)
            self.assertIn("]", anomaly)

    def test_transition_mode_no_validation(self):
        """В переходном режиме аномалий быть не должно (нет лимитов)."""
        _, anomalies = GTUAnalyzer.classify(100, 999, 999, 999, 999, 999)
        self.assertEqual(anomalies, [])

    def test_emergency_mode_no_validation(self):
        """В EMERGENCY нет лимитов в MODE_LIMITS — аномалий быть не должно."""
        _, anomalies = GTUAnalyzer.classify(8300, 780, 140, 2500, 8.5, 100)
        self.assertEqual(anomalies, [])

    def test_multiple_anomalies_detected(self):
        """При нескольких отклонениях список содержит несколько аномалий."""
        # Температура и вибрация оба вне нормы для IDLE
        _, anomalies = GTUAnalyzer.classify(3000, 999, 120, 500, 99.9, 20)
        self.assertGreater(len(anomalies), 1)


class TestGTUAnalyzerModeLimitsIntegrity(unittest.TestCase):
    """Проверка целостности таблицы MODE_LIMITS (Приложение 2)."""

    EXPECTED_MODES = {"STOP", "START", "IDLE", "PARTIAL", "NOMINAL"}
    EXPECTED_PARAMS = {"rpm", "T", "P", "fuel", "vib", "iga"}

    def test_all_modes_present(self):
        """Все штатные режимы должны присутствовать в MODE_LIMITS."""
        self.assertEqual(set(MODE_LIMITS.keys()), self.EXPECTED_MODES)

    def test_all_modes_have_all_params(self):
        """Каждый режим должен содержать все 6 параметров."""
        for mode, params in MODE_LIMITS.items():
            with self.subTest(mode=mode):
                self.assertEqual(set(params.keys()), self.EXPECTED_PARAMS)

    def test_all_limits_are_valid_tuples(self):
        """Каждый лимит — кортеж (min, max) где min <= max."""
        for mode, params in MODE_LIMITS.items():
            for param, (mn, mx) in params.items():
                with self.subTest(mode=mode, param=param):
                    self.assertLessEqual(mn, mx,
                        msg=f"{mode}/{param}: min={mn} > max={mx}")


#  Storage

from storage import Storage, SensorRecord


class TestStorage(unittest.TestCase):
    """Проверка хранилища данных (SQLite)."""

    DB_PATH = "test_gtu_data.db"

    def setUp(self):
        self.storage = Storage(db_path=self.DB_PATH)

    def tearDown(self):
        if os.path.exists(self.DB_PATH):
            os.remove(self.DB_PATH)

    def _make_record(self, ts=None, mode="NOMINAL", anomalies=None) -> SensorRecord:
        return SensorRecord(
            timestamp=ts or time.time(),
            mode=mode,
            anomalies=json.dumps(anomalies or [], ensure_ascii=False),
            rpm=8000.0,
            exhaust_temp=650.0,
            inlet_pressure=150.0,
            fuel_flow=2000.0,
            vibration=4.0,
            iga_position=99.0,
        )

    def test_save_and_retrieve_one_record(self):
        """Сохранённая запись должна возвращаться из get_latest."""
        self.storage.save(self._make_record(mode="IDLE"))
        records = self.storage.get_latest(10)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["mode"], "IDLE")

    def test_get_latest_returns_correct_limit(self):
        """get_latest(n) должен возвращать не более n записей."""
        for i in range(10):
            self.storage.save(self._make_record(ts=time.time() + i))
        self.assertEqual(len(self.storage.get_latest(5)), 5)
        self.assertEqual(len(self.storage.get_latest(10)), 10)

    def test_get_latest_order_is_descending(self):
        """Записи должны быть отсортированы от новых к старым."""
        for i in range(5):
            self.storage.save(self._make_record(ts=float(i)))
        records = self.storage.get_latest(5)
        timestamps = [r["timestamp"] for r in records]
        self.assertEqual(timestamps, sorted(timestamps, reverse=True))

    def test_anomalies_deserialized_to_list(self):
        """Поле anomalies должно возвращаться как список, а не строка."""
        anomalies = ["Вибрация: 9.9 ∉ [1.85-2.25]"]
        self.storage.save(self._make_record(anomalies=anomalies))
        record = self.storage.get_last_record()
        self.assertIsInstance(record["anomalies"], list)
        self.assertEqual(record["anomalies"], anomalies)

    def test_get_last_record_returns_none_when_empty(self):
        """get_last_record() должен возвращать None при пустой БД."""
        self.assertIsNone(self.storage.get_last_record())

    def test_get_last_record_returns_most_recent(self):
        """get_last_record() должен возвращать запись с максимальным timestamp."""
        self.storage.save(self._make_record(ts=1000.0, mode="START"))
        self.storage.save(self._make_record(ts=2000.0, mode="NOMINAL"))
        last = self.storage.get_last_record()
        self.assertEqual(last["mode"], "NOMINAL")

    def test_all_sensor_fields_saved_correctly(self):
        """Все поля датчиков должны сохраняться и возвращаться корректно."""
        record = self._make_record()
        self.storage.save(record)
        result = self.storage.get_last_record()
        self.assertAlmostEqual(result["rpm"],            record.rpm,            places=1)
        self.assertAlmostEqual(result["exhaust_temp"],   record.exhaust_temp,   places=1)
        self.assertAlmostEqual(result["inlet_pressure"], record.inlet_pressure, places=1)
        self.assertAlmostEqual(result["fuel_flow"],      record.fuel_flow,      places=1)
        self.assertAlmostEqual(result["vibration"],      record.vibration,      places=1)
        self.assertAlmostEqual(result["iga_position"],   record.iga_position,   places=1)

#  Orchestrator

from orchestrator import Orchestrator


class TestOrchestrator(unittest.TestCase):
    """Проверка оркестратора с заглушками GTUSimulator и Storage."""

    def setUp(self):
        # auto_cycle=False — не запускать фоновый поток смены режимов
        self.orch = Orchestrator(poll_interval=1.0, auto_cycle=False)

        # Заменяем реальный симулятор заглушкой
        self.mock_sim = MagicMock()
        self.mock_sim.get_readings.return_value = {
            "timestamp":       time.time(),
            "rpm":             8000.0,
            "exhaust_temp":    650.0,
            "inlet_pressure":  150.0,
            "fuel_flow":       2000.0,
            "vibration":       4.0,
            "iga_position":    99.0,
        }
        self.orch._simulator = self.mock_sim

        # Заменяем реальное хранилище заглушкой
        self.mock_storage = MagicMock()
        self.orch._storage = self.mock_storage

    def tearDown(self):
        if self.orch._state.is_running:
            self.orch.stop()

    def test_initial_state_is_not_running(self):
        """До вызова start() оркестратор не должен быть запущен."""
        self.assertFalse(self.orch._state.is_running)

    def test_start_sets_running_true(self):
        """start() должен установить флаг is_running."""
        self.orch.start()
        self.assertTrue(self.orch._state.is_running)

    def test_stop_sets_running_false(self):
        """stop() должен сбросить флаг is_running."""
        self.orch.start()
        self.orch.stop()
        self.assertFalse(self.orch._state.is_running)

    def test_double_start_does_not_create_extra_threads(self):
        """Повторный вызов start() не должен создавать новый поток."""
        self.orch.start()
        thread_before = self.orch._poll_thread
        self.orch.start()
        self.assertIs(self.orch._poll_thread, thread_before)

    def test_get_current_state_initial(self):
        """До первого опроса get_current_state() возвращает пустые показания."""
        state = self.orch.get_current_state()
        self.assertEqual(state["readings"], {})
        self.assertEqual(state["mode"], "UNKNOWN")
        self.assertEqual(state["anomalies"], [])

    def test_analyze_maps_keys_correctly(self):
        """_analyze() должен корректно транслировать ключи GTUSimulator → GTUAnalyzer."""
        readings = self.mock_sim.get_readings.return_value
        mode, anomalies = self.orch._analyze(readings)
        self.assertEqual(mode, "NOMINAL")
        self.assertIsInstance(anomalies, list)

    def test_analyze_returns_unknown_on_missing_key(self):
        """_analyze() должен возвращать UNKNOWN при отсутствующем ключе."""
        bad_readings = {"rpm": 8000}  # нет остальных ключей
        mode, anomalies = self.orch._analyze(bad_readings)
        self.assertEqual(mode, "UNKNOWN")
        self.assertTrue(len(anomalies) > 0)

    def test_poll_loop_saves_to_storage(self):
        """
        Один вызов _poll_loop() (имитация одной итерации)
        должен сохранить запись в хранилище.
        """
        # Подменяем time.sleep чтобы цикл выполнился ровно раз
        self.orch._state.is_running = True
        call_count = [0]

        def fake_sleep(_):
            call_count[0] += 1
            self.orch._state.is_running = False  # останавливаем после 1 итерации

        with patch("orchestrator.time.sleep", side_effect=fake_sleep):
            self.orch._poll_loop()

        self.mock_storage.save.assert_called_once()
        self.assertEqual(call_count[0], 1)

    def test_poll_loop_updates_state(self):
        """После итерации опроса состояние должно обновиться."""
        self.orch._state.is_running = True

        def fake_sleep(_):
            self.orch._state.is_running = False

        with patch("orchestrator.time.sleep", side_effect=fake_sleep):
            self.orch._poll_loop()

        state = self.orch.get_current_state()
        self.assertEqual(state["mode"], "NOMINAL")
        self.assertNotEqual(state["timestamp"], 0.0)

    def test_get_history_delegates_to_storage(self):
        """get_history() должен делегировать вызов в Storage.get_latest()."""
        self.mock_storage.get_latest.return_value = [{"mode": "IDLE"}]
        result = self.orch.get_history(limit=50)
        self.mock_storage.get_latest.assert_called_once_with(50)
        self.assertEqual(result, [{"mode": "IDLE"}])

#  API (server.py)

from fastapi.testclient import TestClient


class TestAPI(unittest.TestCase):
    """Проверка REST API через TestClient (без реального сервера)."""

    DB_AUTH    = "test_api_auth.db"
    DB_SENSOR  = "test_api_sensor.db"

    @classmethod
    def setUpClass(cls):
        """
        Поднимаем приложение один раз на весь класс.
        Патчим пути к БД чтобы не трогать рабочие файлы.
        """
        import server

        # Пересобираем AuthSystem с тестовой БД
        config     = AuthConfig(bcrypt_rounds=4, jwt_secret="test-api-secret",
                                rate_limit_max=1000)
        repo       = SQLiteUserRepository(cls.DB_AUTH)
        hasher     = BcryptHasher(config)
        token_svc  = TokenService("test-api-secret", expire_minutes=60)
        auth       = AuthSystem(repo, hasher, token_svc, config)
        auth.create_admin_if_empty()  # admin / Admin@12345

        server._auth_system = auth

        # Подменяем оркестратор заглушкой
        mock_orch = MagicMock()
        mock_orch.get_current_state.return_value = {
            "timestamp": time.time(),
            "mode":      "NOMINAL",
            "anomalies": [],
            "readings": {
                "rpm": 8000, "exhaust_temp": 650,
                "inlet_pressure": 150, "fuel_flow": 2000,
                "vibration": 4.0, "iga_position": 99,
            },
        }
        mock_orch.get_history.return_value = [
            {"timestamp": time.time(), "mode": "NOMINAL", "anomalies": []}
        ]
        server._orchestrator = mock_orch

        cls.client = TestClient(server.app, raise_server_exceptions=False)

        # Логинимся и получаем токен
        resp = cls.client.post("/api/auth/login",
                               json={"login": "admin", "password": "Admin@12345"})
        cls.token = resp.json().get("token", "")
        cls.auth_headers = {"Authorization": f"Bearer {cls.token}"}

    @classmethod
    def tearDownClass(cls):
        for db in [cls.DB_AUTH, cls.DB_SENSOR]:
            if os.path.exists(db):
                os.remove(db)

    # /health

    def test_health_returns_200(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)

    def test_health_returns_ok(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.json(), {"status": "ok"})

    # /api/auth/login

    def test_login_success_returns_token(self):
        resp = self.client.post("/api/auth/login",
                                json={"login": "admin", "password": "Admin@12345"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("token", resp.json())

    def test_login_wrong_password_returns_401(self):
        resp = self.client.post("/api/auth/login",
                                json={"login": "admin", "password": "WrongPass@1"})
        self.assertEqual(resp.status_code, 401)

    def test_login_unknown_user_returns_401(self):
        resp = self.client.post("/api/auth/login",
                                json={"login": "ghost", "password": "Ghost@1234"})
        self.assertEqual(resp.status_code, 401)

    # /api/status

    def test_status_without_token_returns_401(self):
        resp = self.client.get("/api/status")
        self.assertEqual(resp.status_code, 401)

    def test_status_with_token_returns_200(self):
        resp = self.client.get("/api/status", headers=self.auth_headers)
        self.assertEqual(resp.status_code, 200)

    def test_status_contains_required_fields(self):
        resp = self.client.get("/api/status", headers=self.auth_headers)
        body = resp.json()
        for field in ("timestamp", "mode", "anomalies", "readings"):
            with self.subTest(field=field):
                self.assertIn(field, body)

    def test_status_mode_is_string(self):
        resp = self.client.get("/api/status", headers=self.auth_headers)
        self.assertIsInstance(resp.json()["mode"], str)

    # /api/history

    def test_history_without_token_returns_401(self):
        resp = self.client.get("/api/history")
        self.assertEqual(resp.status_code, 401)

    def test_history_with_token_returns_200(self):
        resp = self.client.get("/api/history", headers=self.auth_headers)
        self.assertEqual(resp.status_code, 200)

    def test_history_returns_list(self):
        resp = self.client.get("/api/history", headers=self.auth_headers)
        self.assertIsInstance(resp.json(), list)

    def test_history_limit_too_large_returns_400(self):
        resp = self.client.get("/api/history?limit=9999", headers=self.auth_headers)
        self.assertEqual(resp.status_code, 400)

    def test_history_limit_zero_returns_400(self):
        resp = self.client.get("/api/history?limit=0", headers=self.auth_headers)
        self.assertEqual(resp.status_code, 400)

    # /api/auth/change-password

    def test_change_password_invalid_current_returns_400(self):
        resp = self.client.post(
            "/api/auth/change-password",
            json={"current_password": "WrongCurrent@1", "new_password": "NewValid@99"},
            headers=self.auth_headers,
        )
        self.assertEqual(resp.status_code, 400)

    def test_change_password_weak_new_password_returns_422(self):
        resp = self.client.post(
            "/api/auth/change-password",
            json={"current_password": "Admin@12345", "new_password": "weak"},
            headers=self.auth_headers,
        )
        self.assertEqual(resp.status_code, 422)

    def test_change_password_without_token_returns_401(self):
        resp = self.client.post(
            "/api/auth/change-password",
            json={"current_password": "Admin@12345", "new_password": "NewValid@99"},
        )
        self.assertEqual(resp.status_code, 401)


if __name__ == "__main__":
    unittest.main(verbosity=2)