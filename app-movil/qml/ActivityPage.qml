// ActivityPage.qml - Pestaña Deporte (wireframe 8.1 y resumen): elegir actividad, iniciar/finalizar,
// ver el resumen y la lista de actividades guardadas.
// Mientras hay una actividad en marcha, la base de datos guarda 1 medición por segundo (RF-30).
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: page
    readonly property var types: ["walk", "run", "cycling", "swim", "hiking", "strength", "training", "other"]
    property string selected: "run"
    property var saved: []
    property var summary: ({})
    property var summaryPts: []

    function reloadSaved() { if (db.loggedIn) saved = db.activities() }
    Component.onCompleted: reloadSaved()
    function fmt(sec) { var m = Math.floor(sec / 60), s = sec % 60; return (m < 10 ? "0" : "") + m + ":" + (s < 10 ? "0" : "") + s }
    function n(v, d) { return (v === null || v === undefined) ? "--" : Number(v).toFixed(d) }

    Flickable {
        anchors.fill: parent; contentHeight: col.height + 30; clip: true
        ColumnLayout {
            id: col; x: Theme.margin; width: parent.width - 2 * Theme.margin; spacing: 14

            Text { text: Lang.t("activities"); color: Theme.white; font.pixelSize: Theme.fontTitle; font.bold: true }

            // ---------- Elegir actividad (solo si no hay una en marcha) ----------
            ColumnLayout { visible: !db.activityActive; Layout.fillWidth: true; spacing: 10
                Text { text: Lang.t("chooseActivity"); color: Theme.gray }
                Flow { Layout.fillWidth: true; spacing: 8
                    Repeater { model: page.types
                        delegate: Rectangle {
                            height: 38; width: chipTxt.implicitWidth + 28; radius: 19
                            property bool on: page.selected === modelData
                            color: on ? Theme.blue : Theme.surface; border.width: 1; border.color: on ? Theme.cyan : Theme.grayDark
                            Behavior on color { ColorAnimation { duration: 180 } }
                            Text { id: chipTxt; anchors.centerIn: parent; text: Lang.t(modelData); color: Theme.white; font.pixelSize: Theme.fontSmall + 1 }
                            MouseArea { anchors.fill: parent; onClicked: page.selected = modelData }
                        }
                    }
                }
                VButton { text: Lang.t("startActivity"); iconName: "play"; Layout.fillWidth: true; enabled: ble.state === "connected"
                          onClicked: db.startActivity(page.selected) }
                Text { visible: ble.state !== "connected"; text: Lang.t("firstTime"); color: Theme.gray; font.pixelSize: Theme.fontSmall; wrapMode: Text.Wrap; Layout.fillWidth: true }
            }

            // ---------- Actividad en marcha: anillo giratorio + cronómetro ----------
            VCard { visible: db.activityActive; Layout.fillWidth: true; accent: Theme.cyan; autoHeight: false; Layout.preferredHeight: 300
                Item { anchors.centerIn: parent; width: 220; height: 220
                    Canvas {                                   // anillo que gira mientras se graba
                        id: ring; anchors.fill: parent
                        property real angle: 0
                        NumberAnimation on angle { from: 0; to: 6.2832; duration: 3000; loops: Animation.Infinite; running: db.activityActive }
                        onAngleChanged: requestPaint()
                        onPaint: { var c = getContext("2d"); c.reset(); c.lineWidth = 8; c.lineCap = "round"
                            c.strokeStyle = "#2A3850"; c.beginPath(); c.arc(110, 110, 98, 0, 6.2832); c.stroke()
                            c.strokeStyle = "#22D3EE"; c.beginPath(); c.arc(110, 110, 98, angle, angle + 1.6); c.stroke() }
                    }
                    Column { anchors.centerIn: parent; spacing: 4
                        Text { text: Lang.t(db.activityType); color: Theme.cyan; font.pixelSize: Theme.fontBody; anchors.horizontalCenter: parent.horizontalCenter }
                        Text { text: page.fmt(db.activitySeconds); color: Theme.white; font.pixelSize: 44; font.bold: true; anchors.horizontalCenter: parent.horizontalCenter }
                        Text { text: Math.round(ble.heartRate) + " " + Lang.t("bpm"); color: Theme.heart; font.pixelSize: 20; anchors.horizontalCenter: parent.horizontalCenter }
                    }
                }
            }
            VButton { visible: db.activityActive; text: Lang.t("stopActivity"); iconName: "stop"; Layout.fillWidth: true
                      onClicked: { page.summary = db.finishActivity(); page.summaryPts = db.activitySeries(page.summary.id, "hr"); page.reloadSaved(); sumPopup.open() } }

            // ---------- Actividades guardadas (desplegable) ----------
            Collapsible {
                Layout.fillWidth: true; title: Lang.t("savedActivities") + " (" + page.saved.length + ")"
                Repeater { model: page.saved
                    delegate: Rectangle { width: parent.width; height: 62; radius: 14; color: Theme.surface2
                        RowLayout { anchors.fill: parent; anchors.margins: 12
                            ColumnLayout { spacing: 2
                                Text { text: Lang.t(modelData.type); color: Theme.white; font.bold: true }
                                Text { text: Qt.formatDateTime(new Date(modelData.start), "dd/MM  hh:mm"); color: Theme.gray; font.pixelSize: Theme.fontSmall } }
                            Item { Layout.fillWidth: true }
                            Text { text: page.fmt(modelData.seconds) ; color: Theme.cyan; font.pixelSize: Theme.fontSmall + 1 }
                            Text { text: page.n(modelData.avgHr, 0) + " " + Lang.t("bpm"); color: Theme.heart; font.pixelSize: Theme.fontSmall + 1 }
                        } } }
            }
        }
    }

    // ---------- Ventana emergente con el resumen (wireframe "resumen de actividad") ----------
    Popup {
        id: sumPopup
        modal: true; anchors.centerIn: parent; width: parent.width - 40; padding: 18
        enter: Transition { ParallelAnimation {
            NumberAnimation { property: "scale"; from: 0.85; to: 1; duration: 250; easing.type: Easing.OutBack }
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 200 } } }
        Overlay.modal: Rectangle { color: "#CC050A14" }
        background: Rectangle { radius: Theme.radius; color: Theme.surface; border.color: Theme.cyan; border.width: 1 }
        contentItem: ColumnLayout { spacing: 12
            Text { text: Lang.t("summary") + " · " + Lang.t(page.summary.type || "other"); color: Theme.white; font.bold: true; font.pixelSize: Theme.fontTitle - 4 }
            Text { text: Lang.t("duration") + ": " + page.fmt(page.summary.seconds || 0); color: Theme.cyan }
            GridLayout { columns: 2; Layout.fillWidth: true
                Text { text: Lang.t("avg") + " " + Lang.t("heartRate"); color: Theme.gray; Layout.fillWidth: true }
                Text { text: page.n(page.summary.avgHr, 0) + " " + Lang.t("bpm"); color: Theme.heart; font.bold: true }
                Text { text: Lang.t("max"); color: Theme.gray; Layout.fillWidth: true }
                Text { text: page.n(page.summary.maxHr, 0) + " " + Lang.t("bpm"); color: Theme.heart; font.bold: true }
                Text { text: Lang.t("min"); color: Theme.gray; Layout.fillWidth: true }
                Text { text: page.n(page.summary.minHr, 0) + " " + Lang.t("bpm"); color: Theme.heart; font.bold: true }
                Text { text: Lang.t("respRate"); color: Theme.gray; Layout.fillWidth: true }
                Text { text: page.n(page.summary.avgRr, 1) + " " + Lang.t("rpm"); color: Theme.resp; font.bold: true }
            }
            LineChart { Layout.fillWidth: true; Layout.preferredHeight: 120; points: page.summaryPts; lineColor: Theme.heart }
            VButton { text: Lang.t("close"); Layout.fillWidth: true; onClicked: sumPopup.close() }
        }
    }
}
