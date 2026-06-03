# интерфейс итоговая версия
import sys
from abc import ABC, abstractmethod

import requests
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
                             QPushButton, QGroupBox, QHeaderView)
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import QDialog, QLineEdit, QMenu

from gtu_analyzer import MODE_LIMITS

MODE_COLORS = {
    "STOP": "#808080", "START": "#FFA500", "IDLE": "#2E8B57",
    "PARTIAL": "#1E90FF", "NOMINAL": "#228B22", "EMERGENCY": "#DC143C", "TRANSITION": "#A9A9A9"
}


class IApiClient(ABC):
    """Абстрактный интерфейс для API-клиента"""

    @abstractmethod
    def login(self, login: str, password: str) -> dict:
        """Выполняет вход, возвращает {'token': str, 'is_admin': bool}"""
        pass

    @abstractmethod
    def get_status(self, token: str) -> dict:
        """Возвращает текущее состояние ГТУ (readings, mode, anomalies)"""
        pass

    @abstractmethod
    def get_audit(self, token: str, limit: int = 50) -> list:
        """Возвращает список событий аудита"""
        pass

    @abstractmethod
    def change_password(self, token: str, current_password: str, new_password: str) -> None:
        """Меняет пароль текущего пользователя"""
        pass

    @abstractmethod
    def create_user(self, token: str, username: str, password: str) -> None:
        """Создаёт нового пользователя (только для админа)"""
        pass

class RequestsApiClient(IApiClient):
    def __init__(self, base_url: str = "http://127.0.0.1:8000"):
        self.base_url = base_url
        self.session = requests.Session()  # опционально, для переиспользования соединений

    def login(self, login: str, password: str) -> dict:
        resp = self.session.post(
            f"{self.base_url}/api/auth/login",
            json={"login": login, "password": password},
            timeout=5
        )
        if resp.status_code == 200:
            data = resp.json()
            return {"token": data["token"], "is_admin": data.get("is_admin", False)}
        elif resp.status_code == 401:
            raise Exception("Неверный логин или пароль")
        else:
            raise Exception(f"Ошибка входа: {resp.status_code}")

    def get_status(self, token: str) -> dict:
        headers = {"Authorization": f"Bearer {token}"}
        resp = self.session.get(
            f"{self.base_url}/api/status",
            headers=headers,
            timeout=2
        )
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 401:
            raise Exception("Токен истёк или недействителен")
        else:
            raise Exception(f"Ошибка получения статуса: {resp.status_code}")

    def get_audit(self, token: str, limit: int = 50) -> list:
        headers = {"Authorization": f"Bearer {token}"}
        resp = self.session.get(
            f"{self.base_url}/api/audit?limit={limit}",
            headers=headers,
            timeout=2
        )
        if resp.status_code == 200:
            return resp.json()
        elif resp.status_code == 401:
            raise Exception("Токен истёк или недействителен")
        else:
            raise Exception(f"Ошибка получения логов: {resp.status_code}")

    def change_password(self, token: str, current_password: str, new_password: str) -> None:
        headers = {"Authorization": f"Bearer {token}"}
        resp = self.session.post(
            f"{self.base_url}/api/auth/change-password",
            json={"current_password": current_password, "new_password": new_password},
            headers=headers,
            timeout=5
        )
        if resp.status_code == 200:
            return
        else:
            detail = resp.json().get("detail", "Ошибка смены пароля")
            raise Exception(detail)

    def create_user(self, token: str, username: str, password: str) -> None:
        headers = {"Authorization": f"Bearer {token}"}
        resp = self.session.post(
            f"{self.base_url}/api/admin/create-user",
            params={"username": username, "password": password},
            headers=headers,
            timeout=5
        )
        if resp.status_code == 200:
            return
        else:
            detail = resp.json().get("detail", "Ошибка создания пользователя")
            raise Exception(detail)

class LoginDialog(QDialog):
    """Окно авторизации. Поля по умолчанию пустые"""
    def __init__(self, parent: QWidget = None, api_client: IApiClient = None):
        super().__init__(parent)
        self.api_client = api_client
        self.setWindowTitle("Авторизация")
        self.setModal(True)
        self.resize(300, 200)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Логин:"))
        self.input_login = QLineEdit()  # Пустое по умолчанию
        layout.addWidget(self.input_login)

        layout.addWidget(QLabel("Пароль:"))
        self.input_pass = QLineEdit()
        self.input_pass.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.input_pass)

        self.btn_enter = QPushButton("Войти")
        self.btn_enter.clicked.connect(self._do_login)
        layout.addWidget(self.btn_enter)

        self.error_label = QLabel()
        self.error_label.setStyleSheet("color: red")
        layout.addWidget(self.error_label)

        self.setLayout(layout)

    def _do_login(self):
        login = self.input_login.text()
        pwd = self.input_pass.text()
        try:
            result = self.api_client.login(login, pwd)
            self.token = result["token"]
            self.is_admin = result["is_admin"]
            self.accept()
        except Exception as e:
            self.error_label.setText(str(e))



