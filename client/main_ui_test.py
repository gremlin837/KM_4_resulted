# интерфейс тестовая версия
import sys
from gtu_simulator import GTUSimulator, GTUMode
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
        self.resize(300, 160)
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
        self.btn_enter.clicked.connect(self.accept)  # Заглушка: всегда успех
        layout.addWidget(self.btn_enter)
        self.setLayout(layout)


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
     Методы отвечают за вид UI, генерацию тестовых данных, управление таймером итд.
    """
    def __init__(self):
        """
        инициализация mainwindow настраивает заголовок, размеры, флаги состояния,
        создаёт QTimer для обновления данных, запускает стартовую генерацию
        """
        super().__init__()
        self.setWindowTitle("Мониторинг ГТУ (Тестовый клиент)")
        self.resize(850, 600)
        self.sim_running = False # флаг

        # Инициализация реального симулятора
        self.simulator = GTUSimulator(interval=1.0)
        self.current_sim_mode = GTUMode.STOP  # Текущий режим симуляции
        self.sim_thread = None  # Поток для фоновой смены режимов (но здесь используется таймер GUI)


        self.simulation_step = 0  # Шаг симуляции (0-START, 1-IDLE, ... итд)
        self.step_timer = 0  # Счетчик секунд внутри текущего шага

        # Конфигурация цикла из Приложение 1 (сколько по времени длится каждый режим)
        self.cycle_config = [
            (GTUMode.START, 200),
            (GTUMode.IDLE, 300),
            (GTUMode.PARTIAL, 450),
            (GTUMode.NOMINAL, 500),
            (GTUMode.EMERGENCY, 50),
            (GTUMode.STOP, 300)
        ]

        self.sim_timer = QTimer(self) # таймер для переодического обновления данных(1 секунда)
        self.sim_timer.timeout.connect(self._generate_and_update)

        self._setup_ui()
        self._start_simulation()

    def _setup_ui(self):
        """ строит главный интерфейс
            - Добавляет блок отображения текущего режима
            - Создаёт таблицу для показаний датчиков (6 строк × 3 столбца)
            - Размещает пустую заглушку для будущего журнала логов
            - Кнопки «Запуск» и «Остановка»
            - Строкастатуса окна
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

    def _generate_and_update(self):
        """
        Получает данные от реального симулятора GTUSimulator(Приложение 1) и обновляет UI.
        Также управляет циклической сменой режимов работы ГТУ.
        """
        # Смена режимов (cycle_worker из Приложения 1)
        if self.sim_running:
            mode, duration = self.cycle_config[self.simulation_step]

            # Если текущий режим симулятора не совпадает с запланированным, он заменяется
            if self.simulator.current_mode != mode:
                self.simulator.set_mode(mode)
                self.current_sim_mode = mode

            self.step_timer += 1
            # Если время этапа истекло => начинается следующий
            if self.step_timer >= duration:
                self.step_timer = 0
                self.simulation_step = (self.simulation_step + 1) % len(self.cycle_config)

            # Получение показаний от симулятора
            readings = self.simulator.get_readings()

            # значения по ключам, которые использует анализатор
            rpm = readings['rpm']
            temp = readings['exhaust_temp']
            pres = readings['inlet_pressure']
            fuel = readings['fuel_flow']
            vib = readings['vibration']
            iga = readings['iga_position']

            # Классификация и поиск аномалий через GTUAnalyzer
            # Анализатор сам определит режим по оборотам, но мы можем сравнить его с ожидаемым
            detected_mode, anomalies = GTUAnalyzer.classify(rpm, temp, pres, fuel, vib, iga)

            # Обновление интерфейса
            self._update_table(rpm, temp, pres, fuel, vib, iga)
            self._update_mode_display(detected_mode)  # Показываем тот режим, который определил анализатор

            # Статус бар (снизу слева)
            if anomalies:
                self.statusBar().showMessage(f"Аномалия в режиме {detected_mode}: {anomalies[0]}", 5000)
            else:
                self.statusBar().showMessage(f"Режим: {detected_mode} | Параметры в норме")

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
               Запуск процесса генерации данных.
               - блокирует "Запуск", активирует "Остановку"
               - Устанавливает флаг работы в True.
        """
        if not self.sim_running:
            self.sim_running = True
            self.sim_timer.start(1000)
            self.btn_start.setEnabled(False)
            self.btn_stop.setEnabled(True)
            # Сброс счетчиков при новом запуске
            self.simulation_step = 0
            self.step_timer = 0
            self.simulator.set_mode(GTUMode.START)  # Начинаем с пуска

    def _stop_simulation(self):
        """
            - прерывается генерация новых данных
            - Блокирует "Остановку", активирует "Запуск"
            - состояние «ОЖИДАНИЕ» на главном label
            - Сбрасывает флаг работы в False.
        """
        if self.sim_running:
            self.sim_running = False
            self.sim_timer.stop()
            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(False)
            self.lbl_mode.setText("ОЖИДАНИЕ")
            self.lbl_mode.setStyleSheet("background-color: #333; color: white; border-radius: 8px; padding: 10px;")

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
        if login.exec() == QDialog.DialogCode.Accepted:
            self.show()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    login = LoginDialog()
    if login.exec() == QDialog.DialogCode.Accepted:
        # успешный вход - запускаем mainwindow
        window = GTUWindow()
        window.show()
        sys.exit(app.exec())
    else:
        sys.exit(0)  # Завершение при отмене входа