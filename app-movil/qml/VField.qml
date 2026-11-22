// VField.qml - Campo de texto con icono. Cuando lo tocas, el borde se ilumina en cian.
// USO:  VField { placeholderText: "Usuario"; icon: "user"; secret: false }
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

TextField {
    id: f
    property string icon: "user"
    property bool secret: false
    implicitHeight: 52
    color: Theme.white
    placeholderTextColor: Theme.gray
    font.pixelSize: Theme.fontBody
    echoMode: secret ? TextInput.Password : TextInput.Normal
    leftPadding: 48
    verticalAlignment: TextInput.AlignVCenter
    selectByMouse: true

    background: Rectangle {
        radius: 16
        color: Theme.surface
        border.width: f.activeFocus ? 2 : 1
        border.color: f.activeFocus ? Theme.cyan : Theme.grayDark
        Behavior on border.color { ColorAnimation { duration: 150 } }
        Icon { x: 14; anchors.verticalCenter: parent.verticalCenter; name: f.icon; size: 22; color: f.activeFocus ? Theme.cyan : Theme.gray }
    }
}
