// RegisterPage.qml - Pantalla 2.2: crear cuenta. Si todo va bien, entra directamente a la app.
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    GradientBg { anchors.fill: parent }
    PageHeader { id: hdr; title: Lang.t("createAccount"); anchors { top: parent.top; left: parent.left; right: parent.right } }

    Flickable {
        anchors { top: hdr.bottom; left: parent.left; right: parent.right; bottom: parent.bottom }
        contentHeight: col.height + 40; clip: true
        ColumnLayout {
            id: col
            x: 24; width: parent.width - 48; spacing: 12
            VField { id: fName; icon: "user"; placeholderText: Lang.t("name"); Layout.fillWidth: true }
            VField { id: fSur; icon: "user"; placeholderText: Lang.t("surname"); Layout.fillWidth: true }
            VField { id: fUser; icon: "user"; placeholderText: Lang.t("username"); Layout.fillWidth: true }
            VField { id: fMail; icon: "mail"; placeholderText: Lang.t("email"); Layout.fillWidth: true; inputMethodHints: Qt.ImhEmailCharactersOnly }
            VField { id: fPass; icon: "lock"; secret: true; placeholderText: Lang.t("password"); Layout.fillWidth: true }
            VField { id: fConf; icon: "lock"; secret: true; placeholderText: Lang.t("confirmPassword"); Layout.fillWidth: true }
            Text { id: err; color: "#FF7B8A"; font.pixelSize: Theme.fontSmall + 1; visible: text !== ""; wrapMode: Text.Wrap; Layout.fillWidth: true }
            VButton {
                text: Lang.t("createAccount"); iconName: "plus"; Layout.fillWidth: true
                onClicked: {
                    var e = db.registerUser(fName.text, fSur.text, fUser.text, fMail.text, fPass.text, fConf.text)
                    if (e === "") Nav.enterApp(ble.state === "connected")
                    else err.text = Lang.t("e_" + e)
                }
            }
        }
    }
}
