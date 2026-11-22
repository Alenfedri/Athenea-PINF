// EcgPage.qml - Pestaña ECG (wireframe 4.3): señal del corazón en directo + estado + interruptor del filtro.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: ecgPage
    property string clock: Qt.formatTime(new Date(), "hh:mm:ss")
    Timer { interval: 1000; running: ecgPage.visible; repeat: true; onTriggered: ecgPage.clock = Qt.formatTime(new Date(), "hh:mm:ss") }

    ColumnLayout {
        x: Theme.margin; y: 6; width: parent.width - 2 * Theme.margin; spacing: 14

        Text { text: Lang.t("ecgTitle"); color: Theme.white; font.pixelSize: Theme.fontTitle; font.bold: true }

        RowLayout { spacing: 10
            // Indicador "EN DIRECTO" con punto parpadeante
            Rectangle { radius: 12; color: Theme.surface; border.color: live ? Theme.cyan : Theme.grayDark
                Layout.preferredHeight: 28; Layout.preferredWidth: lbl.implicitWidth + 40
                property bool live: ble.state === "connected"
                Row { anchors.centerIn: parent; spacing: 6
                    StatusDot { anchors.verticalCenter: parent.verticalCenter; color: parent.parent.live ? Theme.cyan : Theme.gray; pulsing: parent.parent.live }
                    Text { id: lbl; text: parent.parent.live ? Lang.t("live") : Lang.t("noSignal"); color: Theme.white; font.pixelSize: 11; font.bold: true }
                }
            }
            Text { text: ble.state === "connected" ? Lang.t("signalOk") : ""; color: Theme.cyan; font.pixelSize: Theme.fontSmall }
            Item { Layout.fillWidth: true }
            Text { text: Lang.t("lastUpdate") + " " + clock; color: Theme.gray; font.pixelSize: Theme.fontSmall }
        }

        Rectangle {                                    // marco del monitor
            Layout.fillWidth: true; Layout.preferredHeight: 260; radius: Theme.radius
            color: Theme.black; border.width: 1; border.color: Theme.cyan; clip: true
            EcgChart { anchors.fill: parent; anchors.margins: 4; active: ble.state === "connected" }
            Column { anchors.centerIn: parent; spacing: 8; visible: ble.state !== "connected"
                Image { source: "../assets/img/empty.svg"; anchors.horizontalCenter: parent.horizontalCenter }
                Text { text: Lang.t("noSignal"); color: Theme.gray; anchors.horizontalCenter: parent.horizontalCenter } }
        }

        VCard { Layout.fillWidth: true; accent: Theme.blue
            RowLayout { width: parent.width
                Text { text: Lang.t("filterOff"); color: Theme.white; Layout.fillWidth: true; font.pixelSize: Theme.fontBody }
                Switch { checked: ble.ecgFilterOff; onToggled: ble.ecgFilterOff = checked }
            }
        }
    }
}
