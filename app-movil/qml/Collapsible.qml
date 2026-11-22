// Collapsible.qml - Sección DESPLEGABLE: pulsas el título y se abre/cierra con animación.
// USO:  Collapsible { title: "Filtros"; Text { text: "contenido" } }
import QtQuick
import QtQuick.Layouts

Rectangle {
    id: c
    property string title: ""
    property string icon: "chevron"
    property bool expanded: false
    default property alias content: body.data

    implicitHeight: head.height + (expanded ? body.height + 16 : 0)
    clip: true
    radius: Theme.radius
    color: Theme.surface
    border.width: 1; border.color: expanded ? Theme.cyan : Theme.grayDark
    Behavior on implicitHeight { NumberAnimation { duration: 280; easing.type: Easing.OutCubic } }
    Behavior on border.color { ColorAnimation { duration: 200 } }

    Item {
        id: head
        width: parent.width; height: 56
        RowLayout {
            anchors.fill: parent; anchors.leftMargin: 16; anchors.rightMargin: 16; spacing: 10
            Text { text: c.title; color: Theme.white; font.pixelSize: Theme.fontBody; font.bold: true; Layout.fillWidth: true }
            Icon { name: "chevron"; size: 22; color: Theme.cyan; rotation: c.expanded ? 180 : 0
                   Behavior on rotation { NumberAnimation { duration: 250 } } }
        }
        MouseArea { anchors.fill: parent; onClicked: c.expanded = !c.expanded }
    }
    Column {
        id: body
        x: 16; y: head.height; width: c.width - 32; spacing: 10
        opacity: c.expanded ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 250 } }
    }
}
