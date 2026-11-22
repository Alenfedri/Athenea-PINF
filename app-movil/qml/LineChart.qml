// LineChart.qml - Gráfica de líneas dibujada "a mano" con un Canvas (un lienzo).
// Recibe una lista de puntos [{t: milisegundos, v: valor}]. Un valor vacío (null) significa
// "no hubo medición": la línea se corta en vez de inventarse datos (RF-27).
// La línea se "dibuja" de izquierda a derecha al aparecer (animación).
import QtQuick

Canvas {
    id: c
    property var points: []
    property color lineColor: Theme.cyan
    property bool compact: false          // true = versión mini sin ejes (para las tarjetas)
    property string unit: ""
    property real reveal: 1               // 0..1 : cuánto de la línea se ve

    property bool animateOnChange: false  // true = la línea se redibuja con animación cada vez que cambian los datos
    onPointsChanged: { requestPaint(); if (animateOnChange) anim.restart() }
    onLineColorChanged: requestPaint()
    onRevealChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    function replay() { anim.restart() }
    NumberAnimation on reveal { id: anim; from: 0; to: 1; duration: 800; easing.type: Easing.OutCubic }

    onPaint: {
        var ctx = getContext("2d")
        ctx.reset()
        var n = points ? points.length : 0
        var L = compact ? 2 : 38, R = 6, T = 8, B = compact ? 2 : 22
        var w = width - L - R, h = height - T - B
        if (n < 2 || w <= 0 || h <= 0) {
            ctx.fillStyle = "#8A97AD"; ctx.font = "13px sans-serif"
            if (!compact) ctx.fillText("—", width / 2, height / 2)
            return
        }
        var lo = 1e9, hi = -1e9
        for (var i = 0; i < n; i++) { var v = points[i].v; if (v !== null && v !== undefined) { lo = Math.min(lo, v); hi = Math.max(hi, v) } }
        if (lo > hi) return
        if (hi - lo < 1) { hi += 0.5; lo -= 0.5 }
        var pad = (hi - lo) * 0.12; lo -= pad; hi += pad
        var t0 = points[0].t, t1 = points[n - 1].t
        if (t1 === t0) t1 = t0 + 1
        function X(t) { return L + (t - t0) / (t1 - t0) * w }
        function Y(v) { return T + (1 - (v - lo) / (hi - lo)) * h }

        if (!compact) {                                    // rejilla y etiquetas
            ctx.strokeStyle = "#2A3850"; ctx.fillStyle = "#8A97AD"; ctx.font = "11px sans-serif"; ctx.lineWidth = 1
            for (var g = 0; g <= 3; g++) {
                var gy = T + g * h / 3
                ctx.beginPath(); ctx.moveTo(L, gy); ctx.lineTo(width - R, gy); ctx.stroke()
                ctx.fillText((hi - (hi - lo) * g / 3).toFixed(hi - lo < 10 ? 1 : 0), 2, gy + 4)
            }
            var d0 = new Date(t0), d1 = new Date(t1)
            ctx.fillText(Qt.formatTime(d0, "hh:mm"), L, height - 4)
            ctx.fillText(Qt.formatTime(d1, "hh:mm"), width - R - 34, height - 4)
        }
        // clip: solo se ve la parte "revelada" (animación)
        ctx.save(); ctx.beginPath(); ctx.rect(0, 0, L + w * reveal, height); ctx.clip()
        // área bajo la curva (degradado)
        var grad = ctx.createLinearGradient(0, T, 0, T + h)
        grad.addColorStop(0, Qt.rgba(lineColor.r, lineColor.g, lineColor.b, 0.35))
        grad.addColorStop(1, Qt.rgba(lineColor.r, lineColor.g, lineColor.b, 0))
        var seg = []
        function flush() {
            if (seg.length > 1) {
                ctx.beginPath(); ctx.moveTo(X(seg[0].t), Y(seg[0].v))
                for (var k = 1; k < seg.length; k++) ctx.lineTo(X(seg[k].t), Y(seg[k].v))
                ctx.strokeStyle = lineColor; ctx.lineWidth = compact ? 2 : 2.5; ctx.lineJoin = "round"; ctx.stroke()
                ctx.lineTo(X(seg[seg.length - 1].t), T + h); ctx.lineTo(X(seg[0].t), T + h); ctx.closePath()
                ctx.fillStyle = grad; ctx.fill()
            }
            seg = []
        }
        for (var j = 0; j < n; j++) {
            var p = points[j]
            if (p.v === null || p.v === undefined) flush(); else seg.push(p)   // hueco = cortar línea
        }
        flush()
        ctx.restore()
    }
}
