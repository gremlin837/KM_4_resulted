"""
Unit-тесты для серверной части системы мониторинга ГТУ.

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

from gtu_simulator import GTUSimulator, GTUMode
from gtu_analyzer import GTUAnalyzer, MODE_LIMITS
from storage import Storage, SensorRecord
from orchestrator import Orchestrator
from auth_system_united import (
    AuthConfig, BcryptHasher, TokenService,
    SQLiteUserRepository, AuthSystem
)
from audit_service import AuditEventType, AuditSeverity
import server

from fastapi.testclient import TestClient


# 1. Тесты симулятора ГТУ

class TestGTUSimulatorModes(unittest.TestCase):
    """Проверка режимов работы симулятора."""

    def setUp(self):
        self.sim = GTUSimulator(interval=1.0)

    def test_default_mode_is_stop(self):
        self.assertEqual(self.sim.current_mode, GTUMode.STOP)

    def test_set_every_mode(self):
        for mode in GTUMode:
            with self.subTest(mode=mode):
                self.sim.set_mode(mode)
                self.assertEqual(self.sim.current_mode, mode)

    def test_stop_sets_running_false(self):
        self.sim.stop()
        self.assertFalse(self.sim._running)


class TestGTUSimulatorReadings(unittest.TestCase):
    EXPECTED_KEYS = {
        "rpm", "exhaust_temp", "inlet_pressure",
        "fuel_flow", "vibration", "iga_position", "timestamp"
    }

    def setUp(self):
        self.sim = GTUSimulator(interval=1.0)

    def test_readings_contain_all_keys(self):
        self.assertEqual(set(self.sim.get_readings().keys()), self.EXPECTED_KEYS)

    def test_timestamp_is_current(self):
        readings = self.sim.get_readings()
        self.assertAlmostEqual(readings["timestamp"], time.time(), delta=2)

    def test_stop_rpm_and_fuel_are_zero(self):
        self.sim.set_mode(GTUMode.STOP)
        for _ in range(10):
            r = self.sim.get_readings()
            self.assertEqual(r["rpm"], 0)
            self.assertEqual(r["fuel_flow"], 0)

    def test_nominal_rpm_within_bounds(self):
        self.sim.set_mode(GTUMode.NOMINAL)
        for _ in range(20):
            rpm = self.sim.get_readings()["rpm"]
            self.assertGreaterEqual(rpm, 7800)
            self.assertLessEqual(rpm, 8200)

    def test_idle_temp_within_bounds(self):
        self.sim.set_mode(GTUMode.IDLE)
        for _ in range(20):
            t = self.sim.get_readings()["exhaust_temp"]
            self.assertGreaterEqual(t, 380)
            self.assertLessEqual(t, 420)

    def test_emergency_vibration_within_bounds(self):
        self.sim.set_mode(GTUMode.EMERGENCY)
        for _ in range(20):
            vib = self.sim.get_readings()["vibration"]
            self.assertGreaterEqual(vib, 7.0)
            self.assertLessEqual(vib, 10.0)


class TestGTUSimulatorGenValue(unittest.TestCase):
    def setUp(self):
        self.sim = GTUSimulator()

    def test_sigma_zero_returns_exact_mean(self):
        for mean in [0, 50, 100, 999]:
            with self.subTest(mean=mean):
                self.assertEqual(self.sim._gen_value(mean, 0, 9999, 0), mean)

    def test_value_always_within_bounds(self):
        for _ in range(200):
            val = self.sim._gen_value(50, 10, 90, 1000)
            self.assertGreaterEqual(val, 10)
            self.assertLessEqual(val, 90)


# Тесты анализатора

class TestGTUAnalyzerClassification(unittest.TestCase):
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
    def test_normal_stop_no_anomalies(self):
        _, anomalies = GTUAnalyzer.classify(0, 22, 101, 0, 0.1, 0)
        self.assertEqual(anomalies, [])

    def test_normal_nominal_no_anomalies(self):
        _, anomalies = GTUAnalyzer.classify(8000, 650, 150, 2000, 4.0, 99)
        self.assertEqual(anomalies, [])

    def test_high_vibration_in_idle_is_anomaly(self):
        _, anomalies = GTUAnalyzer.classify(3000, 400, 120, 500, 9.9, 20)
        anomaly_names = [a.split(":")[0] for a in anomalies]
        self.assertIn("Вибрация, мм/с", anomaly_names)

    def test_anomaly_format_contains_value_and_range(self):
        _, anomalies = GTUAnalyzer.classify(3000, 400, 120, 500, 9.9, 20)
        for anomaly in anomalies:
            self.assertIn("∉", anomaly)
            self.assertIn("[", anomaly)
            self.assertIn("-", anomaly)
            self.assertIn("]", anomaly)

    def test_transition_mode_no_validation(self):
        _, anomalies = GTUAnalyzer.classify(100, 999, 999, 999, 999, 999)
        self.assertEqual(anomalies, [])

    def test_emergency_mode_no_validation(self):
        _, anomalies = GTUAnalyzer.classify(8300, 780, 140, 2500, 8.5, 100)
        self.assertEqual(anomalies, [])

    def test_multiple_anomalies_detected(self):
        _, anomalies = GTUAnalyzer.classify(3000, 999, 120, 500, 99.9, 20)
        self.assertGreater(len(anomalies), 1)


class TestGTUAnalyzerModeLimitsIntegrity(unittest.TestCase):
    EXPECTED_MODES = {"STOP", "START", "IDLE", "PARTIAL", "NOMINAL"}
    EXPECTED_PARAMS = {"rpm", "T", "P", "fuel", "vib", "iga"}

    def test_all_modes_present(self):
        self.assertEqual(set(MODE_LIMITS.keys()), self.EXPECTED_MODES)

    def test_all_modes_have_all_params(self):
        for mode, params in MODE_LIMITS.items():
            with self.subTest(mode=mode):
                self.assertEqual(set(params.keys()), self.EXPECTED_PARAMS)

    def test_all_limits_are_valid_tuples(self):
        for mode, params in MODE_LIMITS.items():
            for param, (mn, mx) in params.items():
                with self.subTest(mode=mode, param=param):
                    self.assertLessEqual(mn, mx)


# 3. Тесты хранилища данных (SQLite)
class TestStorage(unittest.TestCase):
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
        self.storage.save(self._make_record(mode="IDLE"))
        records = self.storage.get_latest(10)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["mode"], "IDLE")

    def test_get_latest_returns_correct_limit(self):
        for i in range(10):
            self.storage.save(self._make_record(ts=time.time() + i))
        self.assertEqual(len(self.storage.get_latest(5)), 5)
        self.assertEqual(len(self.storage.get_latest(10)), 10)

    def test_get_latest_order_is_descending(self):
        for i in range(5):
            self.storage.save(self._make_record(ts=float(i)))
        records = self.storage.get_latest(5)
        timestamps = [r["timestamp"] for r in records]
        self.assertEqual(timestamps, sorted(timestamps, reverse=True))

    def test_anomalies_deserialized_to_list(self):
        anomalies = ["Вибрация: 9.9 ∉ [1.85-2.25]"]
        self.storage.save(self._make_record(anomalies=anomalies))
        record = self.storage.get_last_record()
        self.assertIsInstance(record["anomalies"], list)
        self.assertEqual(record["anomalies"], anomalies)

    def test_get_last_record_returns_none_when_empty(self):
        self.assertIsNone(self.storage.get_last_record())

    def test_get_last_record_returns_most_recent(self):
        self.storage.save(self._make_record(ts=1000.0, mode="START"))
        self.storage.save(self._make_record(ts=2000.0, mode="NOMINAL"))
        last = self.storage.get_last_record()
        self.assertEqual(last["mode"], "NOMINAL")

    def test_all_sensor_fields_saved_correctly(self):
        record = self._make_record()
        self.storage.save(record)
        result = self.storage.get_last_record()
        self.assertAlmostEqual(result["rpm"], record.rpm, places=1)
        self.assertAlmostEqual(result["exhaust_temp"], record.exhaust_temp, places=1)
        self.assertAlmostEqual(result["inlet_pressure"], record.inlet_pressure, places=1)
        self.assertAlmostEqual(result["fuel_flow"], record.fuel_flow, places=1)
        self.assertAlmostEqual(result["vibration"], record.vibration, places=1)
        self.assertAlmostEqual(result["iga_position"], record.iga_position, places=1)


# 4. Тесты оркестратора (с заглушками)
class TestOrchestrator(unittest.TestCase):
    def setUp(self):
        self.orch = Orchestrator(poll_interval=1.0, auto_cycle=False)

        self.mock_sim = MagicMock()
        self.mock_sim.get_readings.return_value = {
            "timestamp": time.time(),
            "rpm": 8000.0,
            "exhaust_temp": 650.0,
            "inlet_pressure": 150.0,
            "fuel_flow": 2000.0,
            "vibration": 4.0,
            "iga_position": 99.0,
        }
        self.orch._simulator = self.mock_sim

        self.mock_storage = MagicMock()
        self.orch._storage = self.mock_storage

    def tearDown(self):
        if self.orch._state.is_running:
            self.orch.stop()

    def test_initial_state_is_not_running(self):
        self.assertFalse(self.orch._state.is_running)

    def test_start_sets_running_true(self):
        self.orch.start()
        self.assertTrue(self.orch._state.is_running)

    def test_stop_sets_running_false(self):
        self.orch.start()
        self.orch.stop()
        self.assertFalse(self.orch._state.is_running)

    def test_double_start_does_not_create_extra_threads(self):
        self.orch.start()
        thread_before = self.orch._poll_thread
        self.orch.start()
        self.assertIs(self.orch._poll_thread, thread_before)

    def test_get_current_state_initial(self):
        state = self.orch.get_current_state()
        self.assertEqual(state["readings"], {})
        self.assertEqual(state["mode"], "UNKNOWN")
        self.assertEqual(state["anomalies"], [])

    def test_analyze_maps_keys_correctly(self):
        readings = self.mock_sim.get_readings.return_value
        mode, anomalies = self.orch._analyze(readings)
        self.assertEqual(mode, "NOMINAL")
        self.assertIsInstance(anomalies, list)

    def test_analyze_returns_unknown_on_missing_key(self):
        bad_readings = {"rpm": 8000}
        mode, anomalies = self.orch._analyze(bad_readings)
        self.assertEqual(mode, "UNKNOWN")
        self.assertTrue(len(anomalies) > 0)

    def test_poll_loop_saves_to_storage(self):
        self.orch._state.is_running = True
        call_count = [0]

        def fake_sleep(_):
            call_count[0] += 1
            self.orch._state.is_running = False

        with patch("orchestrator.time.sleep", side_effect=fake_sleep):
            self.orch._poll_loop()

        self.mock_storage.save.assert_called_once()
        self.assertEqual(call_count[0], 1)

    def test_poll_loop_updates_state(self):
        self.orch._state.is_running = True

        def fake_sleep(_):
            self.orch._state.is_running = False

        with patch("orchestrator.time.sleep", side_effect=fake_sleep):
            self.orch._poll_loop()

        state = self.orch.get_current_state()
        self.assertEqual(state["mode"], "NOMINAL")
        self.assertNotEqual(state["timestamp"], 0.0)

    def test_get_history_delegates_to_storage(self):
        self.mock_storage.get_latest.return_value = [{"mode": "IDLE"}]
        result = self.orch.get_history(limit=50)
        self.mock_storage.get_latest.assert_called_once_with(50)
        self.assertEqual(result, [{"mode": "IDLE"}])


# 5. Тесты REST API
class TestAPI(unittest.TestCase):
    DB_AUTH = "test_api_auth.db"
    DB_SENSOR = "test_api_sensor.db"

    @classmethod
    def setUpClass(cls):
        # 1. Подменяем БД аутентификации на тестовую
        test_config = AuthConfig(
            bcrypt_rounds=4,
            jwt_secret="test-secret-key-dolzhen-byt-32-simvolov-xxxx",
            rate_limit_max=1000  # отключаем rate limit для тестов
        )
        repo = SQLiteUserRepository(cls.DB_AUTH)
        hasher = BcryptHasher(test_config)
        token_svc = TokenService(test_config.jwt_secret, expire_minutes=60)
        auth = AuthSystem(repo, hasher, token_svc, test_config)
        auth.create_admin_if_empty()  # admin/Admin@12345
        server._auth_system = auth

        # 2. Подменяем оркестратор заглушкой
        mock_orch = MagicMock()
        mock_orch.get_current_state.return_value = {
            "timestamp": time.time(),
            "mode": "NOMINAL",
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

        # 3. Подменяем сервис аудита заглушкой
        cls.mock_audit = MagicMock()
        server._audit = cls.mock_audit

        # 4. Создаём тестовый клиент
        cls.client = TestClient(server.app, raise_server_exceptions=False)

        # 5. Логинимся админом и получаем токен
        resp = cls.client.post("/api/auth/login",
                               json={"login": "admin", "password": "Admin@12345"})
        cls.token = resp.json().get("token", "")
        cls.auth_headers = {"Authorization": f"Bearer {cls.token}"}

    @classmethod
    def tearDownClass(cls):
        for db in [cls.DB_AUTH, cls.DB_SENSOR]:
            if os.path.exists(db):
                os.remove(db)

    # health
    def test_health_returns_200(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)

    def test_health_returns_ok(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.json(), {"status": "ok"})

    # Статус
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
            self.assertIn(field, body)

    def test_status_mode_is_string(self):
        resp = self.client.get("/api/status", headers=self.auth_headers)
        self.assertIsInstance(resp.json()["mode"], str)

    # История
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

    # Эндпоинты аудита
    def test_audit_endpoint_requires_auth(self):
        resp = self.client.get("/api/audit")
        self.assertEqual(resp.status_code, 401)

    def test_audit_endpoint_for_admin_returns_events(self):
        resp = self.client.get("/api/audit", headers=self.auth_headers)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsInstance(data, list)
        if data:
            event = data[0]
            self.assertIn("id", event)
            self.assertIn("event_type", event)
            self.assertIn("username", event)

    def test_audit_endpoint_respects_limit(self):
        resp = self.client.get("/api/audit?limit=1", headers=self.auth_headers)
        self.assertEqual(resp.status_code, 200)
        self.assertLessEqual(len(resp.json()), 1)

        resp = self.client.get("/api/audit?limit=999", headers=self.auth_headers)
        self.assertEqual(resp.status_code, 400)

    def test_audit_endpoint_non_admin_sees_only_own_events(self):
        # Создаём обычного пользователя
        create_resp = self.client.post(
            "/api/admin/create-user",
            params={"username": "testuser", "password": "Test@1234"},
            headers=self.auth_headers
        )
        self.assertEqual(create_resp.status_code, 200)

        # Логинимся как обычный пользователь
        login_resp = self.client.post("/api/auth/login", json={
            "login": "testuser", "password": "Test@1234"
        })
        self.assertEqual(login_resp.status_code, 200)
        user_token = login_resp.json()["token"]
        user_headers = {"Authorization": f"Bearer {user_token}"}

        # Запрашиваем аудит
        resp = self.client.get("/api/audit", headers=user_headers)
        self.assertEqual(resp.status_code, 200)
        events = resp.json()
        for ev in events:
            self.assertEqual(ev["username"], "testuser")

    # Логирование аудита через моки
    def test_audit_login_success_logged(self):
        self.mock_audit.reset_mock()
        self.client.post("/api/auth/login",
                         json={"login": "admin", "password": "Admin@12345"})
        self.mock_audit.log_login_success.assert_called_once_with(
            username="admin", ip_address="testclient"
        )

    def test_audit_login_failed_logged(self):
        self.mock_audit.reset_mock()
        self.client.post("/api/auth/login",
                         json={"login": "admin", "password": "wrong"})
        self.mock_audit.log_login_failed.assert_called_once()

    def test_audit_password_change_logged(self):
        self.mock_audit.reset_mock()
        # Создаём временного пользователя, чтобы не портить admin
        temp_user = f"passuser_{int(time.time())}"
        temp_pass = "Temp@123"
        self.client.post(
            "/api/admin/create-user",
            params={"username": temp_user, "password": temp_pass},
            headers=self.auth_headers
        )
        login_resp = self.client.post("/api/auth/login", json={
            "login": temp_user, "password": temp_pass
        })
        token = login_resp.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        self.client.post(
            "/api/auth/change-password",
            json={"current_password": temp_pass, "new_password": "NewPass@123"},
            headers=headers
        )
        self.mock_audit.log_password_change.assert_called_once_with(
            username=temp_user, changed_by=temp_user
        )

    def test_audit_status_read_logged(self):
        self.mock_audit.reset_mock()
        self.client.get("/api/status", headers=self.auth_headers)
        self.mock_audit.log_event.assert_called_once_with(
            event_type=AuditEventType.DATA_READ,
            username='admin',
            description='User admin requested current status',
            severity=AuditSeverity.LOW
        )

    def test_audit_create_user_logged(self):
        self.mock_audit.reset_mock()
        unique_name = f"audituser_{int(time.time())}"
        self.client.post(
            "/api/admin/create-user",
            params={"username": unique_name, "password": "Audit@123"},
            headers=self.auth_headers
        )
        self.mock_audit.log_event.assert_called_once()
        call_kwargs = self.mock_audit.log_event.call_args.kwargs
        self.assertEqual(call_kwargs.get('event_type'), AuditEventType.USER_CREATED)

    # Создание пользователей
    def test_create_user_admin_only(self):
        # Создаём обычного пользователя
        norm_user = f"norm_{int(time.time())}"
        norm_pass = "Norm@1234"
        self.client.post(
            "/api/admin/create-user",
            params={"username": norm_user, "password": norm_pass},
            headers=self.auth_headers
        )
        login = self.client.post("/api/auth/login", json={
            "login": norm_user, "password": norm_pass
        })
        user_token = login.json()["token"]
        user_headers = {"Authorization": f"Bearer {user_token}"}

        resp = self.client.post(
            "/api/admin/create-user",
            params={"username": "shouldfail", "password": "Fail@1234"},
            headers=user_headers
        )
        self.assertEqual(resp.status_code, 403)

    def test_create_user_success(self):
        unique_name = f"alice_{int(time.time())}"
        resp = self.client.post(
            "/api/admin/create-user",
            params={"username": unique_name, "password": "Alice@1234"},
            headers=self.auth_headers
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("успешно создан", resp.json()["message"])

        # Проверяем, что можно залогиниться
        login = self.client.post("/api/auth/login", json={
            "login": unique_name, "password": "Alice@1234"
        })
        self.assertEqual(login.status_code, 200)

    def test_create_user_duplicate(self):
        dup_name = f"bob_{int(time.time())}"
        self.client.post(
            "/api/admin/create-user",
            params={"username": dup_name, "password": "Bob@1234"},
            headers=self.auth_headers
        )
        resp = self.client.post(
            "/api/admin/create-user",
            params={"username": dup_name, "password": "Another@1234"},
            headers=self.auth_headers
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("уже существует", resp.json()["detail"])

    def test_create_user_invalid_password(self):
        unique_name = f"weak_{int(time.time())}"
        resp = self.client.post(
            "/api/admin/create-user",
            params={"username": unique_name, "password": "weak"},
            headers=self.auth_headers
        )
        self.assertEqual(resp.status_code, 422)

    # Логин
    def test_login_success_returns_token(self):
        unique_login = f"loginuser_{int(time.time())}"
        unique_pass = "Login@123"
        create_resp = self.client.post(
            "/api/admin/create-user",
            params={"username": unique_login, "password": unique_pass},
            headers=self.auth_headers
        )
        self.assertEqual(create_resp.status_code, 200)

        resp = self.client.post("/api/auth/login",
                                json={"login": unique_login, "password": unique_pass})
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

    # ---- change password ----
    def test_change_password_invalid_current_returns_400(self):
        # Создаём временного пользователя
        user = f"invalid_{int(time.time())}"
        pwd = "Valid@123"
        self.client.post(
            "/api/admin/create-user",
            params={"username": user, "password": pwd},
            headers=self.auth_headers
        )
        login_resp = self.client.post("/api/auth/login", json={"login": user, "password": pwd})
        token = login_resp.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        resp = self.client.post(
            "/api/auth/change-password",
            json={"current_password": "WrongCurrent@1", "new_password": "NewValid@99"},
            headers=headers,
        )
        self.assertEqual(resp.status_code, 400)

    def test_change_password_weak_new_password_returns_422(self):
        user = f"weakuser_{int(time.time())}"
        pwd = "Valid@123"
        self.client.post(
            "/api/admin/create-user",
            params={"username": user, "password": pwd},
            headers=self.auth_headers
        )
        login_resp = self.client.post("/api/auth/login", json={"login": user, "password": pwd})
        token = login_resp.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        resp = self.client.post(
            "/api/auth/change-password",
            json={"current_password": pwd, "new_password": "weak"},
            headers=headers,
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