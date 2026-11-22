// MorePage.qml - Pestaña "Más": menú que lleva a las pantallas secundarias.
//   Conexión · Sincronización · Estadísticas · Ajustes · Plantilla · Cerrar sesión
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    // Cada opción: icono, texto, nombre de pantalla destino (el que registra Main.qml en Nav.pages)
    readonly property var items: [
        { icon: "bluetooth", key: "connection", page: "connection" },
        { icon: "sync",      key: "sync",       page: "sync" },
        { icon: "chart",     key: "stats",      page: "stats" },
        { icon: "settings",  key: "settings",   page: "settings" },
        { icon: "plus",      key: "template",   page: "template" }
    ]
    Flickable {
        anchors.fill: parent; contentHeight: col.height + 30; clip: true
        ColumnLayout {
            id: col; x: Theme.margin; width: parent.width - 2 * Theme.margin; spacing: 10
            Text { text: Lang.t("more"); color: Theme.white; font.pixelSize: Theme.fontTitle; font.bold: true }
            Repeater {
                model: items
                delegate: VCard {
                    Layout.fillWidth: true; delay: index * 70; clickable: true; padding: 14
                    onClicked: Nav.push(modelData.page)
                    RowLayout { width: parent.width; spacing: 14
                        Icon { name: modelData.icon; color: Theme.cyan; size: 26 }
                        Text { text: Lang.t(modelData.key); color: Theme.white; font.pixelSize: Theme.fontBody; Layout.fillWidth: true }
                        // Globo con los registros pendientes, solo en "Sincronización"
                        Rectangle { visible: modelData.page === "sync" && db.pendingCount > 0; radius: 11; height: 22; width: Math.max(22, bt.implicitWidth + 12); color: Theme.blue
                            Text { id: bt; anchors.centerIn: parent; text: db.pendingCount; color: Theme.white; font.pixelSize: 11; font.bold: true } }
                        Icon { name: "back"; rotation: 180; color: Theme.gray; size: 18 }
                    }
                }
            }
            VButton { text: Lang.t("logout"); iconName: "logout"; primary: false; tint: "#FF7B8A"; Layout.fillWidth: true; Layout.topMargin: 10
                      onClicked: { db.logout(); Nav.goRoot("login") } }
        }
    }
}
