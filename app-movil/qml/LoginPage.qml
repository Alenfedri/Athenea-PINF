// LoginPage.qml - Pantalla 2.1 del wireframe: inicio de sesión.
// Va a: RegisterPage (botón Registrarse), SettingsPage (engranaje) y Shell (si el login es correcto).
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: page
    GradientBg { anchors.fill: parent }

    // Botón de ajustes arriba a la derecha (para cambiar el idioma antes de entrar)
    Item {
        anchors { top: parent.top; right: parent.right; margins: 14 }
        width: 48; height: 48
        Icon { anchors.centerIn: parent; name: "settings"; size: 26; color: Theme.gray }
        MouseArea { anchors.fill: parent; onClicked: Nav.push("settings") }
    }

    ColumnLayout {
        anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 28 }
        spacing: 14

        Image {                                        // logo que "flota" arriba y abajo
            id: logo
            source: "../assets/img/logo.svg"
            Layout.alignment: Qt.AlignHCenter
            Layout.preferredWidth: 110; Layout.preferredHeight: 110
            SequentialAnimation on y { loops: Animation.Infinite
                NumberAnimation { to: -6; duration: 1600; easing.type: Easing.InOutSine }
                NumberAnimation { to: 6;  duration: 1600; easing.type: Easing.InOutSine } }
        }
        Text { text: Lang.t("appName"); color: Theme.white; font.pixelSize: 28; font.bold: true; Layout.alignment: Qt.AlignHCenter }
        Text { text: Lang.t("tagline"); color: Theme.cyan; font.pixelSize: Theme.fontBody; Layout.alignment: Qt.AlignHCenter; Layout.bottomMargin: 18 }

        VField { id: user; icon: "user"; placeholderText: Lang.t("user"); Layout.fillWidth: true }
        VField { id: pass; icon: "lock"; secret: true; placeholderText: Lang.t("password"); Layout.fillWidth: true; onAccepted: doLogin() }

        Text {                                          // mensaje de error con temblor
            id: err; text: ""; color: "#FF7B8A"; font.pixelSize: Theme.fontSmall + 1
            Layout.alignment: Qt.AlignHCenter; visible: text !== ""
            transform: Translate { id: shake }
            SequentialAnimation { id: shakeAnim
                NumberAnimation { target: shake; property: "x"; to: -8; duration: 50 }
                NumberAnimation { target: shake; property: "x"; to: 8;  duration: 80 }
                NumberAnimation { target: shake; property: "x"; to: 0;  duration: 50 } }
        }

        VButton { text: Lang.t("login"); iconName: "check"; Layout.fillWidth: true; onClicked: doLogin() }
        VButton { text: Lang.t("register"); primary: false; Layout.fillWidth: true; onClicked: Nav.push("register") }
    }

    function doLogin() {
        if (db.login(user.text, pass.text)) {
            err.text = ""
            Nav.enterApp(ble.state === "connected")
        } else { err.text = Lang.t("badLogin"); shakeAnim.restart() }
    }
}
