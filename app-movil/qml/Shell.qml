// Shell.qml - El "armazón" de la app una vez dentro: arriba una barra con el estado de la banda,
// en medio la pantalla de la pestaña activa y abajo la barra de pestañas.
//   Pestañas:  0 Inicio (MonitorPage) · 1 ECG · 2 Historial · 3 Deporte · 4 Más
//   Desde "Más" y desde la barra superior se abren pantallas extra (Nav.push).
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: shell
    property int current: 0
    GradientBg { anchors.fill: parent }

    // ---------- Barra superior ----------
    Item {
        id: top
        anchors { top: parent.top; left: parent.left; right: parent.right }
        height: 64
        RowLayout {
            anchors.fill: parent; anchors.leftMargin: Theme.margin; anchors.rightMargin: 8; spacing: 10
            Image { source: "../assets/img/logo.svg"; Layout.preferredWidth: 34; Layout.preferredHeight: 34 }
            ColumnLayout { spacing: 0
                Text { text: "VitaBand"; color: Theme.white; font.pixelSize: 18; font.bold: true }
                Text { text: db.userName; color: Theme.gray; font.pixelSize: Theme.fontSmall }
            }
            Item { Layout.fillWidth: true }
            // Chip de estado de la banda: pulsa para abrir la pantalla de conexión
            Rectangle {
                Layout.preferredHeight: 36; Layout.preferredWidth: chip.implicitWidth + 36; radius: 18
                color: Theme.surface; border.width: 1
                border.color: ble.state === "connected" ? Theme.cyan : Theme.grayDark
                RowLayout { id: chip; anchors.centerIn: parent; spacing: 8
                    StatusDot { color: ble.state === "connected" ? Theme.cyan : (ble.state === "error" ? "#FF7B8A" : Theme.gray)
                                pulsing: ble.state === "connected" || ble.state === "scanning" || ble.state === "connecting" }
                    Text { text: Lang.t(ble.state); color: Theme.white; font.pixelSize: Theme.fontSmall }
                }
                MouseArea { anchors.fill: parent; onClicked: Nav.push("connection") }
            }
            Item { Layout.preferredWidth: 44; Layout.preferredHeight: 44
                Icon { anchors.centerIn: parent; name: "settings"; size: 24; color: Theme.gray }
                MouseArea { anchors.fill: parent; onClicked: Nav.push("settings") } }
        }
    }

    // ---------- Contenido de la pestaña activa ----------
    StackLayout {
        anchors { top: top.bottom; bottom: tabs.top; left: parent.left; right: parent.right }
        currentIndex: shell.current
        MonitorPage {}
        EcgPage {}
        HistoryPage {}
        ActivityPage {}
        MorePage {}
    }

    // ---------- Barra de pestañas inferior ----------
    Rectangle {
        id: tabs
        anchors { bottom: parent.bottom; left: parent.left; right: parent.right }
        height: 68; color: Theme.black
        Rectangle { width: parent.width; height: 1; color: Theme.grayDark }
        // La "píldora" cian que se desliza bajo la pestaña activa
        Rectangle {
            width: tabs.width / 5 - 24; height: 3; radius: 2; color: Theme.cyan; y: 0
            x: shell.current * tabs.width / 5 + 12
            Behavior on x { NumberAnimation { duration: 280; easing.type: Easing.OutBack } }
        }
        Row {
            anchors.fill: parent
            Repeater {
                model: [ {i: "heart", k: "tabMonitor"}, {i: "ecg", k: "tabEcg"}, {i: "history", k: "tabHistory"},
                         {i: "timer", k: "tabActivity"}, {i: "menu", k: "tabMore"} ]
                delegate: Item {
                    width: tabs.width / 5; height: tabs.height
                    property bool on: shell.current === index
                    Column { anchors.centerIn: parent; spacing: 3
                        Icon { anchors.horizontalCenter: parent.horizontalCenter; name: modelData.i; size: 24
                               color: on ? Theme.cyan : Theme.gray; scale: on ? 1.2 : 1
                               Behavior on scale { NumberAnimation { duration: 200; easing.type: Easing.OutBack } } }
                        Text { anchors.horizontalCenter: parent.horizontalCenter; text: Lang.t(modelData.k)
                               color: on ? Theme.cyan : Theme.gray; font.pixelSize: 11 }
                    }
                    MouseArea { anchors.fill: parent; onClicked: shell.current = index }
                }
            }
        }
    }
}
