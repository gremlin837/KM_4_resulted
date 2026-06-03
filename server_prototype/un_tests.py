"""
Юнит-тесты для системы аутентификации auth_system_united.py
ПОЛНАЯ ВЕРСИЯ - все тесты проходят
"""

from auth_system_united import (
    AuthSystem, AuthConfig, User,
    BcryptHasher, TokenService,
    SQLiteUserRepository,
    UserNotFound, InvalidPassword, AccountLocked,
    RateLimitExceeded, PermissionDenied, PasswordValidation
)
import unittest
import time
import tempfile
import os
import sqlite3
from datetime import datetime, timedelta

import bcrypt
import jwt

# Импортируем тестируемый модуль
import sys
sys.path.append('.')


class TestAuthConfig(unittest.TestCase):
    """Тесты конфигурации аутентификации"""

    def test_default_config(self):
        """Тест значений по умолчанию"""
        config = AuthConfig()
        self.assertEqual(config.bcrypt_rounds, 12)
        self.assertEqual(config.rate_limit_window, 60)
        self.assertEqual(config.rate_limit_max, 5)
        self.assertEqual(config.admin_min_length, 8)
        self.assertEqual(config.user_min_length, 6)
        self.assertEqual(config.max_attempts, 3)
        self.assertEqual(config.lockout_minutes, 5)

    def test_custom_config(self):
        """Тест кастомных значений"""
        config = AuthConfig(
            bcrypt_rounds=10,
            max_attempts=5,
            lockout_minutes=10
        )
        self.assertEqual(config.bcrypt_rounds, 10)
        self.assertEqual(config.max_attempts, 5)
        self.assertEqual(config.lockout_minutes, 10)


class TestUser(unittest.TestCase):
    """Тесты модели пользователя"""

    def test_user_creation(self):
        """Тест создания пользователя"""
        user = User(
            username="testuser",
            password_hash="hash123",
            is_admin=False
        )
        self.assertEqual(user.username, "testuser")
        self.assertEqual(user.password_hash, "hash123")
        self.assertFalse(user.is_admin)
        self.assertEqual(user.failed_attempts, 0)
        self.assertEqual(user.locked_until, 0)
        self.assertFalse(user.need_change_password)

    def test_is_locked(self):
        """Тест проверки блокировки"""
        user = User(username="test", password_hash="hash", is_admin=False)
        self.assertFalse(user.is_locked())

        user.locked_until = int(time.time()) + 100
        self.assertTrue(user.is_locked())

    def test_remaining_lockout_minutes(self):
        """Тест расчета оставшегося времени блокировки"""
        user = User(username="test", password_hash="hash", is_admin=False)
        self.assertEqual(user.remaining_lockout_minutes(), 0)

        future = int(time.time()) + 300  # 5 минут
        user.locked_until = future
        remaining = user.remaining_lockout_minutes()
        self.assertGreaterEqual(remaining, 4)
        self.assertLessEqual(remaining, 5)


class TestBcryptHasher(unittest.TestCase):
    """Тесты хеширования паролей"""

    def setUp(self):
        self.hasher = BcryptHasher(AuthConfig(bcrypt_rounds=4))

    def test_hash_and_verify(self):
        """Тест хеширования и верификации"""
        password = "Test@12345"
        result = self.hasher.hash_password(password)

        self.assertIn('hash', result)
        self.assertTrue(self.hasher.verify_password(password, result['hash']))
        self.assertFalse(
            self.hasher.verify_password(
                "WrongPassword",
                result['hash']))

    def test_different_passwords_produce_different_hashes(self):
        """Тест: разные пароли дают разные хеши"""
        hash1 = self.hasher.hash_password("Password1@")['hash']
        hash2 = self.hasher.hash_password("Password2@")['hash']
        self.assertNotEqual(hash1, hash2)


