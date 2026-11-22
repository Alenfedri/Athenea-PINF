// StatsPage.qml - Wireframes 7.1 y 7.2: estadísticas (mín/media/máx), reparto de actividad y observaciones.
// Las observaciones son orientativas, NUNCA diagnósticos (RF-23). Distinguen reposo de ejercicio (RF-25).
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: page
    property var st: ({})
    property var dist: [0, 0, 0]
    property var obs: []
    property int periodIdx: 0

    function n(v, d) { return (v === null || v === undefined) ? "--" : Number(v).toFixed(d) }
    function reload() {
        var now = Date.now(), span = [1, 7, 30][periodIdx] * 86400000
        st = db.stats(now - span, now)
        dist = db.activityDistribution(now - span, now)
        obs = db.observations(now - span, now)
    }
    // Traduce un código como "REST_HR:72" a una frase en el idioma actual
    function obsText(code) {
        var parts = code.split(":")
        var txt = Lang.t("o_" + parts[0])
        return parts.length > 1 ? txt.replace("%1", parts[1]) : txt
    }
    Component.onCompleted: reload()

    GradientBg { anchors.fill: parent }
    PageHeader { id: hdr; title: Lang.t("stats"); anchors { top: parent.top; left: parent.left; right: parent.right } }

    Flickable {
        anchors { top: hdr.bottom; left: parent.left; right: parent.right; bottom: parent.bottom }
        contentHeight: col.height + 30; clip: true
        ColumnLayout {
            id: col; x: Theme.margin; width: parent.width - 2 * Theme.margin; spacing: 12

            VCombo { Layout.fillWidth: true; model: [Lang.t("day"), Lang.t("week"), Lang.t("month")]
                     currentIndex: page.periodIdx; onActivated: { page.periodIdx = currentIndex; page.reload() } }

            // Tarjetas mín / media / máx
            Repeater {
                model: [
                    { k: "heartRate", c: Theme.heart, a: "hrAvg", lo: "hrMin", hi: "hrMax", d: 0, u: "bpm" },
                    { k: "respRate",  c: Theme.resp,  a: "rrAvg", lo: "rrMin", hi: "rrMax", d: 1, u: "rpm" },
                    { k: "temperature", c: Theme.temp, a: "tAvg", lo: "tMin",  hi: "tMax",  d: 1, u: "celsius" } ]
                delegate: VCard { id: statCard; property var def: modelData; Layout.fillWidth: true; accent: modelData.c; delay: index * 100
                    ColumnLayout { width: parent.width; spacing: 6
                        Text { text: Lang.t(modelData.k); color: modelData.c; font.bold: true }
                        RowLayout { Layout.fillWidth: true
                            Repeater { model: [ { l: "min", f: modelData.lo }, { l: "avg", f: modelData.a }, { l: "max", f: modelData.hi } ]
                                delegate: ColumnLayout { Layout.fillWidth: true; spacing: 0
                                    Text { text: Lang.t(modelData.l); color: Theme.gray; font.pixelSize: Theme.fontSmall }
                                    Text { text: page.n(page.st[modelData.f], statCard.def.d) ; color: Theme.white; font.pixelSize: 24; font.bold: true } } } }
                    }
                }
            }

            // Reparto de actividad: barras animadas
            VCard { Layout.fillWidth: true; accent: Theme.act
                ColumnLayout { width: parent.width; spacing: 8
                    Text { text: Lang.t("activityLevel"); color: Theme.act; font.bold: true }
                    Repeater { model: [ { k: "rest", i: 0 }, { k: "medium", i: 1 }, { k: "intense", i: 2 } ]
                        delegate: RowLayout { Layout.fillWidth: true; spacing: 10
                            Text { text: Lang.t(modelData.k); color: Theme.gray; Layout.preferredWidth: 70; font.pixelSize: Theme.fontSmall + 1 }
                            Rectangle { Layout.fillWidth: true; height: 14; radius: 7; color: Theme.grayDark
                                Rectangle { height: parent.height; radius: 7; color: Theme.act
                                    width: { var t = page.dist[0] + page.dist[1] + page.dist[2]; return t > 0 ? parent.width * page.dist[modelData.i] / t : 0 }
                                    Behavior on width { NumberAnimation { duration: 700; easing.type: Easing.OutCubic } } } }
                        } }
                }
            }

            // Observaciones
            VCard { Layout.fillWidth: true; accent: Theme.blue
                ColumnLayout { width: parent.width; spacing: 8
                    Text { text: Lang.t("observations"); color: Theme.cyan; font.bold: true }
                    Repeater { model: page.obs
                        delegate: RowLayout { Layout.fillWidth: true; spacing: 8
                            Icon { name: "check"; size: 16; color: Theme.cyan; Layout.alignment: Qt.AlignTop }
                            Text { text: page.obsText(modelData); color: Theme.white; wrapMode: Text.Wrap; Layout.fillWidth: true; font.pixelSize: Theme.fontSmall + 2 } } }
                    Text { text: Lang.t("infoOnly"); color: Theme.gray; font.pixelSize: 11; wrapMode: Text.Wrap; Layout.fillWidth: true }
                }
            }
        }
    }
}
