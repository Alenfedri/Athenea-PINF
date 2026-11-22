// EcgChart.qml - Monitor de ECG en directo, estilo hospital: la línea se dibuja de izquierda
// a derecha y, al llegar al final, vuelve al principio borrando lo antiguo.
// Se alimenta con la señal "ecgSample" del Bluetooth (unas 100 muestras por segundo).
import QtQuick

Canvas {
    id: c
    property bool active: false          // ¿llega señal?
    property int size: 400               // muestras en pantalla (~4 s)
    property var buf: []
    property int pos: 0

    Component.onCompleted: { buf = new Array(size); for (var i = 0; i < size; i++) buf[i] = null }

    Connections {
        target: ble
        function onEcgSample(v) {
            c.buf[c.pos] = v
            c.pos = (c.pos + 1) % c.size      // avanza el "cursor" y vuelve al inicio al llegar al final
        }
    }
    Timer { interval: 33; running: c.visible; repeat: true; onTriggered: c.requestPaint() }   // ~30 fotogramas/s

    onPaint: {
        var ctx = getContext("2d"); ctx.reset()
        var w = width, h = height
        // cuadrícula tipo papel de ECG
        ctx.strokeStyle = "#14264A"; ctx.lineWidth = 1
        for (var x = 0; x < w; x += 24) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke() }
        for (var y = 0; y < h; y += 24) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke() }
        // rango de la señal
        var mn = 1e9, mx = -1e9
        for (var i = 0; i < size; i++) if (buf[i] !== null) { mn = Math.min(mn, buf[i]); mx = Math.max(mx, buf[i]) }
        if (mn > mx) return
        if (mx - mn < 50) { mx += 25; mn -= 25 }
        var pad = (mx - mn) * 0.15; mn -= pad; mx += pad
        function X(i) { return i / (size - 1) * w }
        function Y(v) { return h - (v - mn) / (mx - mn) * h }
        // línea con brillo
        ctx.lineJoin = "round"; ctx.lineCap = "round"
        for (var pass = 0; pass < 2; pass++) {
            ctx.strokeStyle = pass === 0 ? "rgba(34,211,238,0.25)" : "#22D3EE"
            ctx.lineWidth = pass === 0 ? 7 : 2.2
            ctx.beginPath(); var started = false
            for (var k = 0; k < size; k++) {
                if (buf[k] === null) continue
                var gapAhead = (k >= pos && k < pos + 12)        // hueco delante del "cursor" que barre
                if (gapAhead) { started = false; continue }
                if (!started) { ctx.moveTo(X(k), Y(buf[k])); started = true } else ctx.lineTo(X(k), Y(buf[k]))
            }
            ctx.stroke()
        }
        // cursor
        if (active) { ctx.fillStyle = "#F4F8FF"; ctx.beginPath(); ctx.arc(X(pos), Y(buf[(pos + size - 1) % size] || mn), 4, 0, 6.3); ctx.fill() }
    }
}
