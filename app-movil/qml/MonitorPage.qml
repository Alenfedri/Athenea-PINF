// MonitorPage.qml - Pestaña "Inicio" (wireframe 4.1): valores en tiempo real en 4 tarjetas.
// Corazón en CIAN, respiración en AZUL (como pide el wireframe), temperatura y actividad en tonos azulados.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: page
    // Historial reciente de cada dato para las mini-gráficas (últimos 60 segundos)
    property var hrH: []
    property var rrH: []
    property var tH: []
    function pushVal(arr, v) { var a = arr.slice(); a.push({ t: Date.now(), v: v }); if (a.length > 60) a.shift(); return a }

    Timer {
        interval: 1000; repeat: true; running: ble.state === "connected"
        onTriggered: { hrH = pushVal(hrH, ble.heartRate); rrH = pushVal(rrH, ble.respRate); tH = pushVal(tH, ble.temperature) }
    }
    function actText(a) { return a === 0 ? Lang.t("rest") : a === 1 ? Lang.t("medium") : a === 2 ? Lang.t("intense") : "--" }

    Flickable {
        anchors.fill: parent
        contentHeight: col.height + 30; clip: true
        ColumnLayout {
            id: col
            x: Theme.margin; width: parent.width - 2 * Theme.margin; spacing: 12

            // --- Aviso si no hay banda conectada ---
            VCard {
                Layout.fillWidth: true; accent: Theme.blue; visible: ble.state !== "connected"; clickable: true
                onClicked: Nav.push("connection")
                RowLayout { width: parent.width; spacing: 12
                    Image { source: "../assets/img/band.svg"; Layout.preferredWidth: 90; Layout.preferredHeight: 50; fillMode: Image.PreserveAspectFit }
                    Text { text: Lang.t("firstTime"); color: Theme.white; wrapMode: Text.Wrap; Layout.fillWidth: true; font.pixelSize: Theme.fontSmall + 1 }
                    Icon { name: "bluetooth"; color: Theme.cyan }
                }
            }
            // --- Aviso del microcontrolador (taquicardia, etc.) ---
            VCard {
                Layout.fillWidth: true; accent: "#FF7B8A"; visible: ble.alert >= 0 && ble.alert <= 2 && ble.state === "connected"
                RowLayout { width: parent.width; spacing: 10
                    Icon { name: "warning"; color: "#FF7B8A" }
                    Text { text: Lang.t("alert" + ble.alert); color: Theme.white; font.bold: true; font.pixelSize: Theme.fontBody; Layout.fillWidth: true }
                }
            }
            // --- Calibrando ---
            Text { visible: ble.state === "connecting"; text: Lang.t("calibrating"); color: Theme.cyan; Layout.alignment: Qt.AlignHCenter }

            GridLayout {
                Layout.fillWidth: true; columns: 2; columnSpacing: 12; rowSpacing: 12
                VitalCard { Layout.fillWidth: true; Layout.preferredHeight: 170; delay: 0
                    label: Lang.t("heartRate"); unit: Lang.t("bpm"); icon: "heart"; accent: Theme.heart; value: ble.heartRate; pulse: true; history: page.hrH }
                VitalCard { Layout.fillWidth: true; Layout.preferredHeight: 170; delay: 100
                    label: Lang.t("respRate"); unit: Lang.t("rpm"); icon: "lungs"; accent: Theme.resp; value: ble.respRate; decimals: 1; history: page.rrH }
                VitalCard { Layout.fillWidth: true; Layout.preferredHeight: 170; delay: 200
                    label: Lang.t("temperature"); unit: Lang.t("celsius"); icon: "thermo"; accent: Theme.temp; value: ble.temperature; decimals: 1; history: page.tH }
                VitalCard { Layout.fillWidth: true; Layout.preferredHeight: 170; delay: 300
                    label: Lang.t("activityLevel"); icon: "bolt"; accent: Theme.act; value: ble.activity <= 2 ? 1 : 0
                    textValue: ble.state === "connected" ? page.actText(ble.activity) : "" }
            }
            Text { text: Lang.t("infoOnly"); color: Theme.gray; font.pixelSize: 11; wrapMode: Text.Wrap; Layout.fillWidth: true }
        }
    }
}
