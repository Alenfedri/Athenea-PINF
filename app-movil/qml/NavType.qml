// =============================================================================
//  [Se publica como "Nav" desde main.cpp]
//  Nav.qml  -  "El conductor": sabe cómo ir de una pantalla a otra
//  Cualquier pantalla puede escribir  Nav.push("settings")  y aparece Ajustes.
//  El mapa de nombres -> pantallas se rellena en Main.qml.
// =============================================================================
import QtQuick
import QtCore

QtObject {
    property var stack: null        // la "pila" de pantallas (Main.qml la rellena)
    property var pages: ({})        // diccionario  nombre -> pantalla
    property var toastItem: null    // el mensajito flotante

    // Preferencia guardada: "no mostrar el diálogo de conexión al abrir"
    property Settings prefs: Settings { property bool skipConnect: false }

    function push(name)  { stack.push(pages[name]) }           // abre encima de la actual
    function pop()       { if (stack.depth > 1) stack.pop() }  // vuelve atrás
    function goRoot(name){ stack.replace(null, pages[name]) }  // borra todo y abre esta
    // Entrar a la app tras iniciar sesión / registrarse. Si la banda no está
    // conectada y el usuario no marcó "no mostrar", se abre la pantalla de conexión.
    function enterApp(bandConnected) {
        goRoot("shell")
        if (!prefs.skipConnect && !bandConnected) Qt.callLater(push, "connection")
    }
    function toast(msg)  { if (toastItem) toastItem.show(msg) }
}
