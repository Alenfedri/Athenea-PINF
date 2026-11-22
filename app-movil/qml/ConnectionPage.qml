// ConnectionPage.qml - Wireframe 3.1: estado de la conexión, búsqueda y emparejamiento con VitaBand.
// Tres situaciones: DESCONECTADO (buscar) · BUSCANDO (radar + lista) · CONECTADO (desconectar).
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: page
    GradientBg { anchors.fill: parent }
    PageHeader { id: hdr; title: Lang.t("connection"); anchors { top: parent.top; left: parent.left; right: parent.right } }

    Flickable {
        anchors { top: hdr.bottom; left: parent.left; right: parent.right; bottom: parent.bottom }
        contentHeight: col.height + 30; clip: true
        ColumnLayout {
            id: col; x: Theme.margin; width: parent.width - 2 * Theme.margin; spacing: 14

            // ---------- Radar + imagen de la banda ----------
            Item {
                Layout.fillWidth: true; Layout.preferredHeight: 220
                Repeater {                                    // 3 aros que se expanden mientras se busca
                    model: 3
                    delegate: Rectangle {
                        anchors.centerIn: parent; width: 120; height: 120; radius: 60
                        color: "transparent"; border.width: 2; border.color: Theme.cyan; opacity: 0
                        ParallelAnimation { running: ble.state === "scanning" || ble.state === "connecting"; loops: Animation.Infinite
                            SequentialAnimation { PauseAnimation { duration: index * 600 }
                                ParallelAnimation {
                                    NumberAnimation { target: parent; property: "scale"; from: 0.8; to: 2.4; duration: 1800; easing.type: Easing.OutQuad }
                                    NumberAnimation { target: parent; property: "opacity"; from: 0.7; to: 0; duration: 1800 } } } }
                    }
                }
                Image { anchors.centerIn: parent; source: "../assets/img/band.svg"; width: 260; fillMode: Image.PreserveAspectFit
                    SequentialAnimation on scale { loops: Animation.Infinite
                        NumberAnimation { to: 1.04; duration: 1400; easing.type: Easing.InOutSine }
                        NumberAnimation { to: 0.98; duration: 1400; easing.type: Easing.InOutSine } } }
            }

            // ---------- Estado ----------
            VCard { Layout.fillWidth: true; accent: ble.state === "connected" ? Theme.cyan : Theme.blue
                RowLayout { width: parent.width; spacing: 12
                    StatusDot { color: ble.state === "connected" ? Theme.cyan : (ble.state === "error" ? "#FF7B8A" : Theme.gray); pulsing: ble.state !== "disconnected" && ble.state !== "error" }
                    ColumnLayout { Layout.fillWidth: true; spacing: 2
                        Text { text: Lang.t(ble.state); color: Theme.white; font.bold: true; font.pixelSize: Theme.fontBody }
                        Text { text: ble.state === "connected" ? ble.deviceName : (ble.errorText !== "" ? (ble.errorText === "permission" ? Lang.t("permission") : ble.errorText) : Lang.t("firstTime"))
                               color: Theme.gray; font.pixelSize: Theme.fontSmall; wrapMode: Text.Wrap; Layout.fillWidth: true }
                    }
                }
            }

            // ---------- Botones según el estado ----------
            VButton { visible: ble.state === "disconnected" || ble.state === "error"; text: Lang.t("scan"); iconName: "bluetooth"; Layout.fillWidth: true; onClicked: ble.startScan() }
            VButton { visible: ble.state === "disconnected" || ble.state === "error"; text: Lang.t("demo"); iconName: "play"; primary: false; Layout.fillWidth: true; onClicked: ble.startSimulation() }
            VButton { visible: ble.state === "connected"; text: Lang.t("disconnect"); iconName: "stop"; primary: false; tint: "#FF7B8A"; Layout.fillWidth: true; onClicked: ble.disconnectDevice() }

            // ---------- Lista de dispositivos encontrados ----------
            Text { visible: ble.devices.length > 0 && ble.state !== "connected"; text: Lang.t("foundDevices"); color: Theme.gray }
            Repeater {
                model: ble.state === "connected" ? [] : ble.devices
                delegate: VCard { Layout.fillWidth: true; padding: 14; clickable: true; delay: index * 80
                    onClicked: ble.connectTo(index)
                    RowLayout { width: parent.width; spacing: 12
                        Icon { name: "bluetooth"; color: Theme.cyan }
                        ColumnLayout { spacing: 2; Layout.fillWidth: true
                            Text { text: modelData.name; color: Theme.white; font.bold: true }
                            Text { text: modelData.address + "  ·  " + Lang.t("signal") + " " + modelData.rssi + " dBm"; color: Theme.gray; font.pixelSize: 11; elide: Text.ElideRight; Layout.fillWidth: true } }
                        Text { text: Lang.t("connect"); color: Theme.cyan; font.bold: true }
                    }
                }
            }

            // ---------- Casilla: no volver a mostrar esta pantalla al iniciar ----------
            CheckBox {
                text: Lang.t("skipConnect"); checked: Nav.prefs.skipConnect
                onToggled: Nav.prefs.skipConnect = checked
                contentItem: Text { text: parent.text; color: Theme.gray; font.pixelSize: Theme.fontSmall + 1; leftPadding: 34; verticalAlignment: Text.AlignVCenter; wrapMode: Text.Wrap }
            }
            VButton { text: Lang.t("continueBtn"); primary: false; Layout.fillWidth: true; onClicked: Nav.pop() }
        }
    }
}