class ChangePasswordDialog(QDialog):
    """Смена пароля"""
    def __init__(self, parent=None, api_client=None, token=None):
        super().__init__(parent)
        self.api_client = api_client
        self.token = token
        self.setWindowTitle("Смена пароля")
        self.setModal(True)
        self.resize(320, 220)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout()
        self.old_pass = QLineEdit()
        self.old_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.new_pass = QLineEdit()
        self.new_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm_pass = QLineEdit()
        self.confirm_pass.setEchoMode(QLineEdit.EchoMode.Password)

        layout.addWidget(QLabel("Текущий пароль:"))
        layout.addWidget(self.old_pass)
        layout.addWidget(QLabel("Новый пароль:"))
        layout.addWidget(self.new_pass)
        layout.addWidget(QLabel("Подтверждение:"))
        layout.addWidget(self.confirm_pass)

        self.btn_save = QPushButton("Сохранить")
        self.btn_save.clicked.connect(self._do_change)
        layout.addWidget(self.btn_save)

        self.error_label = QLabel()
        self.error_label.setStyleSheet("color: red")
        layout.addWidget(self.error_label)
        self.setLayout(layout)

    def _do_change(self):
        if self.new_pass.text() != self.confirm_pass.text():
            self.error_label.setText("Новый пароль и подтверждение не совпадают")
            return
        try:
            self.api_client.change_password(
                self.token,
                self.old_pass.text(),
                self.new_pass.text()
            )
            self.accept()
        except Exception as e:
            self.error_label.setText(str(e))

class CreateUserDialog(QDialog):
    def __init__(self, parent=None, api_client=None, token=None):
        super().__init__(parent)
        self.api_client = api_client
        self.token = token
        self.setWindowTitle("Создание пользователя")
        self.setModal(True)
        self.resize(300, 200)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Логин:"))
        self.input_login = QLineEdit()
        layout.addWidget(self.input_login)
        layout.addWidget(QLabel("Пароль:"))
        self.input_pass = QLineEdit()
        self.input_pass.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.input_pass)
        self.btn_create = QPushButton("Создать")
        self.btn_create.clicked.connect(self._do_create)
        layout.addWidget(self.btn_create)
        self.error_label = QLabel()
        self.error_label.setStyleSheet("color: red")
        layout.addWidget(self.error_label)
        self.setLayout(layout)

    def _do_create(self):
        login = self.input_login.text().strip()
        pwd = self.input_pass.text()
        if not login or not pwd:
            self.error_label.setText("Заполните все поля")
            return
        try:
            self.api_client.create_user(self.token, login, pwd)
            self.accept()
        except Exception as e:
            self.error_label.setText(str(e))

