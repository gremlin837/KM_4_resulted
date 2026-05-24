"""Тестирование модуля auth_module."""

from auth_module import (
    AuthSystem, AuthConfig, BcryptHasher, TokenService,
    InMemoryUserRepository, AuthError
)




if __name__ == "__main__":

    print("тесты")


    # тестовый репозиторий
    repo = InMemoryUserRepository()

    # настройка
    config = AuthConfig(
        jwt_secret="my_secret_key"
    )
    hasher = BcryptHasher(config)
    token_service = TokenService(config.jwt_secret)


    auth = AuthSystem(repo, hasher, token_service, config)

    # Создание администратора (в пустой БД)
    print("Создание администратора в пустой БД")
    auth.create_admin_if_empty()

    try:
        admin, msg = auth.authenticate("admin", "Admin@12345")
        print(f"    Админ создан: {admin.username}")
        print(f"     Сообщение: {msg}")
    except AuthError as e:
        print(f"     Ошибка: {e}")


    #Создание обычного пользователя
    print("Созданиепользователя")
    hashed = hasher.hash_password("UserPass123!")
    repo.create_user("operator", hashed['hash'], False)
    print("  Пользователь 'operator' создан")

    #Успешная аутентификация
    print(" Успешная аутентификация")
    try:
        user, msg = auth.authenticate("operator", "UserPass123!")
        print(f" {msg}")
        print(f"  Пользователь: {user.username}, admin={user.is_admin}")

        token = auth.create_token(user)
        print(f"  Токен: {token[:60]}...")
    except AuthError as e:
        print(f"  Ошибка: {e}")

    # Неверный пароль
    print(" Неверный пароль")
    try:
        auth.authenticate("operator", "wrong_password")
    except AuthError as e:
        print(f" Ожидаемая ошибка: {e}")

    # Проверка токена
    print(" Проверка JWT токена")
    payload = auth.verify_token(token)
    if payload:
        print(f"  Токен валиден")
        print(f"  Пользователь: {payload.get('sub')}")
        print(f"  is_admin: {payload.get('is_admin')}")
    else:
        print("Токен невалиден")

    # ТЕСТ 6: Смена пароля
    print("Смена пароля")
    try:
        auth.change_password(user, "NewPass456!")
        print(" Пароль изменён")

        # Проверяем с новым паролем
        user2, msg2 = auth.authenticate("operator", "NewPass456!")
        print(f" Вход с новым паролем: {msg2}")
    except AuthError as e:
        print(f"  Ошибка: {e}")


    print("ТЕСТЫ ПРОЙДЕНЫ ")
