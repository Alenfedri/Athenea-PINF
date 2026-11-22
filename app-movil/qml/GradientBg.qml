// GradientBg.qml - Fondo de las pantallas: negro-azulado con ondas que se deslizan despacio
// y un "resplandor" que respira. Es solo decoración.
import QtQuick

Rectangle {
    id: bg
    color: Theme.bg
    clip: true
    Rectangle {                       // resplandor azul arriba
        width: bg.width * 1.4; height: width; radius: width / 2
        x: -bg.width * 0.2; y: -width * 0.72
        color: Theme.navy
        opacity: 0.35
        SequentialAnimation on opacity { loops: Animation.Infinite
            NumberAnimation { to: 0.55; duration: 3500; easing.type: Easing.InOutSine }
            NumberAnimation { to: 0.30; duration: 3500; easing.type: Easing.InOutSine } }
    }
    Image {                           // ondas decorativas (assets/img/waves.svg)
        id: waves
        source: "../assets/img/waves.svg"
        width: bg.width * 2; height: bg.height * 0.35
        y: bg.height * 0.62; opacity: 0.8
        fillMode: Image.Stretch
        NumberAnimation on x { from: 0; to: -bg.width; duration: 16000; loops: Animation.Infinite }
    }
}