class TestTokenService(unittest.TestCase):
    """Тесты JWT токенов"""

    def setUp(self):
        self.secret = "test_secret_key_12345678901234567890"  # 40 байт
        self.service = TokenService(self.secret, expire_minutes=60)

    def test_create_and_verify_token(self):
        """Тест создания и верификации токена"""
        token = self.service.create("testuser", True)
        self.assertIsNotNone(token)

        payload = self.service.verify(token)
        self.assertIsNotNone(payload)
        self.assertEqual(payload['sub'], "testuser")
        self.assertTrue(payload['is_admin'])

    def test_invalid_token(self):
        """Тест невалидного токена"""
        payload = self.service.verify("invalid.token.here")
        self.assertIsNone(payload)

    def test_wrong_secret(self):
        """Тест токена с неправильным секретом"""
        token = self.service.create("testuser", False)

        other_service = TokenService("different_secret_key_1234567890")
        payload = other_service.verify(token)
        self.assertIsNone(payload)


class TestSQLiteUserRepository(unittest.TestCase):
    """Тесты SQLite репозитория"""

    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.temp_db.close()
        self.repo = SQLiteUserRepository(self.temp_db.name)

    def tearDown(self):
        try:
            if os.path.exists(self.temp_db.name):
                os.unlink(self.temp_db.name)
        except PermissionError:
            pass

    def test_create_and_get_user(self):
        """Тест создания и получения пользователя"""
        self.repo.create_user("alice", "hash123", False)

        user = self.repo.get_user("alice")
        self.assertIsNotNone(user)
        self.assertEqual(user['username'], "alice")
        self.assertEqual(user['hash'], "hash123")
        self.assertEqual(user['is_admin'], 0)
        self.assertEqual(user['failed'], 0)

    def test_get_nonexistent_user(self):
        """Тест получения несуществующего пользователя"""
        user = self.repo.get_user("nonexistent")
        self.assertIsNone(user)

    def test_update_user(self):
        """Тест обновления пользователя"""
        self.repo.create_user("bob", "oldhash", False)

        self.repo.update_user(
            "bob",
            hash="newhash",
            failed=3,
            locked_until=12345)

        user = self.repo.get_user("bob")
        self.assertEqual(user['hash'], "newhash")
        self.assertEqual(user['failed'], 3)
        self.assertEqual(user['locked_until'], 12345)

    def test_all_users(self):
        """Тест получения списка всех пользователей"""
        self.repo.create_user("user1", "hash1", False)
        self.repo.create_user("user2", "hash2", True)
        self.repo.create_user("user3", "hash3", False)

        users = self.repo.all_users()
        self.assertEqual(len(users), 3)
        self.assertIn("user1", users)
        self.assertIn("user2", users)
        self.assertIn("user3", users)


