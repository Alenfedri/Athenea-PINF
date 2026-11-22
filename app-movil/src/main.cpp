// =============================================================================
//  main.cpp  -  "El interruptor general" de la aplicación
// -----------------------------------------------------------------------------
//  Aquí se enciende todo: se crean los dos "motores" (Bluetooth y base de
//  datos), se conectan entre sí y se le entregan a las pantallas (QML).
// =============================================================================
#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQuickStyle>
#include <QQmlComponent>
#include <QDebug>
#include "BleManager.h"
#include "DatabaseManager.h"

int main(int argc, char *argv[])
{
    QGuiApplication app(argc, argv);
    app.setOrganizationName("Athenea");          // necesario para guardar preferencias (idioma, etc.)
    app.setApplicationName("VitaBand");
    QQuickStyle::setStyle("Basic");              // estilo neutro que permite pintar los controles a nuestro gusto

    BleManager ble;                              // motor 1: Bluetooth
    DatabaseManager db;                          // motor 2: base de datos
    if (!db.open()) return -1;

    // CABLEADO: cada segundo el Bluetooth envía una "foto" de los valores y la
    // base de datos la recibe para guardarla. (RF-12, RF-26, RF-37)
    QObject::connect(&ble, &BleManager::snapshot, &db, &DatabaseManager::onSnapshot);

    QQmlApplicationEngine engine;
    // Les ponemos nombre para que las pantallas los usen: "ble" y "db".
    engine.rootContext()->setContextProperty("ble", &ble);
    engine.rootContext()->setContextProperty("db", &db);

    // "Theme" (colores), "Lang" (idiomas) y "Nav" (navegación) se crean aquí una sola vez
    // y se ponen a disposición de todas las pantallas con ese mismo nombre.
    const QList<QPair<QString, QString>> shared = {{"Theme", "ThemeType"}, {"Lang", "LangType"}, {"Nav", "NavType"}};
    for (const auto &p : shared) {
        QQmlComponent comp(&engine, QUrl("qrc:/qt/qml/VitaBand/qml/" + p.second + ".qml"));
        QObject *obj = comp.create();
        if (!obj) { qWarning() << comp.errors(); return -1; }
        obj->setParent(&engine);
        engine.rootContext()->setContextProperty(p.first, obj);
    }

    QObject::connect(&engine, &QQmlApplicationEngine::objectCreationFailed, &app, []() { QCoreApplication::exit(-1); }, Qt::QueuedConnection);
    engine.loadFromModule("VitaBand", "Main");   // abre la pantalla Main.qml
    return app.exec();
}
