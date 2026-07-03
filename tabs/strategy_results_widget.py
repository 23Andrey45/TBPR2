# tabs/strategy_results_widget.py
from __future__ import annotations

from typing import Any

from PyQt6 import QtCore, QtWidgets

from core.strategies import STRATEGIES
from core.strategies.base import Strategy, StrategyResult, ParamSpec


class StrategyBlock(QtWidgets.QGroupBox):
    recalc_requested = QtCore.pyqtSignal(str, object)  # strategy_id, user_params(dict)

    def __init__(self, strategy: Strategy, parent=None):
        super().__init__(parent)
        self.strategy = strategy
        self.setTitle(strategy.strategy_name)
        self.setCheckable(True)
        self.setChecked(True)

        self._editors: dict[str, QtWidgets.QWidget] = {}

        # -------- LEFT: recalc button + params form --------
        self.btn_recalc = QtWidgets.QPushButton("Пересчитать")
        self.btn_recalc.clicked.connect(self._on_recalc_clicked)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        form.setFormAlignment(QtCore.Qt.AlignmentFlag.AlignTop)
        form.setContentsMargins(0, 0, 0, 0)

        for p in strategy.param_specs():
            w = self._make_editor(p)
            self._editors[p.key] = w
            form.addRow(p.label + ":", w)

        left_layout = QtWidgets.QVBoxLayout()
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)
        left_layout.addWidget(self.btn_recalc, 0)
        left_layout.addLayout(form, 1)

        left_widget = QtWidgets.QWidget()
        left_widget.setLayout(left_layout)
        left_widget.setMinimumWidth(340)

        # -------- RIGHT: metrics table --------
        self.table = QtWidgets.QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["метрика", "значение"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)

        # -------- CONTENT (two columns) --------
        self.content = QtWidgets.QWidget()
        content_layout = QtWidgets.QHBoxLayout(self.content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)
        content_layout.addWidget(left_widget, 0)
        content_layout.addWidget(self.table, 1)

        # -------- OUTER LAYOUT (so we can hide content) --------
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(6)
        outer.addWidget(self.content)

        # collapse/expand by checkbox
        self.toggled.connect(self._on_toggled)
        self._on_toggled(self.isChecked())

    def _on_toggled(self, checked: bool):
        self.content.setVisible(checked)

        # Чтобы scroll/layout быстрее пересчитали высоту
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Fixed if not checked else QtWidgets.QSizePolicy.Policy.Preferred,
        )
        self.updateGeometry()
        if self.parentWidget():
            self.parentWidget().updateGeometry()

    def _make_editor(self, p: ParamSpec) -> QtWidgets.QWidget:
        t = p.type.lower()

        if t == "bool":
            cb = QtWidgets.QCheckBox()
            cb.setChecked(bool(p.default))
            return cb

        if t == "choice":
            combo = QtWidgets.QComboBox()
            for c in (p.choices or []):
                combo.addItem(str(c), c)
            if p.default in (p.choices or []):
                combo.setCurrentIndex((p.choices or []).index(p.default))
            return combo

        le = QtWidgets.QLineEdit()
        le.setText(str(p.default))
        return le

    def _collect_params(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for p in self.strategy.param_specs():
            w = self._editors[p.key]
            t = p.type.lower()

            if t == "bool":
                out[p.key] = bool(w.isChecked())  # type: ignore[attr-defined]
            elif t == "choice":
                out[p.key] = w.currentData()       # type: ignore[attr-defined]
            else:
                out[p.key] = w.text().strip()      # type: ignore[attr-defined]
        return out

    def _on_recalc_clicked(self):
        params = self._collect_params()
        self.recalc_requested.emit(self.strategy.strategy_id, params)

    def set_result(self, result: StrategyResult):
        self.setTitle(result.strategy_name)

        self.table.setRowCount(0)
        for k, v in result.metrics.items():
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(str(k)))
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(str(v)))


class StrategyResultsWidget(QtWidgets.QWidget):
    recalc_requested = QtCore.pyqtSignal(str, object)  # strategy_id, user_params(dict)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._blocks: dict[str, StrategyBlock] = {}

        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)

        self.content = QtWidgets.QWidget()
        self.vbox = QtWidgets.QVBoxLayout(self.content)
        self.vbox.setContentsMargins(6, 6, 6, 6)
        self.vbox.setSpacing(10)
        self.vbox.addStretch(1)

        self.scroll.setWidget(self.content)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.scroll)

        for s in STRATEGIES:
            block = StrategyBlock(s)
            block.recalc_requested.connect(self.recalc_requested)
            self._blocks[s.strategy_id] = block
            self.vbox.insertWidget(self.vbox.count() - 1, block)

    def set_results(self, results: dict[str, StrategyResult]):
        for res in results.values():
            self.update_one(res)

    def update_one(self, res: StrategyResult):
        block = self._blocks.get(res.strategy_id)
        if block:
            block.set_result(res)
