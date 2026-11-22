// VCombo.qml - Desplegable (lista de opciones) con estilo VitaBand.
// USO:  VCombo { model: ["Uno","Dos"]; onActivated: console.log(currentIndex) }
import QtQuick
import QtQuick.Controls

ComboBox {
    id: c
    implicitHeight: 48
    font.pixelSize: Theme.fontBody

    background: Rectangle {
        radius: 14; color: Theme.surface
        border.width: c.popup.visible ? 2 : 1
        border.color: c.popup.visible ? Theme.cyan : Theme.grayDark
    }
    contentItem: Text {
        leftPadding: 14
        text: c.displayText; color: Theme.white; font: c.font
        verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
    }
    indicator: Icon {
        x: c.width - width - 12; y: (c.height - height) / 2
        name: "chevron"; size: 20; color: Theme.cyan
        rotation: c.popup.visible ? 180 : 0                 // la flecha gira al abrir
        Behavior on rotation { NumberAnimation { duration: 200 } }
    }
    delegate: ItemDelegate {                                 // cada fila de la lista
        width: c.width; height: 44
        contentItem: Text { text: modelData !== undefined ? modelData : model[c.textRole]; color: highlighted ? Theme.cyan : Theme.white; font: c.font; verticalAlignment: Text.AlignVCenter }
        background: Rectangle { color: parent.down ? Theme.surface2 : "transparent" }
        highlighted: c.highlightedIndex === index
    }
    popup: Popup {
        y: c.height + 4; width: c.width; padding: 4
        implicitHeight: Math.min(contentItem.implicitHeight + 8, 260)
        enter: Transition { NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 150 } }
        contentItem: ListView { clip: true; implicitHeight: contentHeight; model: c.popup.visible ? c.delegateModel : null; currentIndex: c.highlightedIndex }
        background: Rectangle { radius: 14; color: Theme.surface2; border.color: Theme.cyan; border.width: 1 }
    }
}
