import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Page {
    title: "Autenticación"
    
    ColumnLayout {
        anchors.centerIn: parent
        spacing: 20

        Text {
            text: "VitaBand"
            font.pixelSize: 32
            font.bold: true
            Layout.alignment: Qt.AlignHCenter
        }

        TextField {
            id: userInput
            placeholderText: "Usuario"
            Layout.preferredWidth: 250
        }

        TextField {
            id: passInput
            placeholderText: "Contraseña"
            echoMode: TextInput.Password
            Layout.preferredWidth: 250
        }

        Button {
            text: "Iniciar Sesión (RF-01)"
            Layout.preferredWidth: 250
            onClicked: {
                if (userInput.text !== "") {
                    stackView.push("Dashboard.qml")
                }
            }
        }
    }
}
