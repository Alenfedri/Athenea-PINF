import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import VitaBand 1.0

Page {
    title: "Actividad Deportiva"
    property var bleController

    header: ToolBar {
        ToolButton {
            text: "← Volver"
            onClicked: stackView.pop()
        }
    }

    ColumnLayout {
        anchors.centerIn: parent
        spacing: 30

        Text {
            text: "Registrar Entrenamiento"
            font.pixelSize: 22
            Layout.alignment: Qt.AlignHCenter
        }

        Button {
            text: "Iniciar Registro (RF-30)"
            Layout.preferredWidth: 200
            onClicked: bleController.startActivity()
        }

        Button {
            text: "Finalizar y Guardar (RF-31)"
            Layout.preferredWidth: 200
            onClicked: bleController.stopActivity()
        }
    }
}
