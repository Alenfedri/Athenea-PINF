// SyncPage.qml - Wireframe 6.1: sincronización móvil -> ordenador.
// ¿Cómo funciona? 1) La base de datos reúne todo lo pendiente en un archivo JSON (db.exportPending()).
//                 2) Ese archivo es el "paquete" que leerá la app de escritorio.
//                 3) Al terminar se marcan los datos como enviados (db.markSynced()) y no se repiten.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: page
    property real progress: 0
    property string result: ""
    property string path: ""
    property bool busy: false

    GradientBg { anchors.fill: parent }
    PageHeader { id: hdr; title: Lang.t("sync"); anchors { top: parent.top; left: parent.left; right: parent.right } }

    SequentialAnimation {                                      // barra de progreso animada
        id: run
        ScriptAction { script: { page.busy = true; page.result = Lang.t("syncing"); page.progress = 0; page.path = db.exportPending() } }
        NumberAnimation { target: page; property: "progress"; from: 0; to: 1; duration: 2200; easing.type: Easing.InOutQuad }
        ScriptAction { script: { db.markSynced(); page.busy = false; page.result = Lang.t("syncDone") } }
    }

    ColumnLayout {
        anchors { top: hdr.bottom; left: parent.left; right: parent.right; margins: Theme.margin }
        spacing: 14
        RowLayout { spacing: 12; Layout.fillWidth: true
            VCard { Layout.fillWidth: true; accent: Theme.cyan; padding: 12
                ColumnLayout { width: parent.width; spacing: 2
                    Text { text: Lang.t("mobileState"); color: Theme.gray; font.pixelSize: Theme.fontSmall }
                    Row { spacing: 6; StatusDot { color: Theme.cyan; pulsing: true; anchors.verticalCenter: parent.verticalCenter }
                          Text { text: Lang.t("ready"); color: Theme.white; font.bold: true } } } }
            VCard { Layout.fillWidth: true; accent: Theme.blue; padding: 12
                ColumnLayout { width: parent.width; spacing: 2
                    Text { text: Lang.t("pcState"); color: Theme.gray; font.pixelSize: Theme.fontSmall }
                    Row { spacing: 6; StatusDot { color: Theme.gray; anchors.verticalCenter: parent.verticalCenter }
                          Text { text: Lang.t("waitingPc"); color: Theme.white; font.bold: true; font.pixelSize: Theme.fontSmall + 1 } } } }
        }
        VCard { Layout.fillWidth: true; accent: Theme.blue
            ColumnLayout { width: parent.width; spacing: 8
                Text { text: Lang.t("pending"); color: Theme.gray }
                Text { text: db.pendingCount; color: Theme.white; font.pixelSize: Theme.fontBig; font.bold: true }
                Text { text: Lang.t("lastSync") + ": " + (db.lastSync > 0 ? Qt.formatDateTime(new Date(db.lastSync), "dd/MM/yy hh:mm") : Lang.t("never")); color: Theme.gray; font.pixelSize: Theme.fontSmall }
                // barra de progreso
                Rectangle { Layout.fillWidth: true; height: 10; radius: 5; color: Theme.grayDark
                    Rectangle { width: parent.width * page.progress; height: parent.height; radius: 5
                        gradient: Gradient { orientation: Gradient.Horizontal; GradientStop { position: 0; color: Theme.blue } GradientStop { position: 1; color: Theme.cyan } } } }
                Text { text: Math.round(page.progress * 100) + " %"; color: Theme.cyan; font.pixelSize: Theme.fontSmall }
            }
        }
        VButton { text: Lang.t("syncNow"); iconName: "sync"; Layout.fillWidth: true; enabled: !page.busy
                  onClicked: { if (db.pendingCount === 0) { page.result = Lang.t("syncNothing"); page.progress = 0 } else run.restart() } }
        Text { text: page.result; color: Theme.cyan; font.bold: true; visible: text !== ""; Layout.alignment: Qt.AlignHCenter }
        Text { text: page.path !== "" && !page.busy ? Lang.t("file") + ":\n" + page.path : ""; color: Theme.gray; font.pixelSize: 11; wrapMode: Text.WrapAnywhere; Layout.fillWidth: true; visible: text !== "" }
    }
}
