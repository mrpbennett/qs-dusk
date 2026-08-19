import QtQuick
import qs.Commons

// A compact celestial glyph: sun for Light, crescent for Dark, and a split
// day/night dial for Auto. Each state has a distinct silhouette at bar scale.
Item {
  id: root

  property string kind: "auto" // "light" | "dark" | "auto"
  property color color: "#ffffff"

  implicitWidth: Style.space(12)
  implicitHeight: Style.space(12)

  onKindChanged: canvas.requestPaint()
  onColorChanged: canvas.requestPaint()

  function line(ctx, x1, y1, x2, y2) {
    ctx.beginPath()
    ctx.moveTo(x1, y1)
    ctx.lineTo(x2, y2)
    ctx.stroke()
  }

  Canvas {
    id: canvas
    anchors.fill: parent

    Component.onCompleted: requestPaint()

    onPaint: {
      var ctx = getContext("2d")
      var w = width
      var h = height
      var size = Math.min(w, h)
      var cx = w / 2
      var cy = h / 2
      var stroke = Math.max(1.25, size * 0.105)

      ctx.reset()
      ctx.clearRect(0, 0, w, h)
      ctx.strokeStyle = root.color
      ctx.fillStyle = root.color
      ctx.lineWidth = stroke
      ctx.lineCap = "round"

      if (root.kind === "light") {
        var sunRadius = size * 0.19
        var rayStart = size * 0.31
        var rayEnd = size * 0.43

        ctx.beginPath()
        ctx.arc(cx, cy, sunRadius, 0, Math.PI * 2)
        ctx.stroke()

        for (var i = 0; i < 8; i++) {
          var angle = i * Math.PI / 4
          root.line(ctx,
                    cx + Math.cos(angle) * rayStart,
                    cy + Math.sin(angle) * rayStart,
                    cx + Math.cos(angle) * rayEnd,
                    cy + Math.sin(angle) * rayEnd)
        }
      } else if (root.kind === "dark") {
        var moonRadius = size * 0.31

        // Cut the overlapping disc out of the filled moon for a clean crescent.
        ctx.save()
        ctx.beginPath()
        ctx.arc(cx - size * 0.04, cy, moonRadius, 0, Math.PI * 2)
        ctx.fill()
        ctx.globalCompositeOperation = "destination-out"
        ctx.beginPath()
        ctx.arc(cx + size * 0.17, cy - size * 0.06, moonRadius, 0, Math.PI * 2)
        ctx.fill()
        ctx.restore()
      } else {
        var dialRadius = size * 0.32

        ctx.beginPath()
        ctx.arc(cx, cy, dialRadius, 0, Math.PI * 2)
        ctx.stroke()

        ctx.save()
        ctx.beginPath()
        ctx.arc(cx, cy, dialRadius - stroke / 2, 0, Math.PI * 2)
        ctx.clip()
        ctx.globalAlpha = 0.32
        ctx.fillRect(cx, cy - dialRadius, dialRadius, dialRadius * 2)
        ctx.restore()

        ctx.globalAlpha = 0.75
        root.line(ctx, cx, cy - dialRadius + stroke, cx, cy + dialRadius - stroke)
      }
    }
  }
}
