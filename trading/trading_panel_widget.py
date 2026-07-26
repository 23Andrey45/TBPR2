# trading/trading_panel_widget.py
"""
Виджет панели торговли.
Выбор инструмента, ввод лотов и цены, кнопки Buy/Sell.
"""

from __future__ import annotations

from typing import Optional

from PyQt6 import QtCore, QtGui, QtWidgets

from core.instruments_catalog import InstrumentInfo


class TradingPanelWidget(QtWidgets.QWidget):
    """Виджет панели торговли."""

    # Сигналы
    instrument_selected = QtCore.pyqtSignal(object)  # InstrumentInfo
    buy_clicked = QtCore.pyqtSignal(object, int, float)  # instrument, lots, price
    sell_clicked = QtCore.pyqtSignal(object, int, float)  # instrument, lots, price

    def __init__(self, parent=None):
        super().__init__(parent)

        self._selected_instrument: Optional[InstrumentInfo] = None

        # Заголовок
        header_label = QtWidgets.QLabel("📈 Торговая панель")
        header_label.setStyleSheet(
            "font-weight: bold; font-size: 11px; padding: 4px; background: #e8f5e9; border-radius: 3px;")

        # Выбор инструмента
        instrument_layout = QtWidgets.QFormLayout()
        instrument_layout.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)

        self.lbl_instrument = QtWidgets.QLabel("Не выбран")
        self.lbl_instrument.setStyleSheet("font-weight: bold; color: #1976d2;")
        instrument_layout.addRow("Инструмент:", self.lbl_instrument)

        # Лоты
        self.ed_lots = QtWidgets.QLineEdit("1")
        self.ed_lots.setMaximumWidth(100)
        self.ed_lots.setStyleSheet("""
            QLineEdit {
                border: 1px solid #ddd;
                border-radius: 3px;
                padding: 4px;
                font-size: 11px;
            }
            QLineEdit:focus {
                border: 1px solid #1976d2;
            }
        """)
        instrument_layout.addRow("Лотов:", self.ed_lots)

        # Цена
        self.ed_price = QtWidgets.QLineEdit("")
        self.ed_price.setMaximumWidth(100)
        self.ed_price.setStyleSheet("""
            QLineEdit {
                border: 1px solid #ddd;
                border-radius: 3px;
                padding: 4px;
                font-size: 11px;
            }
            QLineEdit:focus {
                border: 1px solid #1976d2;
            }
        """)
        instrument_layout.addRow("Цена:", self.ed_price)

        # Кнопки Buy/Sell
        buttons_layout = QtWidgets.QHBoxLayout()
        buttons_layout.setSpacing(8)

        self.btn_buy = QtWidgets.QPushButton("🟢 Buy Limit")
        self.btn_buy.setMinimumHeight(30)
        self.btn_buy.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:disabled {
                background-color: #ccc;
            }
        """)
        self.btn_buy.clicked.connect(self._on_buy_clicked)
        buttons_layout.addWidget(self.btn_buy)

        self.btn_sell = QtWidgets.QPushButton("🔴 Sell Limit")
        self.btn_sell.setMinimumHeight(30)
        self.btn_sell.setStyleSheet("""
            QPushButton {
                background-color: #f44336;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #d32f2f;
            }
            QPushButton:disabled {
                background-color: #ccc;
            }
        """)
        self.btn_sell.clicked.connect(self._on_sell_clicked)
        buttons_layout.addWidget(self.btn_sell)

        # Результат операции
        self.lbl_result = QtWidgets.QLabel("")
        self.lbl_result.setWordWrap(True)
        self.lbl_result.setStyleSheet("font-size: 10px; padding: 4px;")

        # Компоновка
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(header_label)
        layout.addLayout(instrument_layout)
        layout.addLayout(buttons_layout)
        layout.addWidget(self.lbl_result)

        # Валидатор для лотов (только целые числа)
        self.ed_lots.setValidator(QtGui.QIntValidator(1, 999999))

        # Валидатор для цены (только числа)
        price_validator = QtGui.QDoubleValidator(0.01, 999999.99, 2)
        self.ed_price.setValidator(price_validator)

    def set_instrument(self, info: Optional[InstrumentInfo], price: float = 0.0):
        """Установить выбранный инструмент и цену."""
        self._selected_instrument = info

        if info:
            self.lbl_instrument.setText(f"{info.ticker} | {info.name}")
            self.lbl_instrument.setStyleSheet("font-weight: bold; color: #1976d2; font-size: 11px;")

            # Установить цену
            if price > 0:
                self.ed_price.setText(f"{price:.2f}")

            # Сбросить лоты на 1 если поле пустое
            if not self.ed_lots.text():
                self.ed_lots.setText("1")

            # Включить кнопки
            self.btn_buy.setEnabled(True)
            self.btn_sell.setEnabled(True)

            self.instrument_selected.emit(info)
        else:
            self.lbl_instrument.setText("Не выбран")
            self.lbl_instrument.setStyleSheet("color: #999;")
            self.ed_price.clear()
            self.btn_buy.setEnabled(False)
            self.btn_sell.setEnabled(False)

    def _on_buy_clicked(self):
        """Обработка клика Buy."""
        if not self._selected_instrument:
            self.lbl_result.setText("❌ Выберите инструмент")
            self.lbl_result.setStyleSheet("color: #f44336;")
            return

        try:
            lots = int(self.ed_lots.text())
            price = float(self.ed_price.text().replace(",", "."))

            if lots <= 0 or price <= 0:
                raise ValueError()

            self.lbl_result.setText(f"⏳ Выставление заявки на покупку {lots} лотов по {price:.2f}...")
            self.lbl_result.setStyleSheet("color: #1976d2;")

            self.buy_clicked.emit(self._selected_instrument, lots, price)
        except ValueError:
            self.lbl_result.setText("❌ Проверьте значения лотов и цены")
            self.lbl_result.setStyleSheet("color: #f44336;")

    def _on_sell_clicked(self):
        """Обработка клика Sell."""
        if not self._selected_instrument:
            self.lbl_result.setText("❌ Выберите инструмент")
            self.lbl_result.setStyleSheet("color: #f44336;")
            return

        try:
            lots = int(self.ed_lots.text())
            price = float(self.ed_price.text().replace(",", "."))

            if lots <= 0 or price <= 0:
                raise ValueError()

            self.lbl_result.setText(f"⏳ Выставление заявки на продажу {lots} лотов по {price:.2f}...")
            self.lbl_result.setStyleSheet("color: #ff9800;")

            self.sell_clicked.emit(self._selected_instrument, lots, price)
        except ValueError:
            self.lbl_result.setText("❌ Проверьте значения лотов и цены")
            self.lbl_result.setStyleSheet("color: #f44336;")

    def set_result(self, success: bool, message: str):
        """Установить результат операции."""
        if success:
            self.lbl_result.setText(f"✅ {message}")
            self.lbl_result.setStyleSheet("color: #4CAF50;")
        else:
            self.lbl_result.setText(f"❌ {message}")
            self.lbl_result.setStyleSheet("color: #f44336;")

    def clear_result(self):
        """Очистить результат."""
        self.lbl_result.setText("")