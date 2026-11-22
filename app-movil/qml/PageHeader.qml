// PageHeader.qml - Barra superior de las pantallas "secundarias": flecha de volver + título.
import QtQuick
import QtQuick.Layouts

Item {
    property string title: ""
    property bool showBack: true
    implicitHeight: 64
    RowLayout {
        anchors.fill: parent; anchors.leftMargin: 8; anchors.rightMargin: Theme.margin; spacing: 4
        Item {
            visible: showBack; Layout.preferredWidth: 48; Layout.preferredHeight: 48
            Icon { anchors.centerIn: parent; name: "back"; size: 26; color: Theme.cyan }
            MouseArea { anchors.fill: parent; onClicked: Nav.pop() }
        }
        Text { text: title; color: Theme.white; font.pixelSize: Theme.fontTitle; font.bold: true; Layout.fillWidth: true; leftPadding: showBack ? 0 : 10; elide: Text.ElideRight }
    }
}
