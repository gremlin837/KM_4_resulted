# интерфейс тестовая версия
import sys
import requests
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
                             QPushButton, QGroupBox, QHeaderView)
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import QDialog, QLineEdit, QMenu

from gtu_analyzer import GTUAnalyzer, MODE_LIMITS

MODE_COLORS = {
    "STOP": "#808080", "START": "#FFA500", "IDLE": "#2E8B57",
    "PARTIAL": "#1E90FF", "NOMINAL": "#228B22", "EMERGENCY": "#DC143C", "TRANSITION": "#A9A9A9"
}

class LoginDialog(QDialog):
    """Заглушка окна авторизации. Поля по умолчанию пустые"""
    def __init__(self, parent=None):
        super().__init__(parent)
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
            resp = requests.post("http://127.0.0.1:8000/api/auth/login",
                                 json={"login": login, "password": pwd},
                                 timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                self.token = data["token"]  # сохраняем токен
                self.accept()
            else:
                self.error_label.setText("Неверный логин или пароль")
        except Exception:
            self.error_label.setText("Ошибка соединения")


class ChangePasswordDialog(QDialog):
    """Заглушка окна смены пароля"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Смена пароля")
        self.setModal(True)
        self.resize(320, 220)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout()
        for label_text in ["Текущий пароль:", "Новый пароль:", "Подтверждение нового пароля:"]:
            layout.addWidget(QLabel(label_text))
            inp = QLineEdit()
            inp.setEchoMode(QLineEdit.EchoMode.Password)
            layout.addWidget(inp)

        self.btn_save = QPushButton("Сохранить")
        self.btn_save.clicked.connect(self.accept)  # Заглушка
        layout.addWidget(self.btn_save)
        self.setLayout(layout)

class GTUWindow(QMainWindow):
    """ Главное окно приложения.
    """
    def __init__(self, token):
        """
        инициализация mainwindow настраивает заголовок, размеры, флаги состояния,
        создаёт QTimer для опроса сервера
        """
        super().__init__()
        self.token = token
        self.setWindowTitle("Мониторинг ГТУ")
        self.resize(850, 600)

        # Настройки подключения к серверу
        self.API_URL = "http://127.0.0.1:8000"
        self.is_connected = False
        self.sim_running = False  # флаг


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

        # Заглушка журнала логов (в будущем здесь будет логирование в реальном времени)
        stub_box = QGroupBox("Журнал событий")
        stub_layout = QVBoxLayout(stub_box)
        self.lbl_stub = QLabel("", alignment=Qt.AlignmentFlag.AlignCenter)
        self.lbl_stub.setFixedHeight(40)
        self.lbl_stub.setStyleSheet("background-color: #f5f5f5; border: 1px dashed #ccc; color: #999;")
        stub_layout.addWidget(self.lbl_stub)
        main_layout.addWidget(stub_box)

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

    def _fetch_data_from_server(self):
        """
        Получает данные с сервера через API и обновляет UI.
        Выполняется в отдельном потоке, чтобы не блокировать интерфейс.
        """
        if not self.sim_running or not self.token:
            return

        try:
            # Запрос к серверу за текущим статусом
            headers = {"Authorization": f"Bearer {self.token}"}
            response = requests.get(f"{self.API_URL}/api/status", headers=headers, timeout=2)

            if response.status_code == 200:
                data = response.json()

                # Сервер возвращает структуру: {"readings": {...}, "mode": "...", "anomalies": [...]}
                readings = data.get("readings", {})
                mode = data.get("mode", "UNKNOWN")
                anomalies = data.get("anomalies", [])

                # Извлекаем параметры (ключи должны совпадать с теми, что шлет сервер)
                rpm = readings.get('rpm', 0)
                temp = readings.get('exhaust_temp', 0)
                pres = readings.get('inlet_pressure', 0)
                fuel = readings.get('fuel_flow', 0)
                vib = readings.get('vibration', 0)
                iga = readings.get('iga_position', 0)

                # Обновляем интерфейс
                self._update_table(rpm, temp, pres, fuel, vib, iga)
                self._update_mode_display(mode)

                # Статус бар
                if anomalies:
                    self.statusBar().showMessage(f"Аномалия: {anomalies[0]}", 5000)
                else:
                    self.statusBar().showMessage(f"Режим: {mode} | Данные получены с сервера")

                self.is_connected = True
            else:
                self.statusBar().showMessage(f"Ошибка сервера: {response.status_code}", 3000)
                self.is_connected = False

        except requests.exceptions.ConnectionError:
            self.statusBar().showMessage("Нет связи с сервером", 3000)
            self.is_connected = False
        except Exception as e:
            self.statusBar().showMessage(f"Ошибка: {str(e)}", 3000)

    def _update_table(self, rpm, temp, pres, fuel, vib, iga):
        """
        Заполнение двух столбцов таблицы
        - Принимает числовые значения параметров и вписывает их в ячейки
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
        menu.addAction("Выйти", self._handle_logout)
        return menu

    def _open_change_password(self):
        """Показывает окно смены пароля (заглушка)"""
        dialog = ChangePasswordDialog(self)
        dialog.exec()

    def _handle_logout(self):
        """Имитация выхода: скрывает основное окно, вызывает логин.
        При успешном входе снова показывает главное окно."""
        self.hide()
        login = LoginDialog(self)
        if login.exec() == QDialog.DialogCode.Accepted and hasattr(login, 'token'):
            self.token = login.token
            self.show()
            self._start_simulation()
        else:
            self.close()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    login = LoginDialog()
    if login.exec() == QDialog.DialogCode.Accepted and hasattr(login, 'token'):
        # успешный вход - запускаем mainwindow
        window = GTUWindow(token=login.token)
        window.show()
        sys.exit(app.exec())
    else:
        sys.exit(0)  # Завершение при отмене входа