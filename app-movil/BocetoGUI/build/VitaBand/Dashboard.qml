import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import VitaBand 1.0

Page {
    title: "Monitorización"

    BleController {
        id: bleCtrl
        onDeviceFound: (name, address) => {
            bleCtrl.connectToDevice(address)
        }
    }

    header: ToolBar {
        RowLayout {
            anchors.fill: parent
            ToolButton {
                text: "Cerrar Sesión"
                onClicked: {
                    bleCtrl.disconnectDevice()
                    stackView.pop() // RF-02
                }
            }
            Item { Layout.fillWidth: true }
            ToolButton {
                text: "Deporte"
                onClicked: stackView.push("Activity.qml", {bleController: bleCtrl})
            }
        }
    }

    ColumnLayout {
        anchors.centerIn: parent
        spacing: 20

        Label {
            text: bleCtrl.isConnected ? "Estado: CONECTADO" : "Estado: DESCONECTADO (RF-11)"
            color: bleCtrl.isConnected ? "green" : "red"
            font.bold: true
            Layout.alignment: Qt.AlignHCenter
        }

        Button {
            text: bleCtrl.isConnected ? "Desconectar VitaBand" : "Buscar VitaBand (RF-04)"
            Layout.alignment: Qt.AlignHCenter
            onClicked: {
                if (bleCtrl.isConnected) bleCtrl.disconnectDevice()
                else bleCtrl.scanDevices()
            }
        }

        GridLayout {
            columns: 2
            rowSpacing: 10
            columnSpacing: 20
            visible: bleCtrl.isConnected
            Layout.alignment: Qt.AlignHCenter

            Label { text: "Frecuencia Cardíaca:" }
            Label { text: bleCtrl.heartRate + " bpm" ; font.bold: true }

            Label { text: "Frec. Respiratoria:" }
            Label { text: bleCtrl.respRate + " rpm" ; font.bold: true }

            Label { text: "Temperatura:" }
            Label { text: bleCtrl.temperature + " °C" ; font.bold: true }
        }

        Rectangle {
            width: 300
            height: 120
            color: "#222"
            radius: 8
            visible: bleCtrl.isConnected
            Layout.alignment: Qt.AlignHCenter
            
            Text {
                text: "Señal ECG (RF-10)"
                color: "#0f0"
                anchors.centerIn: parent
            }
        }
    }
}
