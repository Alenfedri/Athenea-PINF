import QtQuick
import QtQuick.Controls

ApplicationWindow {
    id: window
    width: 360
    height: 640
    visible: true
    title: "VitaBand"

    StackView {
        id: stackView
        anchors.fill: parent
        initialItem: "Login.qml"
    }
}
