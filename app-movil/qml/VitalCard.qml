// VitalCard.qml - Tarjeta de un dato vital (pulso, respiración, temperatura, actividad):
// icono + nombre + número grande (que "rueda" al cambiar) + mini gráfica de los últimos segundos.
import QtQuick
import QtQuick.Layouts

VCard {
    id: v
    property string label: ""
    property string unit: ""
    property string icon: "heart"
    property real value: 0
    property int decimals: 0
    property string textValue: ""         // si se rellena, se muestra este texto en vez del número (p. ej. "Reposo")
    property var history: []
    property bool pulse: false            // el icono "late" al ritmo del pulso
    autoHeight: false

    property real shown: value
    Behavior on shown { NumberAnimation { duration: 450; easing.type: Easing.OutCubic } }  // el número rueda suavemente

    RowLayout {
        id: head
        width: parent.width; spacing: 8
        Icon {
            id: ic; name: v.icon; size: 22; color: v.accent
            SequentialAnimation on scale {                // latido
                running: v.pulse && v.value > 0; loops: Animation.Infinite
                NumberAnimation { to: 1.35; duration: Math.max(120, 60000 / Math.max(v.value, 40) * 0.25); easing.type: Easing.OutQuad }
                NumberAnimation { to: 1.0;  duration: Math.max(180, 60000 / Math.max(v.value, 40) * 0.75); easing.type: Easing.InOutQuad }
            }
        }
        Text { text: v.label; color: Theme.gray; font.pixelSize: Theme.fontSmall; Layout.fillWidth: true; elide: Text.ElideRight }
    }
    Row {
        anchors.top: head.bottom; anchors.topMargin: 6; spacing: 4
        Text {
            text: v.textValue !== "" ? v.textValue : (v.value > 0 ? v.shown.toFixed(v.decimals) : "--")
            color: Theme.white; font.pixelSize: v.textValue !== "" ? 26 : 38; font.bold: true
        }
        Text { text: v.unit; color: v.accent; font.pixelSize: Theme.fontBody; y: 16 }
    }
    LineChart {
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
        height: 44; compact: true; lineColor: v.accent; points: v.history
        reveal: 1                                  // en tiempo real no se re-anima cada segundo
    }
}
