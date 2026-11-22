// SettingsPage.qml - Wireframes 9 y 9.1: idioma, gestión de datos y eliminación de cuenta.
// Todas las operaciones de borrado piden CONFIRMACIÓN antes de ejecutarse.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: page
    property string pending: ""          // qué se va a borrar: "meas" | "all" | "account"

    GradientBg { anchors.fill: parent }
    PageHeader { id: hdr; title: Lang.t("settings"); anchors { top: parent.top; left: parent.left; right: parent.right } }

    Flickable {
        anchors { top: hdr.bottom; left: parent.left; right: parent.right; bottom: parent.bottom }
        contentHeight: col.height + 30; clip: true
        ColumnLayout {
            id: col; x: Theme.margin; width: parent.width - 2 * Theme.margin; spacing: 12

            // ----- Idioma: selector con "píldora" deslizante -----
            Text { text: Lang.t("language"); color: Theme.gray }
            Rectangle { Layout.fillWidth: true; height: 52; radius: 26; color: Theme.surface; border.color: Theme.grayDark
                Rectangle { width: parent.width / 2 - 6; height: 44; radius: 22; y: 4
                    x: (Lang.code === "es" ? 0 : parent.width / 2) + 3
                    Behavior on x { NumberAnimation { duration: 260; easing.type: Easing.OutBack } }
                    gradient: Gradient { orientation: Gradient.Horizontal; GradientStop { position: 0; color: Theme.blue } GradientStop { position: 1; color: Theme.cyan } } }
                Row { anchors.fill: parent
                    Repeater { model: [ { c: "es", k: "spanish" }, { c: "en", k: "english" } ]
                        delegate: Item { width: parent.width / 2; height: parent.height
                            Text { anchors.centerIn: parent; text: Lang.t(modelData.k); font.bold: true; color: Lang.code === modelData.c ? Theme.black : Theme.white }
                            MouseArea { anchors.fill: parent; onClicked: Lang.setLanguage(modelData.c) } } } }
            }

            // ----- Gestión de datos (solo con sesión iniciada) -----
            Collapsible { visible: db.loggedIn; Layout.fillWidth: true; title: Lang.t("dataMgmt")
                VButton { width: parent.width; text: Lang.t("delMeas"); iconName: "trash"; primary: false; onClicked: { page.pending = "meas"; confirm.open() } }
                VButton { width: parent.width; text: Lang.t("delAll"); iconName: "trash"; primary: false; onClicked: { page.pending = "all"; confirm.open() } }
                VButton { width: parent.width; text: Lang.t("delAccount"); iconName: "warning"; primary: false; tint: "#FF7B8A"; onClicked: { page.pending = "account"; confirm.open() } }
            }
            Collapsible { Layout.fillWidth: true; title: Lang.t("about")
                Text { width: parent.width; text: "VitaBand Software\n" + Lang.t("version") + " 1.0\nAthenea"; color: Theme.gray; wrapMode: Text.Wrap }
            }
        }
    }

    // ----- Ventana de confirmación (wireframe 9.1 / 17) -----
    Popup {
        id: confirm
        modal: true; anchors.centerIn: parent; width: parent.width - 48; padding: 20
        enter: Transition { ParallelAnimation {
            NumberAnimation { property: "scale"; from: 0.85; to: 1; duration: 220; easing.type: Easing.OutBack }
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 180 } } }
        Overlay.modal: Rectangle { color: "#CC050A14" }
        background: Rectangle { radius: Theme.radius; color: Theme.surface; border.color: page.pending === "account" ? "#FF7B8A" : Theme.cyan }
        contentItem: ColumnLayout { spacing: 14
            Text { text: Lang.t("areYouSure"); color: Theme.white; font.bold: true; font.pixelSize: Theme.fontTitle - 2 }
            Text { Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.gray
                   text: page.pending === "meas" ? Lang.t("delMeasMsg") : page.pending === "all" ? Lang.t("delAllMsg") : Lang.t("delAccMsg") }
            RowLayout { spacing: 10
                VButton { text: Lang.t("cancel"); primary: false; Layout.fillWidth: true; onClicked: confirm.close() }
                VButton { text: Lang.t("confirm"); tint: "#FF7B8A"; Layout.fillWidth: true
                    onClicked: {
                        confirm.close()
                        if (page.pending === "meas") db.deleteMeasurements()
                        else if (page.pending === "all") db.deleteEverything()
                        else if (page.pending === "account") { db.deleteAccount(); Nav.goRoot("login"); return }
                        Nav.toast(Lang.t("done"))
                    } }
            }
        }
    }
}
