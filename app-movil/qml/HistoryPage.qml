// HistoryPage.qml - Pestaña Historial (wireframes 4.2, 5.1 y 5.2): gráfica de evolución + filtros + lista.
// Los datos salen de la base de datos con db.series(...) (gráfica) y db.history(...) (lista).
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: page
    property var rows: []
    property var pts: []
    // Elecciones del usuario guardadas en la página (los controles del encabezado no son visibles desde fuera)
    property int rangeIdx: 1
    property int kindIdx: 0
    property int varIdx: 0
    readonly property var fields: ["hr", "rr", "temp", "activity"]
    readonly property var fieldColors: [Theme.heart, Theme.resp, Theme.temp, Theme.act]

    // Calcula el intervalo "desde - hasta" según la opción elegida en "Periodo"
    function range() {
        var now = Date.now(), d = new Date(); d.setHours(0, 0, 0, 0)
        switch (rangeIdx) {
        case 0: return [now - 3600000, now]
        case 1: return [d.getTime(), now]
        case 2: return [now - 7 * 86400000, now]
        default: return [now - 30 * 86400000, now]
        }
    }
    function reload() {
        if (!db.loggedIn) return
        var r = range()
        var kinds = ["all", "periodic", "activity"]
        rows = db.history(r[0], r[1], kinds[kindIdx], 200)
        pts = db.series(r[0], r[1], fields[varIdx], 100)
    }
    Component.onCompleted: reload()
    onVisibleChanged: if (visible) reload()
    Connections { target: db; function onDataChanged() { if (page.visible) page.reload() } }

    ListView {
        id: list
        anchors.fill: parent; clip: true; spacing: 8
        model: page.rows
        leftMargin: Theme.margin; rightMargin: Theme.margin; bottomMargin: 20

        header: ColumnLayout {
            width: list.width - 2 * Theme.margin; spacing: 12
            Text { text: Lang.t("history"); color: Theme.white; font.pixelSize: Theme.fontTitle; font.bold: true }
            // Filtros DESPLEGABLES (wireframe 5.2)
            Collapsible {
                Layout.fillWidth: true; title: Lang.t("filters"); expanded: false
                Text { text: Lang.t("range"); color: Theme.gray; font.pixelSize: Theme.fontSmall }
                VCombo { id: rangeBox; width: parent.width; model: [Lang.t("last1h"), Lang.t("today"), Lang.t("last7"), Lang.t("last30")]; currentIndex: page.rangeIdx; onActivated: { page.rangeIdx = currentIndex; page.reload() } }
                Text { text: Lang.t("type"); color: Theme.gray; font.pixelSize: Theme.fontSmall }
                VCombo { id: kindBox; width: parent.width; model: [Lang.t("all"), Lang.t("periodic"), Lang.t("sport")]; currentIndex: page.kindIdx; onActivated: { page.kindIdx = currentIndex; page.reload() } }
            }
            VCombo { id: varBox; Layout.fillWidth: true; model: [Lang.t("heartRate"), Lang.t("respRate"), Lang.t("temperature"), Lang.t("activityLevel")]; currentIndex: page.varIdx; onActivated: { page.varIdx = currentIndex; page.reload() } }
            VCard {
                Layout.fillWidth: true; accent: page.fieldColors[page.varIdx]; autoHeight: false; Layout.preferredHeight: 210; padding: 10
                LineChart { anchors.fill: parent; animateOnChange: true; points: page.pts; lineColor: page.fieldColors[page.varIdx] }
            }
            Text { visible: page.rows.length === 0; text: Lang.t("noData"); color: Theme.gray; Layout.alignment: Qt.AlignHCenter; Layout.topMargin: 20 }
        }

        delegate: VCard {
            width: list.width - 2 * Theme.margin; padding: 12
            accent: modelData.kind === "activity" ? Theme.blue : Theme.cyan
            RowLayout { width: parent.width; spacing: 10
                ColumnLayout { spacing: 2
                    Text { text: Qt.formatDate(new Date(modelData.ts), "dd/MM/yy"); color: Theme.white; font.bold: true; font.pixelSize: Theme.fontSmall + 1 }
                    Text { text: Qt.formatTime(new Date(modelData.ts), "hh:mm:ss"); color: Theme.gray; font.pixelSize: Theme.fontSmall }
                }
                Item { Layout.fillWidth: true }
                Text { text: Math.round(modelData.hr) + " " + Lang.t("bpm"); color: Theme.heart; font.pixelSize: Theme.fontSmall + 1 }
                Text { text: modelData.rr.toFixed(1) + " " + Lang.t("rpm"); color: Theme.resp; font.pixelSize: Theme.fontSmall + 1 }
                Text { text: modelData.temp.toFixed(1) + "°"; color: Theme.temp; font.pixelSize: Theme.fontSmall + 1 }
            }
        }
        // Animación al aparecer/desaparecer filas
        add: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 250 } }
    }
}
