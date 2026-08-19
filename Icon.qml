import QtQuick
import QtQuick.Shapes
import qs.Commons

// A toggle-switch glyph drawn locally: a pill track whose dark side fills from
// the right and a knob that sits at the boundary. Light = empty track, knob
// left; Dark = filled track, knob right; Auto = half filled, knob centered.
// Deliberately not a sun/moon so it never reads as a weather icon.
Item {
  id: root

  property string kind: "auto" // "light" | "dark" | "auto"
  property color color: "#ffffff"

  implicitWidth: Style.space(12)
  implicitHeight: Style.space(12)

  onKindChanged: canvas.requestPaint()
  onColorChanged: canvas.requestPaint()

  function roundedRectPath(ctx, x, y, w, h, r) {
    ctx.beginPath()
    ctx.moveTo(x + r, y)
    ctx.lineTo(x + w - r, y)
    ctx.arc(x + w - r, y + r, r, -Math.PI / 2, 0)
    ctx.lineTo(x + w, y + h - r)
    ctx.arc(x + w - r, y + h - r, r, 0, Math.PI / 2)
    ctx.lineTo(x + r, y + h)
    ctx.arc(x + r, y + h - r, r, Math.PI / 2, Math.PI)
    ctx.lineTo(x, y + r)
    ctx.arc(x + r, y + r, r, Math.PI, Math.PI * 1.5)
    ctx.closePath()
  }

  Canvas {
    id: canvas
    anchors.fill: parent

    Component.onCompleted: requestPaint()

    onPaint: {
      var ctx = getContext("2d")
      var w = width
      var h = height
      var trackH = h * 0.42
      var trackY = (h - trackH) / 2
      var trackR = trackH / 2
      var knobD = Math.max(h * 0.72, trackH * 1.35)
      var knobR = knobD / 2

      ctx.reset()
      ctx.clearRect(0, 0, w, h)

      // Fraction of the track filled from the right (the "dark" side).
      var frac = root.kind === "dark" ? 1 : (root.kind === "light" ? 0 : 0.5)

      // Track outline.
      ctx.strokeStyle = root.color
      ctx.lineWidth = Math.max(1, h * 0.07)
      ctx.globalAlpha = 0.45
      root.roundedRectPath(ctx, 0, trackY, w, trackH, trackR)
      ctx.stroke()

      // Filled dark side.
      if (frac > 0) {
        ctx.save()
        root.roundedRectPath(ctx, 0, trackY, w, trackH, trackR)
        ctx.clip()
        ctx.fillStyle = root.color
        ctx.globalAlpha = 0.55
        ctx.fillRect(w * frac, trackY, w * (1 - frac), trackH)
        ctx.restore()
      }

      // Knob at the light/dark boundary.
      ctx.globalAlpha = 1
      ctx.fillStyle = root.color
      ctx.beginPath()
      ctx.arc(frac * (w - knobD) + knobD / 2, h / 2, knobR, 0, Math.PI * 2)
      ctx.fill()
    }
  }
}
