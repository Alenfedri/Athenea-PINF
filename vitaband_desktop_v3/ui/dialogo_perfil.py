"""Perfil fisiológico (edad, sexo, peso) para estimar las kcal con Keytel."""

from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QLabel, QSpinBox)

from services.calculos_fisiologicos import HOMBRE, MUJER, PESO_REFERENCIA_KG, PerfilFisiologico


class DialogoPerfil(QDialog):

    def __init__(self, perfil: PerfilFisiologico, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Perfil fisiológico")
        form = QFormLayout(self)
        self.spin_edad = QSpinBox()
        self.spin_edad.setRange(0, 100)
        self.spin_edad.setSpecialValueText("No indicada")
        self.spin_edad.setValue(perfil.edad or 0)
        self.combo_sexo = QComboBox()
        self.combo_sexo.addItems(["No indicado", HOMBRE, MUJER])
        self.combo_sexo.setCurrentText(perfil.sexo if perfil.sexo in (HOMBRE, MUJER) else "No indicado")
        self.spin_peso = QDoubleSpinBox()
        self.spin_peso.setRange(0, 250)
        self.spin_peso.setDecimals(1)
        self.spin_peso.setSuffix(" kg")
        self.spin_peso.setSpecialValueText("No indicado")
        self.spin_peso.setValue(perfil.peso_kg or 0)
        form.addRow("Edad", self.spin_edad)
        form.addRow("Sexo", self.combo_sexo)
        form.addRow("Peso", self.spin_peso)
        aviso = QLabel("Sin peso se usa uno de referencia (%d kg hombre, %d kg mujer). Las kcal son una estimación; "
                       "sin edad y sexo no se calculan." % (PESO_REFERENCIA_KG[HOMBRE], PESO_REFERENCIA_KG[MUJER]))
        aviso.setWordWrap(True)
        form.addRow(aviso)
        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        botones.accepted.connect(self.accept)
        botones.rejected.connect(self.reject)
        form.addRow(botones)
        self._objetivo = perfil.objetivo_semanal_min

    def perfil(self) -> PerfilFisiologico:
        sexo = self.combo_sexo.currentText()
        return PerfilFisiologico(self.spin_edad.value() or None, sexo if sexo in (HOMBRE, MUJER) else None,
                                 self.spin_peso.value() or None, self._objetivo)
