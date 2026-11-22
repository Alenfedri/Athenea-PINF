// Toast.qml - Mensajito flotante que aparece abajo unos segundos y se va. Uso: Nav.toast("Hola")
import QtQuick

Rectangle {
    id: t
    property string message: ""
    function show(m) { message = m; anim.restart() }
    anchors.horizontalCenter: parent.horizontalCenter
    y: parent.height - 120
    width: Math.min(parent.width - 40, label.implicitWidth + 40); height: 48; radius: 24
    color: Theme.surface2; border.color: Theme.cyan; border.width: 1
    opacity: 0; z: 100
    Text { id: label; anchors.centerIn: parent; text: t.message; color: Theme.white; font.pixelSize: Theme.fontSmall + 1 }
    SequentialAnimation { id: anim
        NumberAnimation { target: t; property: "opacity"; to: 1; duration: 200 }
        PauseAnimation { duration: 2500 }
        NumberAnimation { target: t; property: "opacity"; to: 0; duration: 400 } }
}
