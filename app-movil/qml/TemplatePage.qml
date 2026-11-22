// =============================================================================
//  TemplatePage.qml  -  PANTALLA PLANTILLA
//  ---------------------------------------------------------------------------
//  Cómo crear una pantalla nueva en 4 pasos (no hace falta saber programar):
//   1. Copia este archivo y ponle otro nombre, p. ej. "MiPantalla.qml".
//   2. Cambia el título y borra lo que no necesites (cada bloque está marcado).
//   3. En CMakeLists.txt, añade "qml/MiPantalla.qml" a la lista QML_FILES.
//   4. En Main.qml añade:  Component { id: miPantalla; MiPantalla {} }
//      y en Nav.pages:     miPantalla: miPantalla
//      Para abrirla desde cualquier sitio:   Nav.push("miPantalla")
// =============================================================================
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: page
    property int tab: 0

    GradientBg { anchors.fill: parent }                                   // [FONDO] déjalo igual en todas las pantallas
    PageHeader { id: hdr; title: Lang.t("template"); anchors { top: parent.top; left: parent.left; right: parent.right } }   // [CABECERA] flecha atrás + título

    Flickable {                                                           // [ZONA CON SCROLL]
        anchors { top: hdr.bottom; left: parent.left; right: parent.right; bottom: parent.bottom }
        contentHeight: col.height + 30; clip: true
        ColumnLayout {
            id: col; x: Theme.margin; width: parent.width - 2 * Theme.margin; spacing: 14

            // [PESTAÑAS] segmentadas, con indicador deslizante
            Rectangle { Layout.fillWidth: true; height: 46; radius: 23; color: Theme.surface; border.color: Theme.grayDark
                Rectangle { width: parent.width / 3 - 6; height: 38; radius: 19; y: 4; x: page.tab * parent.width / 3 + 3; color: Theme.blue
                            Behavior on x { NumberAnimation { duration: 250; easing.type: Easing.OutBack } } }
                Row { anchors.fill: parent
                    Repeater { model: ["A", "B", "C"]
                        delegate: Item { width: parent.width / 3; height: parent.height
                            Text { anchors.centerIn: parent; text: Lang.t("tplTabs") + " " + modelData; color: Theme.white; font.pixelSize: Theme.fontSmall + 1 }
                            MouseArea { anchors.fill: parent; onClicked: page.tab = index } } } } }

            // [TARJETA] con animación de entrada; "clickable" la hace pulsable
            VCard { Layout.fillWidth: true; accent: Theme.cyan; clickable: true; onClicked: Nav.toast(Lang.t("tplHello"))
                RowLayout { width: parent.width; spacing: 12
                    Icon { name: "heart"; size: 30; color: Theme.cyan }
                    ColumnLayout { Layout.fillWidth: true; spacing: 2
                        Text { text: Lang.t("tplCard") + " (" + (page.tab + 1) + ")"; color: Theme.white; font.bold: true }
                        Text { text: Lang.t("tplHello"); color: Theme.gray; font.pixelSize: Theme.fontSmall } } } }

            // [DESPLEGABLE] pulsa el título para abrir/cerrar. Puedes meter cualquier cosa dentro.
            Collapsible { Layout.fillWidth: true; title: Lang.t("tplSection"); expanded: true
                Text { text: Lang.t("tplChoose"); color: Theme.gray; font.pixelSize: Theme.fontSmall }
                VCombo { width: parent.width; model: [Lang.t("walk"), Lang.t("run"), Lang.t("cycling")] }       // [LISTA DESPLEGABLE]
                RowLayout { width: parent.width
                    Text { text: Lang.t("tplSwitch"); color: Theme.white; Layout.fillWidth: true }
                    Switch {} }                                                                                    // [INTERRUPTOR]
                CheckBox { text: Lang.t("tplCheck"); contentItem: Text { text: parent.text; color: Theme.white; leftPadding: 34; verticalAlignment: Text.AlignVCenter } }  // [CASILLA]
                Text { text: Lang.t("tplSlider"); color: Theme.gray; font.pixelSize: Theme.fontSmall }
                Slider { width: parent.width; from: 0; to: 100; value: 40 }                                        // [DESLIZADOR]
            }
            Collapsible { Layout.fillWidth: true; title: Lang.t("tplOptions")
                VField { width: parent.width; icon: "user"; placeholderText: Lang.t("name") }                      // [CAMPO DE TEXTO]
                VField { width: parent.width; icon: "lock"; secret: true; placeholderText: Lang.t("password") }
            }

            // [BOTONES]
            VButton { text: Lang.t("tplPrimary"); iconName: "check"; Layout.fillWidth: true; onClicked: Nav.toast(Lang.t("done")) }
            VButton { text: Lang.t("tplSecondary"); primary: false; Layout.fillWidth: true; onClicked: popup.open() }

            // [GRÁFICA de ejemplo]
            VCard { Layout.fillWidth: true; autoHeight: false; Layout.preferredHeight: 170; padding: 8
                LineChart { anchors.fill: parent; animateOnChange: true; lineColor: Theme.blue
                    points: [ {t:0,v:5},{t:1,v:9},{t:2,v:6},{t:3,v:12},{t:4,v:8},{t:5,v:14} ] } }
        }
    }

    // [VENTANA EMERGENTE]
    Popup { id: popup; modal: true; anchors.centerIn: parent; width: parent.width - 60; padding: 20
        enter: Transition { NumberAnimation { property: "scale"; from: 0.8; to: 1; duration: 220; easing.type: Easing.OutBack } }
        Overlay.modal: Rectangle { color: "#CC050A14" }
        background: Rectangle { radius: Theme.radius; color: Theme.surface; border.color: Theme.cyan }
        contentItem: ColumnLayout { spacing: 12
            Text { text: Lang.t("tplHello"); color: Theme.white; font.bold: true; font.pixelSize: Theme.fontTitle - 4 }
            VButton { text: Lang.t("close"); Layout.fillWidth: true; onClicked: popup.close() } } }
}
