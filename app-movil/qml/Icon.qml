// Icon.qml - Dibuja un icono (de la carpeta assets/icons) y lo tiñe del color que pidas.
// USO:  Icon { name: "heart"; color: Theme.cyan; size: 28 }
import QtQuick
import QtQuick.Effects

Item {
    property string name: "heart"
    property color color: Theme.cyan
    property int size: 24
    width: size; height: size

    Image {
        id: img
        anchors.fill: parent
        source: name !== "" ? "../assets/icons/" + name + ".svg" : ""
        sourceSize: Qt.size(size * 2, size * 2)   // se carga a doble tamaño para que se vea nítido
        visible: false
    }
    MultiEffect {                                  // el "tinte": convierte el icono blanco en el color elegido
        anchors.fill: img
        source: img
        colorization: 1.0
        colorizationColor: parent.color
    }
}
