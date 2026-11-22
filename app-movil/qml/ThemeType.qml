// =============================================================================
//  [Se publica como "Theme" desde main.cpp]
//  Theme.qml  -  "La paleta de colores y medidas" (singleton: único y global)
//  Cambia un color AQUÍ y cambia en TODA la app. Paleta: azul, cian, gris,
//  negro y blanco.
// =============================================================================
import QtQuick

QtObject {
    // --- Negro / fondos ---
    readonly property color black:    "#050A14"
    readonly property color bg:       "#07101F"
    readonly property color surface:  "#0E1B30"
    readonly property color surface2: "#14264A"
    // --- Azules ---
    readonly property color navy:     "#0B3D91"
    readonly property color blue:     "#2F7BFF"
    // --- Cian ---
    readonly property color cyan:     "#22D3EE"
    // --- Grises ---
    readonly property color gray:     "#8A97AD"
    readonly property color grayDark: "#2A3850"
    // --- Blanco ---
    readonly property color white:    "#F4F8FF"

    // Colores por tipo de dato (el wireframe pide la respiración en azul):
    readonly property color heart: cyan        // corazón -> cian
    readonly property color resp:  blue        // respiración -> azul
    readonly property color temp:  "#BFD3F2"   // temperatura -> blanco azulado
    readonly property color act:   "#7FA8FF"   // actividad -> azul claro

    // Medidas comunes
    readonly property int radius: 20
    readonly property int margin: 18
    readonly property int fontSmall: 12
    readonly property int fontBody: 15
    readonly property int fontTitle: 22
    readonly property int fontBig: 40
}
