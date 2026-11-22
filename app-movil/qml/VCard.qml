// VCard.qml - Una "tarjeta" con borde brillante que aparece con una animación suave
// (sube y se hace visible). Todo lo que pongas dentro queda dentro de la tarjeta.
// USO:  VCard { accent: Theme.cyan; delay: 100;  Text { text: "hola" } }
import QtQuick

Rectangle {
    id: card
    property color accent: Theme.cyan     // color del borde/brillo
    property int delay: 0                 // milisegundos de espera antes de aparecer (efecto escalonado)
    property bool clickable: false
    signal clicked()
    default property alias content: inner.data
    property int padding: 16

    property bool autoHeight: true        // true = la tarjeta crece según su contenido
    implicitHeight: autoHeight ? inner.childrenRect.height + padding * 2 : 100
    radius: Theme.radius
    color: Theme.surface
    border.width: 1
    border.color: Qt.rgba(accent.r, accent.g, accent.b, mouse.pressed ? 0.9 : 0.35)
    scale: mouse.pressed ? 0.98 : 1
    Behavior on scale { NumberAnimation { duration: 120 } }
    Behavior on border.color { ColorAnimation { duration: 150 } }

    // Degradado suave de fondo
    Rectangle {
        anchors.fill: parent; radius: parent.radius
        gradient: Gradient {
            GradientStop { position: 0; color: Qt.rgba(card.accent.r, card.accent.g, card.accent.b, 0.12) }
            GradientStop { position: 1; color: "transparent" }
        }
    }
    Item { id: inner; x: card.padding; y: card.padding; width: card.width - card.padding * 2; height: card.autoHeight ? childrenRect.height : card.height - card.padding * 2 }
    MouseArea { id: mouse; anchors.fill: parent; enabled: card.clickable; onClicked: card.clicked() }

    // Animación de entrada
    opacity: 0
    transform: Translate { id: shift; y: 24 }
    Component.onCompleted: enter.start()
    SequentialAnimation {
        id: enter
        PauseAnimation { duration: card.delay }
        ParallelAnimation {
            NumberAnimation { target: card; property: "opacity"; to: 1; duration: 450; easing.type: Easing.OutCubic }
            NumberAnimation { target: shift; property: "y"; to: 0; duration: 450; easing.type: Easing.OutCubic }
        }
    }
}
