cmake_minimum_required(VERSION 3.16)
project(VitaBandApp VERSION 0.1 LANGUAGES CXX)
set(CMAKE_CXX_STANDARD_REQUIRED ON)


# --- AÑADIR ESTAS TRES LÍNEAS PARA COMPILAR LOS METADATOS DE QT ---
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)
set(CMAKE_AUTOUIC ON)

find_package(Qt6 6.4 REQUIRED COMPONENTS Quick Bluetooth)
find_package(Qt6 6.4 REQUIRED COMPONENTS Quick Bluetooth)
qt_add_executable(appVitaBandApp
    main.cpp
    BleController.cpp
    BleController.h
)
qt_add_qml_module(appVitaBandApp
    URI VitaBand
    VERSION 1.0
    QML_FILES
        Main.qml
        Login.qml
        Dashboard.qml
        Activity.qml
)
target_link_libraries(appVitaBandApp PRIVATE Qt6::Quick Qt6::Bluetooth)
