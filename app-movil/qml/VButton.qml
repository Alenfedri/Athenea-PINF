// VButton.qml - Botón con estilo VitaBand. "primary" = relleno azul-cian; si no, solo borde.
// Se encoge un poquito al pulsarlo (animación) para que se sienta "táctil".
// USO:  VButton { text: "Guardar"; iconName: "check"; onClicked: ... }
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Button {
    id: b
    property bool primary: true
    property string iconName: ""
    property color tint: Theme.cyan
    implicitHeight: 50
    implicitWidth: 140
    scale: down ? 0.96 : 1
    opacity: enabled ? 1 : 0.4
    Behavior on scale { NumberAnimation { duration: 100 } }

    background: Rectangle {
        radius: 16
        border.width: b.primary ? 0 : 1.5
        border.color: b.tint
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0; color: b.primary ? Theme.blue : "transparent" }
            GradientStop { position: 1; color: b.primary ? Theme.cyan : "transparent" }
        }
    }
    contentItem: RowLayout {
        spacing: 8
        Item { Layout.fillWidth: true }
        Icon { visible: b.iconName !== ""; name: b.iconName; size: 20; color: b.primary ? Theme.black : b.tint }
        Text {
            text: b.text
            color: b.primary ? Theme.black : b.tint
            font.pixelSize: Theme.fontBody; font.bold: true
        }
        Item { Layout.fillWidth: true }
    }
}
