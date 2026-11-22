// StatusDot.qml - Puntito de estado. Si "pulsing" es true, emite un aro que se expande (como un radar).
import QtQuick

Item {
    property color color: Theme.gray
    property bool pulsing: false
    width: 14; height: 14
    Rectangle {
        id: ring; anchors.centerIn: parent; width: 14; height: 14; radius: 7
        color: "transparent"; border.color: parent.color; border.width: 2; opacity: 0; visible: pulsing
        ParallelAnimation { running: pulsing; loops: Animation.Infinite
            NumberAnimation { target: ring; property: "scale"; from: 1; to: 2.6; duration: 1200 }
            NumberAnimation { target: ring; property: "opacity"; from: 0.9; to: 0; duration: 1200 } }
    }
    Rectangle { anchors.centerIn: parent; width: 12; height: 12; radius: 6; color: parent.color }
}