class TestAuthSystem(unittest.TestCase):
    """Основные тесты системы аутентификации"""

    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.temp_db.close()

        self.config = AuthConfig(
            bcrypt_rounds=4,
            max_attempts=5,  # Увеличиваем до 5, чтобы не блокировать в тестах
            lockout_minutes=1,
            rate_limit_window=60,
            rate_limit_max=10
        )
        self.repo = SQLiteUserRepository(self.temp_db.name)
        self.hasher = BcryptHasher(self.config)
        # Секрет длиной 32+ байт
        self.token_service = TokenService(
            "test_secret_key_12345678901234567890123456789012",
            self.config.jwt_algorithm,
            self.config.jwt_expire_minutes
        )
        self.auth = AuthSystem(
            self.repo,
            self.hasher,
            self.token_service,
            self.config)

    def tearDown(self):
        try:
            if os.path.exists(self.temp_db.name):
                os.unlink(self.temp_db.name)
        except BaseException:
            pass

    def test_create_admin_if_empty(self):
        """Тест создания администратора при пустой БД"""
        created = self.auth.create_admin_if_empty()
        self.assertTrue(created)

        users = self.repo.all_users()
        self.assertIn("admin", users)

        created_again = self.auth.create_admin_if_empty()
        self.assertFalse(created_again)

    def test_successful_authentication(self):
        """Тест успешной аутентификации"""
        hashed = self.hasher.hash_password("ValidPass@123")
        self.repo.create_user("testuser", hashed['hash'], False)

        user, message = self.auth.authenticate("testuser", "ValidPass@123")

        self.assertEqual(user.username, "testuser")
        self.assertEqual(message, "Успешный вход")
        self.assertEqual(user.failed_attempts, 0)

    def test_authentication_wrong_password(self):
        """Тест аутентификации с неверным паролем"""
        hashed = self.hasher.hash_password("CorrectPass@123")
        self.repo.create_user("testuser", hashed['hash'], False)

        with self.assertRaises(InvalidPassword):
            self.auth.authenticate("testuser", "WrongPass@123")

        user_data = self.repo.get_user("testuser")
        self.assertEqual(user_data['failed'], 1)

    def test_authentication_nonexistent_user(self):
        """Тест аутентификации несуществующего пользователя"""
        with self.assertRaises(UserNotFound):
            self.auth.authenticate("nonexistent", "anypass")

    def test_account_lockout(self):
        """Тест блокировки аккаунта после превышения попыток"""
        # Временно уменьшаем max_attempts для этого теста
        original_max = self.auth.config.max_attempts
        self.auth.config.max_attempts = 3

        hashed = self.hasher.hash_password("CorrectPass@123")
        self.repo.create_user("testuser", hashed['hash'], False)

        # 3 неудачные попытки
        for i in range(3):
            try:
                self.auth.authenticate("testuser", "WrongPass@123")
            except (InvalidPassword, AccountLocked):
                pass

        # 4-я попытка должна заблокировать аккаунт
        with self.assertRaises(AccountLocked):
            self.auth.authenticate("testuser", "WrongPass@123")

        user_data = self.repo.get_user("testuser")
        self.assertGreater(user_data['locked_until'], time.time())

        # Восстанавливаем
        self.auth.config.max_attempts = original_max

    def test_change_password(self):
        """Тест смены пароля"""
        hashed = self.hasher.hash_password("OldPass@123")
        self.repo.create_user("testuser", hashed['hash'], False)

        user = self.auth._load_user("testuser")
        self.auth.change_password(user, "NewPass@123")

        new_user, message = self.auth.authenticate("testuser", "NewPass@123")
        self.assertEqual(message, "Успешный вход")

        with self.assertRaises(InvalidPassword):
            self.auth.authenticate("testuser", "OldPass@123")

    def test_change_password_invalid(self):
        """Тест смены пароля на невалидный"""
        hashed = self.hasher.hash_password("OldPass@123")
        self.repo.create_user("testuser", hashed['hash'], False)
        user = self.auth._load_user("testuser")

        with self.assertRaises(PasswordValidation):
            self.auth.change_password(user, "short")

        with self.assertRaises(PasswordValidation):
            self.auth.change_password(user, "noupper@123")

        with self.assertRaises(PasswordValidation):
            self.auth.change_password(user, "NoSpecial123")

    def test_create_token(self):
        """Тест создания JWT токена"""
        hashed = self.hasher.hash_password("Test@123")
        self.repo.create_user("testuser", hashed['hash'], False)
        user = self.auth._load_user("testuser")

        token = self.auth.create_token(user)
        self.assertIsNotNone(token)

        payload = self.token_service.verify(token)
        self.assertEqual(payload['sub'], "testuser")
        self.assertFalse(payload['is_admin'])

    def test_get_user_from_token(self):
        """Тест получения пользователя из токена"""
        hashed = self.hasher.hash_password("Test@123")
        self.repo.create_user("testuser", hashed['hash'], False)
        user = self.auth._load_user("testuser")

        token = self.auth.create_token(user)
        retrieved_user = self.auth.get_user_from_token(token)

        self.assertIsNotNone(retrieved_user)
        self.assertEqual(retrieved_user.username, "testuser")

    def test_get_user_from_invalid_token(self):
        """Тест получения пользователя из невалидного токена"""
        user = self.auth.get_user_from_token("invalid.token.here")
        self.assertIsNone(user)

        user = self.auth.get_user_from_token("")
        self.assertIsNone(user)

    def test_reset_user_password_by_admin(self):
        """Тест сброса пароля администратором"""
        admin_hashed = self.hasher.hash_password("AdminPass@123")
        user_hashed = self.hasher.hash_password("UserOld@123")

        self.repo.create_user("admin", admin_hashed['hash'], True)
        self.repo.create_user("testuser", user_hashed['hash'], False)

        admin = self.auth._load_user("admin")

        # Пароль не должен содержать "testuser"
        self.auth.reset_user_password(admin, "testuser", "NewUserPass@123")

        user, message = self.auth.authenticate("testuser", "NewUserPass@123")
        self.assertEqual(message, "Требуется смена пароля при первом входе")
        self.assertTrue(user.need_change_password)

    def test_set_user_lock(self):
        """Тест блокировки/разблокировки пользователя"""
        admin_hashed = self.hasher.hash_password("AdminPass@123")
        user_hashed = self.hasher.hash_password("User@123")

        self.repo.create_user("admin", admin_hashed['hash'], True)
        self.repo.create_user("testuser", user_hashed['hash'], False)

        admin = self.auth._load_user("admin")

        self.auth.set_user_lock(admin, "testuser", True)

        user_data = self.repo.get_user("testuser")
        self.assertGreater(user_data['locked_until'], time.time())

        self.auth.set_user_lock(admin, "testuser", False)

        user_data = self.repo.get_user("testuser")
        self.assertEqual(user_data['locked_until'], 0)

    def test_refresh_user(self):
        """Тест обновления пользователя из БД"""
        hashed = self.hasher.hash_password("Test@123")
        self.repo.create_user("testuser", hashed['hash'], False)

        self.auth._load_user("testuser")
        self.repo.update_user("testuser", failed=5)

        user2 = self.auth.refresh_user("testuser")
        self.assertEqual(user2.failed_attempts, 5)

    def test_validation_rules_for_admin(self):
        """Тест правил валидации для администратора"""
        admin_hashed = self.hasher.hash_password("AdminPass@123")
        self.repo.create_user("admin", admin_hashed['hash'], True)
        admin = self.auth._load_user("admin")

        # Пароль НЕ должен содержать "admin"
        self.auth.change_password(admin, "NewSuper@12345")

        auth_admin, _ = self.auth.authenticate("admin", "NewSuper@12345")
        self.assertEqual(auth_admin.username, "admin")

    def test_validation_rules_for_user(self):
        """Тест правил валидации для обычного пользователя"""
        user_hashed = self.hasher.hash_password("User@123")
        self.repo.create_user("testuser", user_hashed['hash'], False)
        user = self.auth._load_user("testuser")

        # Пароль НЕ должен содержать "testuser"
        self.auth.change_password(user, "UsrNew@12")

        auth_user, _ = self.auth.authenticate("testuser", "UsrNew@12")
        self.assertEqual(auth_user.username, "testuser")

    def test_rate_limit_exceeded(self):
        """Тест превышения лимита запросов"""
        hashed = self.hasher.hash_password("Test@123")
        self.repo.create_user("testuser", hashed['hash'], False)

        original_max = self.auth.config.rate_limit_max
        self.auth.config.rate_limit_max = 2

        client_ip = "192.168.1.100"

        for i in range(2):
            try:
                self.auth.authenticate("testuser", "WrongPass@123", client_ip)
            except InvalidPassword:
                pass

        with self.assertRaises(RateLimitExceeded):
            self.auth.authenticate("testuser", "WrongPass@123", client_ip)

        self.auth.config.rate_limit_max = original_max

    def test_rate_limit_different_ips(self):
        """Тест: разные IP имеют разные счетчики"""
        hashed = self.hasher.hash_password("Test@123")
        self.repo.create_user("testuser", hashed['hash'], False)

        original_max = self.auth.config.rate_limit_max
        original_attempts = self.auth.config.max_attempts
        self.auth.config.rate_limit_max = 2
        self.auth.config.max_attempts = 10  # Увеличиваем, чтобы не блокировать аккаунт

        ip1 = "192.168.1.1"
        ip2 = "192.168.1.2"

        for i in range(2):
            try:
                self.auth.authenticate("testuser", "WrongPass@123", ip1)
            except InvalidPassword:
                pass

        for i in range(2):
            try:
                self.auth.authenticate("testuser", "WrongPass@123", ip2)
            except InvalidPassword:
                pass

        with self.assertRaises(RateLimitExceeded):
            self.auth.authenticate("testuser", "WrongPass@123", ip1)

        # Сброс счетчика неудачных попыток
        self.auth._invalidate_cache("testuser")

        self.auth.config.rate_limit_max = original_max
        self.auth.config.max_attempts = original_attempts

    def test_permission_denied_non_admin_reset(self):
        """Тест: обычный пользователь не может сбросить пароль"""
        user1_hashed = self.hasher.hash_password("User1@123")
        user2_hashed = self.hasher.hash_password("User2@123")

        self.repo.create_user("user1", user1_hashed['hash'], False)
        self.repo.create_user("user2", user2_hashed['hash'], False)

        user1 = self.auth._load_user("user1")

        with self.assertRaises(PermissionDenied):
            self.auth.reset_user_password(user1, "user2", "NewPass@123")

    def test_permission_denied_non_admin_lock(self):
        """Тест: обычный пользователь не может блокировать других"""
        user1_hashed = self.hasher.hash_password("User1@123")
        user2_hashed = self.hasher.hash_password("User2@123")

        self.repo.create_user("user1", user1_hashed['hash'], False)
        self.repo.create_user("user2", user2_hashed['hash'], False)

        user1 = self.auth._load_user("user1")

        with self.assertRaises(PermissionDenied):
            self.auth.set_user_lock(user1, "user2", True)

    def test_permission_denied_admin_can_reset(self):
        """Тест: администратор может сбросить пароль"""
        admin_hashed = self.hasher.hash_password("AdminPass@123")
        user_hashed = self.hasher.hash_password("User@123")

        self.repo.create_user("admin", admin_hashed['hash'], True)
        self.repo.create_user("testuser", user_hashed['hash'], False)

        admin = self.auth._load_user("admin")

        self.auth.reset_user_password(admin, "testuser", "NewPass@123")

        user, message = self.auth.authenticate("testuser", "NewPass@123")
        self.assertEqual(message, "Требуется смена пароля при первом входе")

    def test_permission_denied_admin_can_lock(self):
        """Тест: администратор может блокировать пользователей"""
        admin_hashed = self.hasher.hash_password("AdminPass@123")
        user_hashed = self.hasher.hash_password("User@123")

        self.repo.create_user("admin", admin_hashed['hash'], True)
        self.repo.create_user("testuser", user_hashed['hash'], False)

        admin = self.auth._load_user("admin")

        self.auth.set_user_lock(admin, "testuser", True)

        user_data = self.repo.get_user("testuser")
        self.assertGreater(user_data['locked_until'], time.time())

    def test_get_user_from_invalid_token(self):
        """Тест получения пользователя из невалидного токена"""
        # Пробуем с невалидным токеном
        user = self.auth.get_user_from_token("invalid.token.here")
        self.assertIsNone(user)

        # Пробуем с пустым токеном
        user = self.auth.get_user_from_token("")
        self.assertIsNone(user)

        # Пробуем с токеном, у которого нет sub
        fake_payload = {"not_sub": "some_value", "exp": time.time() + 3600}
        fake_token = jwt.encode(
            fake_payload,
            self.token_service.secret,
            algorithm="HS256")
        user = self.auth.get_user_from_token(fake_token)
        self.assertIsNone(user)

    def test_rate_limit_reset_after_window(self):
        """Тест сброса лимита после временного окна"""
        hashed = self.hasher.hash_password("Test@123")
        self.repo.create_user("testuser", hashed['hash'], False)

        original_max = self.auth.config.rate_limit_max
        original_window = self.auth.config.rate_limit_window
        self.auth.config.rate_limit_max = 1
        self.auth.config.rate_limit_window = 1

        client_ip = "192.168.1.200"

        # Первая попытка
        try:
            self.auth.authenticate("testuser", "WrongPass@123", client_ip)
        except InvalidPassword:
            pass

        # Вторая попытка сразу - должна быть заблокирована
        with self.assertRaises(RateLimitExceeded):
            self.auth.authenticate("testuser", "WrongPass@123", client_ip)

        # Ждем окончания окна
        time.sleep(1.1)

        # После ожидания попытка должна пройти
        try:
            self.auth.authenticate("testuser", "WrongPass@123", client_ip)
        except RateLimitExceeded:
            self.fail("Rate limit should be reset after window")
        except InvalidPassword:
            pass

        self.auth.config.rate_limit_max = original_max
        self.auth.config.rate_limit_window = original_window

    def test_rate_limit_with_valid_auth(self):
        """Тест: успешная аутентификация тоже учитывается в rate limit"""
        hashed = self.hasher.hash_password("CorrectPass@123")
        self.repo.create_user("testuser", hashed['hash'], False)

        original_max = self.auth.config.rate_limit_max
        self.auth.config.rate_limit_max = 2

        client_ip = "192.168.1.150"

        # Первая успешная аутентификация
        self.auth.authenticate("testuser", "CorrectPass@123", client_ip)

        # Вторая успешная аутентификация
        self.auth.authenticate("testuser", "CorrectPass@123", client_ip)

        # Третья попытка должна быть заблокирована
        with self.assertRaises(RateLimitExceeded):
            self.auth.authenticate("testuser", "CorrectPass@123", client_ip)

        self.auth.config.rate_limit_max = original_max


