import QtQuick
import qs.Commons

// Compact outline glyphs with one visual weight: sun for Light, crescent for
// Dark, and sunrise for Auto. Each state stays distinct at bar scale.
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
      var stroke = Math.max(1.35, size * 0.09)

      ctx.reset()
      ctx.clearRect(0, 0, w, h)
      ctx.strokeStyle = root.color
      ctx.fillStyle = root.color
      ctx.lineWidth = stroke
      ctx.lineCap = "round"
      ctx.lineJoin = "round"

      if (root.kind === "light") {
        var sunRadius = size * 0.18
        var rayStart = size * 0.30
        var rayEnd = size * 0.41

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
        // One continuous outline avoids the heavy filled weight of a cutout.
        ctx.beginPath()
        ctx.moveTo(cx + size * 0.10, cy - size * 0.34)
        ctx.bezierCurveTo(cx - size * 0.19, cy - size * 0.25,
                          cx - size * 0.25, cy + size * 0.18,
                          cx + size * 0.02, cy + size * 0.31)
        ctx.bezierCurveTo(cx + size * 0.20, cy + size * 0.40,
                          cx + size * 0.38, cy + size * 0.27,
                          cx + size * 0.40, cy + size * 0.15)
        ctx.bezierCurveTo(cx + size * 0.09, cy + size * 0.14,
                          cx - size * 0.04, cy - size * 0.14,
                          cx + size * 0.10, cy - size * 0.34)
        ctx.stroke()
      } else {
        var horizonY = cy + size * 0.13
        var riseRadius = size * 0.19
        var autoRayStart = size * 0.29
        var autoRayEnd = size * 0.39

        ctx.beginPath()
        ctx.arc(cx, horizonY, riseRadius, Math.PI, Math.PI * 2)
        ctx.stroke()

        root.line(ctx, cx - size * 0.39, horizonY, cx + size * 0.39, horizonY)
        root.line(ctx, cx - size * 0.25, horizonY + size * 0.14,
                       cx + size * 0.25, horizonY + size * 0.14)

        for (var j = 0; j < 5; j++) {
          var autoAngle = Math.PI + j * Math.PI / 4
          root.line(ctx,
                    cx + Math.cos(autoAngle) * autoRayStart,
                    horizonY + Math.sin(autoAngle) * autoRayStart,
                    cx + Math.cos(autoAngle) * autoRayEnd,
                    horizonY + Math.sin(autoAngle) * autoRayEnd)
        }
      }
    }
  }
}
