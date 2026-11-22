# =============================================================================
#  CMakeLists.txt - "La receta de compilación"
#  Le dice a Qt qué archivos forman la app. Si añades una pantalla nueva
#  (un .qml), añádela a la lista QML_FILES de abajo.
#  Requiere Qt 6.5 o superior (con los módulos Quick, Bluetooth, Sql y Svg).
# =============================================================================
cmake_minimum_required(VERSION 3.21)
project(VitaBand VERSION 1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(Qt6 6.5 REQUIRED COMPONENTS Core Gui Quick QuickControls2 Bluetooth Sql Svg)
qt_standard_project_setup(REQUIRES 6.5)

qt_add_executable(appVitaBand
    src/main.cpp
    src/BleManager.h        src/BleManager.cpp
    src/DatabaseManager.h   src/DatabaseManager.cpp
)

qt_add_qml_module(appVitaBand
    URI VitaBand
    VERSION 1.0
    QML_FILES
        qml/Main.qml qml/ThemeType.qml qml/LangType.qml qml/NavType.qml
        qml/Shell.qml qml/LoginPage.qml qml/RegisterPage.qml
        qml/MonitorPage.qml qml/EcgPage.qml qml/HistoryPage.qml qml/ActivityPage.qml qml/MorePage.qml
        qml/ConnectionPage.qml qml/SyncPage.qml qml/StatsPage.qml qml/SettingsPage.qml qml/TemplatePage.qml
        qml/Icon.qml qml/VCard.qml qml/VitalCard.qml qml/VButton.qml qml/VField.qml qml/VCombo.qml
        qml/Collapsible.qml qml/PageHeader.qml qml/GradientBg.qml qml/StatusDot.qml qml/Toast.qml
        qml/LineChart.qml qml/EcgChart.qml
    RESOURCES
        assets/img/logo.svg assets/img/band.svg assets/img/waves.svg assets/img/empty.svg
        assets/icons/heart.svg assets/icons/lungs.svg assets/icons/thermo.svg assets/icons/bolt.svg
        assets/icons/ecg.svg assets/icons/bluetooth.svg assets/icons/history.svg assets/icons/timer.svg
        assets/icons/menu.svg assets/icons/chart.svg assets/icons/sync.svg assets/icons/settings.svg
        assets/icons/back.svg assets/icons/user.svg assets/icons/lock.svg assets/icons/trash.svg
        assets/icons/check.svg assets/icons/warning.svg assets/icons/home.svg assets/icons/plus.svg
        assets/icons/chevron.svg assets/icons/mail.svg assets/icons/play.svg assets/icons/stop.svg
        assets/icons/logout.svg
)

target_link_libraries(appVitaBand PRIVATE
    Qt6::Core Qt6::Gui Qt6::Quick Qt6::QuickControls2 Qt6::Bluetooth Qt6::Sql Qt6::Svg)

# Android: permisos de Bluetooth. En el AndroidManifest.xml (Qt Creator lo genera) añade:
#   <uses-permission android:name="android.permission.BLUETOOTH_SCAN" android:usesPermissionFlags="neverForLocation"/>
#   <uses-permission android:name="android.permission.BLUETOOTH_CONNECT"/>
#   <uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" android:maxSdkVersion="30"/>
# iOS: en Info.plist añade NSBluetoothAlwaysUsageDescription con un texto explicativo.