class TestIntegration(unittest.TestCase):
    """Интеграционные тесты"""

    def setUp(self):
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.temp_db.close()

        self.config = AuthConfig(bcrypt_rounds=4)
        self.repo = SQLiteUserRepository(self.temp_db.name)
        self.hasher = BcryptHasher(self.config)
        self.token_service = TokenService(
            "test_secret_key_12345678901234567890123456789012"
        )
        self.auth = AuthSystem(
            self.repo,
            self.hasher,
            self.token_service,
            self.config)

    def tearDown(self):
        try:
            if os.path.exists(self.temp_db.name):
                os.unlink(self.temp_db.name)
        except BaseException:
            pass

    def test_full_auth_flow(self):
        """Тест полного сценария аутентификации"""
        # 1. Создаем админа
        self.auth.create_admin_if_empty()

        # 2. Админ меняет свой пароль (пароль НЕ должен содержать "admin")
        admin = self.auth._load_user("admin")
        self.auth.change_password(admin, "SuperUser@123")

        # 3. Создаем обычного пользователя
        hashed = self.hasher.hash_password("Initial@123")
        self.repo.create_user("operator", hashed['hash'], False)

        # 4. Пользователь входит в систему
        user, message = self.auth.authenticate("operator", "Initial@123")
        self.assertEqual(message, "Успешный вход")

        # 5. Создаем токен
        token = self.auth.create_token(user)
        self.assertIsNotNone(token)

        # 6. Получаем пользователя из токена
        retrieved = self.auth.get_user_from_token(token)
        self.assertEqual(retrieved.username, "operator")

        # 7. Меняем пароль (пароль НЕ должен содержать "operator")
        self.auth.change_password(retrieved, "NewPassUser@456")

        # 8. Выходим и заходим с новым паролем
        user2, message2 = self.auth.authenticate("operator", "NewPassUser@456")
        self.assertEqual(message2, "Успешный вход")


def run_tests():
    """Запуск всех тестов"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestAuthConfig))
    suite.addTests(loader.loadTestsFromTestCase(TestUser))
    suite.addTests(loader.loadTestsFromTestCase(TestBcryptHasher))
    suite.addTests(loader.loadTestsFromTestCase(TestTokenService))
    suite.addTests(loader.loadTestsFromTestCase(TestSQLiteUserRepository))
    suite.addTests(loader.loadTestsFromTestCase(TestAuthSystem))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegration))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
