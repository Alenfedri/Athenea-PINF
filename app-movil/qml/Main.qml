// =============================================================================
//  Main.qml  -  La ventana principal. Contiene la "pila" de pantallas.
//
//  CÓMO FUNCIONA LA NAVEGACIÓN (idea de la pila de platos):
//    - Cada pantalla es un plato. "push" pone un plato encima, "pop" lo quita.
//    - La app arranca con LoginPage. Tras iniciar sesión se cambia a Shell
//      (la pantalla con barra de pestañas) y, si procede, se abre Conexión.
// =============================================================================
import QtQuick
import QtQuick.Controls

ApplicationWindow {
    id: win
    width: 390; height: 800          // tamaño de móvil para probar en el ordenador
    visible: true
    title: "VitaBand"
    color: Theme.bg

    StackView {
        id: stack
        anchors.fill: parent
        initialItem: loginPage

        // Animaciones de transición entre pantallas: deslizar + fundido.
        pushEnter: Transition { ParallelAnimation {
            NumberAnimation { property: "x"; from: stack.width * 0.25; to: 0; duration: 300; easing.type: Easing.OutCubic }
            NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 300 } } }
        pushExit: Transition { NumberAnimation { property: "opacity"; to: 0.3; duration: 250 } }
        popEnter: Transition { NumberAnimation { property: "opacity"; to: 1; duration: 250 } }
        popExit: Transition { ParallelAnimation {
            NumberAnimation { property: "x"; to: stack.width * 0.25; duration: 280; easing.type: Easing.InCubic }
            NumberAnimation { property: "opacity"; to: 0; duration: 280 } } }
        replaceEnter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 400 } }
        replaceExit: Transition { NumberAnimation { property: "opacity"; to: 0; duration: 250 } }
    }

    // El "catálogo" de pantallas. Cada Component es una pantalla que aún no se ha creado.
    Component { id: loginPage;      LoginPage {} }
    Component { id: registerPage;   RegisterPage {} }
    Component { id: shellPage;      Shell {} }
    Component { id: connectionPage; ConnectionPage {} }
    Component { id: syncPage;       SyncPage {} }
    Component { id: statsPage;      StatsPage {} }
    Component { id: settingsPage;   SettingsPage {} }
    Component { id: templatePage;   TemplatePage {} }

    Toast { id: toast }

    Component.onCompleted: {
        // Le damos al "conductor" (Nav) el mapa de nombres -> pantallas.
        Nav.stack = stack
        Nav.toastItem = toast
        Nav.pages = { login: loginPage, register: registerPage, shell: shellPage, connection: connectionPage,
                      sync: syncPage, stats: statsPage, settings: settingsPage, template: templatePage }
    }

    // Si la banda se desconecta sola, avisamos al usuario (RF-06).
    Connections {
        target: ble
        function onUnexpectedDisconnect() { Nav.toast(Lang.t("lostConn")) }
    }
}