class GTUWindow(QMainWindow):
    """ Главное окно приложения.
    """
    def __init__(self, parent=None, api_client=None, token=None, is_admin=False):
        """
        инициализация mainwindow настраивает заголовок, размеры, флаги состояния,
        создаёт QTimer для опроса сервера
        """
        super().__init__()
        self.api_client = api_client
        self.token = token
        self.is_admin = is_admin
        role_text = "Администратор" if self.is_admin else "Пользователь"
        self.setWindowTitle(f"Мониторинг ГТУ ({role_text})")
        self.resize(850, 600)

        # Настройки подключения к серверу
        self.API_URL = "http://127.0.0.1:8000"
        self.is_connected = False
        self.sim_running = False  # флаг

        self.log_timer = QTimer(self) # таймер для логов
        self.log_timer.timeout.connect(self._fetch_audit_logs)


        # Таймер для обновления UI (теперь он только триггерит запрос к API)
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self._fetch_data_from_server)

        self._setup_ui()
        self._start_simulation()

    def _setup_ui(self):
        """ строит главный интерфейс
            - Добавляет блок отображения текущего режима
            - Создаёт таблицу для показаний датчиков (6 строк × 3 столбца)
            - Кнопки «Запуск» и «Остановка»
            - Строка статуса окна
        """
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        # Статус режима
        status_box = QGroupBox("Текущий режим ГТУ")
        status_layout = QVBoxLayout(status_box)
        self.lbl_mode = QLabel("STOP", alignment=Qt.AlignmentFlag.AlignCenter)
        self.lbl_mode.setFont(QFont("Arial", 24, QFont.Weight.Bold))
        self.lbl_mode.setStyleSheet("background-color: #808080; color: white; border-radius: 8px; padding: 10px;")
        status_layout.addWidget(self.lbl_mode)
        main_layout.addWidget(status_box)

        # Параметры в реальном времени
        params_box = QGroupBox("Показания датчиков")
        params_layout = QVBoxLayout(params_box)
        self.tbl_params = QTableWidget(6, 3)
        self.tbl_params.setHorizontalHeaderLabels(["Параметр", "Значение", "Статус"])
        self.tbl_params.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tbl_params.verticalHeader().setVisible(False)
        params_layout.addWidget(self.tbl_params)
        main_layout.addWidget(params_box)

        log_box = QGroupBox("Журнал событий")
        log_layout = QVBoxLayout(log_box)
        self.log_table = QTableWidget(0, 4)  # 4 колонки
        self.log_table.setHorizontalHeaderLabels(["Время", "Пользователь", "Событие", "Описание"])
        self.log_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.log_table.setAlternatingRowColors(True)
        log_layout.addWidget(self.log_table)
        main_layout.addWidget(log_box)

        # Управление (кнопки остановка и запуск начинают и прерывают мониторинг соответственно)
        ctrl_layout = QHBoxLayout()
        self.btn_account = QPushButton("Аккаунт")
        self.btn_account.setMenu(self._create_account_menu())
        ctrl_layout.addWidget(self.btn_account)
        self.btn_start = QPushButton("Запуск")
        self.btn_stop = QPushButton("Остановка")
        self.btn_start.clicked.connect(self._start_simulation)
        self.btn_stop.clicked.connect(self._stop_simulation)
        ctrl_layout.addWidget(self.btn_start)
        ctrl_layout.addWidget(self.btn_stop)
        main_layout.addLayout(ctrl_layout)

        self.statusBar().showMessage("Готово к работе")

    def _fetch_audit_logs(self):
        if not self.sim_running or not self.token:
            return
        try:
            events = self.api_client.get_audit(self.token, limit=50)
            self._update_log_table(events)
        except Exception as e:
            self.statusBar().showMessage(f"Ошибка получения логов: {e}", 3000)

    def _update_log_table(self, events):
        self.log_table.setRowCount(0)
        for event in events:
            row = self.log_table.rowCount()
            self.log_table.insertRow(row)
            self.log_table.setItem(row, 0, QTableWidgetItem(event.get("timestamp", "")))
            self.log_table.setItem(row, 1, QTableWidgetItem(event.get("username", "")))
            self.log_table.setItem(row, 2, QTableWidgetItem(event.get("event_type", "")))
            desc = event.get("description", "")
            # если описание слишком длинное, обрезаем
            if len(desc) > 80:
                desc = desc[:77] + "..."
            self.log_table.setItem(row, 3, QTableWidgetItem(desc))
        # Прокручиваем к последней записи (снизу)
        self.log_table.scrollToBottom()

    def _fetch_data_from_server(self):
        """
        Получает данные с сервера через API и обновляет UI.
        Вызывается по таймеру в главном потоке. Блокирующий вызов requests.get()
        может временно замораживать интерфейс при задержках сети или отсутствии сервера
        """
        if not self.sim_running or not self.token:
            return

        try:
            data = self.api_client.get_status(self.token)
            readings = data.get("readings", {})
            mode = data.get("mode", "UNKNOWN")
            anomalies = data.get("anomalies", [])

            rpm = readings.get('rpm', 0)
            temp = readings.get('exhaust_temp', 0)
            pres = readings.get('inlet_pressure', 0)
            fuel = readings.get('fuel_flow', 0)
            vib = readings.get('vibration', 0)
            iga = readings.get('iga_position', 0)

            self._update_table(rpm, temp, pres, fuel, vib, iga)
            self._update_mode_display(mode)

            if anomalies:
                self.statusBar().showMessage(f"Аномалия: {anomalies[0]}", 5000)
            else:
                self.statusBar().showMessage(f"Режим: {mode} | Данные получены с сервера")
            self.is_connected = True
        except Exception as e:
            self.statusBar().showMessage(f"Ошибка: {str(e)}", 3000)
            self.is_connected = False

    def _update_table(self, rpm, temp, pres, fuel, vib, iga):
        """
        Заполнение двух столбцов таблицы
        - Принимает числовые значения параметров с сервера (api/status) и вписывает их в ячейки
        - Не изменяет третий столбец «Статус» (его обновление вынесено в метод update_mode_display).
        """
        data = [
            ("Об/мин", f"{rpm:.1f}"), ("Температура, °C", f"{temp:.1f}"),
            ("Давление, кПа", f"{pres:.2f}"), ("Топливо, кг/ч", f"{fuel:.1f}"),
            ("Вибрация, мм/с", f"{vib:.2f}"), ("IGA, %", f"{iga:.2f}")
        ]
        for i, (name, val) in enumerate(data):
            self.tbl_params.setItem(i, 0, QTableWidgetItem(name))
            item = QTableWidgetItem(val)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.tbl_params.setItem(i, 1, item)

    def _update_mode_display(self, mode):
        """
        Визуальное обновление статуса режима и проверка параметров на соответствие норме.
            - Проходит по всем строкам таблицы, сравнивает каждое значение с допустимыми
                границами (MODE_LIMITS) для текущего режима.
            - Записывает в третий столбец статус: "Норма" (зелёный текст) или "Выход за норму"
                (красный текст)
        """
        self.lbl_mode.setText(mode)
        color = MODE_COLORS.get(mode, "#808080")
        self.lbl_mode.setStyleSheet(f"background-color: {color}; color: white; border-radius: 8px; padding: 10px;")

        # Подсветка статусов строк таблицы
        keys = ["rpm", "T", "P", "fuel", "vib", "iga"]
        limits = MODE_LIMITS.get(mode, {})

        for i in range(self.tbl_params.rowCount()):
            val_item = self.tbl_params.item(i, 1)
            if val_item:
                val = float(val_item.text())
                key = keys[i]
                status_item = QTableWidgetItem()
                if key in limits:
                    mn, mx = limits[key]
                    if mn <= val <= mx:
                        status_item.setText("Норма")
                        status_item.setForeground(QColor("green"))
                    else:
                        status_item.setText("Выход за норму")
                        status_item.setForeground(QColor("red"))
                self.tbl_params.setItem(i, 2, status_item)

    def _start_simulation(self):
        """
        Запускает таймер опроса сервера
        """
        if not self.sim_running:
            self.sim_running = True
            self.log_timer.start(3000)  # обновлять каждые 3 секунды
            self.update_timer.start(1000)
            self.btn_start.setEnabled(False)
            self.btn_stop.setEnabled(True)
            self.statusBar().showMessage("Подключение к серверу...")

    def _stop_simulation(self):
        """
        останавливает опрос сервера
        """
        if self.sim_running:
            self.sim_running = False
            self.log_timer.stop()
            self.update_timer.stop()
            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(False)
            self.lbl_mode.setText("ОЖИДАНИЕ")
            self.lbl_mode.setStyleSheet("background-color: #333; color: white; border-radius: 8px; padding: 10px;")
            self.statusBar().showMessage("Опрос остановлен")

    def _create_account_menu(self):
        """Формирует выпадающее меню для кнопки Аккаунт"""
        menu = QMenu(self)
        menu.addAction("Сменить пароль", self._open_change_password)
        if self.is_admin:
            menu.addAction("Создать пользователя", self._create_user)
        menu.addAction("Выйти", self._handle_logout)
        return menu

    def _create_user(self):
        dialog = CreateUserDialog(self, self.api_client, self.token)
        if dialog.exec():
            self.statusBar().showMessage("Новый пользователь создан", 3000)

    def _open_change_password(self):
        """Показывает окно смены пароля (заглушка)"""
        dialog = ChangePasswordDialog(self, self.api_client, self.token)  # parent, api_client, token
        if dialog.exec():
            self.statusBar().showMessage("Пароль успешно изменён", 3000)

    def _handle_logout(self):
        """Выход: скрывает основное окно, вызывает логин.
        При успешном входе снова показывает главное окно."""
        self.log_table.setRowCount(0)  # очищаем старые логи
        self.hide()
        login = LoginDialog(parent=self, api_client=self.api_client)
        if login.exec() == QDialog.DialogCode.Accepted and hasattr(login, 'token'):
            self.token = login.token
            self.is_admin = login.is_admin
            self._update_account_menu()
            # обновляем заголовок при смене пользователя (его роли)
            role_text = "Администратор" if self.is_admin else "Пользователь"
            self.setWindowTitle(f"Мониторинг ГТУ ({role_text})")
            #перезапуск обновления интерфейса
            self._stop_simulation()
            self._start_simulation()
            self.show()
        else:
            self.log_timer.stop()
            self.close()

    def _update_account_menu(self):
        """Обновляет меню кнопки Аккаунт в зависимости от прав пользователя(после перелогина)"""
        menu = QMenu(self)
        menu.addAction("Сменить пароль", self._open_change_password)
        if self.is_admin:
            menu.addAction("Создать пользователя", self._create_user)
        menu.addAction("Выйти", self._handle_logout)
        self.btn_account.setMenu(menu)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    api_client = RequestsApiClient()
    login = LoginDialog(parent=None, api_client=api_client)  # явно указываем имена параметров
    if login.exec() == QDialog.DialogCode.Accepted and hasattr(login, 'token'):
        # успешный вход - запускаем mainwindow
        window = GTUWindow(parent=None, api_client=api_client, token=login.token, is_admin=login.is_admin)
        window.show()
        sys.exit(app.exec())
    else:
        sys.exit(0)  # Завершение при отмене входа