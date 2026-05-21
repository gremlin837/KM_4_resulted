# интерфейс тестовая версия
import sys
import random
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
                             QPushButton, QGroupBox, QHeaderView)
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QColor, QFont

from gtu_analyzer import GTUAnalyzer, MODE_LIMITS

MODE_COLORS = {
    "STOP": "#808080", "START": "#FFA500", "IDLE": "#2E8B57",
    "PARTIAL": "#1E90FF", "NOMINAL": "#228B22", "EMERGENCY": "#DC143C", "TRANSITION": "#A9A9A9"
}


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
        self.mode_cycle_idx = 0
        self._ticks = 0 # Счётчик тактов таймера для управления цикличностью режимов

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
                Обработчик таймера: генерация тестовых данных, классификация и обновление UI.
                Вызывается автоматически каждую секунду.
                - Каждые 15 смен циклически меняет режим работы ГТУ.
                - Накладывает гауссовский шум для имитации реальных показаний датчиков (эмуляция Прил. 1).
                - С вероятностью 5% искусственно завышает вибрацию для проверки детекции аномалий.
                - Вызывает GTUAnalyzer.classify() для определения режима и поиска отклонений.
                - Обновляет таблицу показателей и цветовую индикацию режима.
                - Выводит краткое сообщение в строку статуса о состоянии параметров.
                """
        self._ticks += 1
        if self._ticks % 15 == 0:
            self.mode_cycle_idx = (self.mode_cycle_idx + 1) % 5

        # Базовые центры режимов (из Приложения 1)
        bases = [
            {"rpm": 0, "T": 22.5, "P": 101.0, "fuel": 0, "vib": 0.1, "iga": 0},
            {"rpm": 1500, "T": 210, "P": 110, "fuel": 250, "vib": 1.2, "iga": 50},
            {"rpm": 3000, "T": 400, "P": 120, "fuel": 500, "vib": 2.0, "iga": 20},
            {"rpm": 5500, "T": 500, "P": 130, "fuel": 1000, "vib": 3.0, "iga": 50},
            {"rpm": 8000, "T": 650, "P": 150, "fuel": 2000, "vib": 4.0, "iga": 99}
        ]
        base = bases[self.mode_cycle_idx]
        noise = lambda val, sigma: max(0, val + random.gauss(0, sigma)) # нужен исключительно для тестовой версии (симуляция погрешностей)

        rpm = noise(base["rpm"], 15 if base["rpm"] > 0 else 0)
        temp = noise(base["T"], 10)
        pres = noise(base["P"], 0.8)
        fuel = noise(base["fuel"], 25 if base["fuel"] > 0 else 0)
        vib = noise(base["vib"], 0.15)
        iga = noise(base["iga"], 3)

        # 5% вероятность выброса для демонстрации детекции
        # резкий скачок показаний, тестирует что детектор отклонений работает корректно
        if random.random() < 0.05:
            vib += random.uniform(2.0, 4.0)

        # Вызов анализатора
        mode, anomalies = GTUAnalyzer.classify(rpm, temp, pres, fuel, vib, iga)

        self._update_table(rpm, temp, pres, fuel, vib, iga)
        self._update_mode_display(mode)

        if anomalies:
            self.statusBar().showMessage("Обнаружены отклонения параметров", 3000)
        else:
            self.statusBar().showMessage(f"Режим: {mode} | Параметры в норме")

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
               - Запускает QTimer с интервалом 1 c.
               - блокирует "Запуск", активирует "Остановку"
               - Устанавливает флаг работы в True.
        """
        if not self.sim_running:
            self.sim_running = True
            self.sim_timer.start(1000)
            self.btn_start.setEnabled(False)
            self.btn_stop.setEnabled(True)

    def _stop_simulation(self):
        """
            - Останавливает QTimer => прерывается генерация новых данных
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


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = GTUWindow()
    window.show()
    sys.exit(app.exec())