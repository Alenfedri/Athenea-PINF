"""Modo Entrenador: bandeja multi-sujeto aislada. Solo lee paquetes .vbcoach; no accede a ninguna base SQLite."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from services import modo_entrenador as me

COLUMNAS = ["Deportista/Alias", "HRV/RMSSD", "VO2máx", "TSB", "% Cumplimiento", "Hábitos"]


class ModoEntrenadorWidget(QWidget):
    def __init__(self, directorio: str = me.DIR_COACH_PACKS, parent=None):
        super().__init__(parent)
        self.directorio = directorio
        self.packs: list[dict] = []                         # arranca vacía
        capa = QVBoxLayout(self)
        capa.addWidget(QLabel("Modo Entrenador: solo muestra los paquetes .vbcoach que importes aquí "
                              "(nunca lee otras cuentas de este equipo)."))
        fila = QHBoxLayout()
        self.btn_importar = QPushButton("Importar Coach Pack(s)")
        self.btn_pdf = QPushButton("Exportar PDFs Anonimizados por Lotes")
        self.btn_pdf.setEnabled(False)
        fila.addWidget(self.btn_importar)
        fila.addWidget(self.btn_pdf)
        fila.addStretch(1)
        capa.addLayout(fila)
        self.tabla = QTableWidget(0, len(COLUMNAS))
        self.tabla.setHorizontalHeaderLabels(COLUMNAS)
        capa.addWidget(self.tabla)
        self.btn_importar.clicked.connect(self.importar)
        self.btn_pdf.clicked.connect(self.exportar_pdfs)

    def importar(self) -> None:
        rutas, _ = QFileDialog.getOpenFileNames(self, "Importar Coach Pack(s)", "", "Coach Pack (*.vbcoach)")
        errores = []
        for r in rutas:
            try:
                copia = me.importar_coach_pack(r, self.directorio)
                d = me.leer_coach_pack(copia)
                d["archivo"] = copia
                self.packs.append(d)
            except (OSError, ValueError) as e:
                errores.append(f"{r}: {e}")
        if errores:
            QMessageBox.warning(self, "Importar Coach Pack", "\n".join(errores))
        self._rellenar()

    def _rellenar(self) -> None:
        self.tabla.setRowCount(0)
        n = lambda x, d=0: "N/D" if x is None else f"{x:.{d}f}"
        for p in self.packs:
            m, f = p["metricas"], self.tabla.rowCount()
            self.tabla.insertRow(f)
            hab = p.get("habitos")
            valores = [p.get("alias", "?"), n(m.get("rmssd_medio_ms")) + " ms", n(m.get("vo2max"), 1),
                       n(m.get("tsb_actual"), 1), n(p.get("cumplimiento_semanal_pct")) + (" %" if p.get("cumplimiento_semanal_pct") is not None else ""),
                       "No compartido" if hab is None else (", ".join(f"{h['etiqueta']} ×{h['veces']}" for h in hab) or "Sin etiquetas")]
            for c, v in enumerate(valores):
                self.tabla.setItem(f, c, QTableWidgetItem(v))
        self.btn_pdf.setEnabled(bool(self.packs))

    def exportar_pdfs(self) -> None:
        carpeta = QFileDialog.getExistingDirectory(self, "Carpeta de destino de los PDFs")
        if carpeta and self.packs:
            rutas = me.exportar_informes_lote_anonimizados([p["archivo"] for p in self.packs], carpeta)
            QMessageBox.information(self, "PDFs anonimizados", f"Se generaron {len(rutas)} informes en {carpeta}.")

    def reiniciar(self) -> None:
        """Vacía la vista (cierre de sesión)."""
        self.packs = []
        self._rellenar()
