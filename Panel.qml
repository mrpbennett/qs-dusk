import QtQuick
import QtQuick.Layouts
import Quickshell
import qs.Commons
import qs.Ui

// Dusk bar widget: a clean sun/moon icon button that opens a panel with the
// three mode buttons (Auto / Light / Dark) and inline theme pickers for the
// light and dark themes from the themes Omarchy ships. Everything is driven
// only through the `omarchy-auto-theme` CLI; the icon never conveys state by
// color alone.
//
// The theme pickers are inline expandable lists rather than QtQuick.Controls
// Popups: a Popup needs a window overlay, which a bar-attached KeyboardPanel
// surface does not provide, so popups render clipped and unusable there.
Panel {
  id: root
  moduleName: "dusk"
  ipcTarget: "dusk"
  manageIpc: false

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color activeColor: bar ? bar.urgent : Color.accent
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  function refreshInterval() {
    var value = root.settings ? root.settings.refreshIntervalSec : undefined
    var n = parseInt(value, 10)
    return isNaN(n) ? 30 : Math.max(5, Math.min(600, n))
  }

  Service {
    id: service
    settings: root.settings
  }

  Timer {
    interval: root.refreshInterval() * 1000
    repeat: true
    running: true
    onTriggered: {
      service.refresh()
    }
  }

  onOpenedChanged: {
    if (opened) {
      lightSelect.expanded = false
      darkSelect.expanded = false
      service.refresh()
      service.refreshThemes()
    }
  }

  // ---- bar: single clean sun/moon icon ---------------------------------------

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    iconComponent: Component {
      Icon {
        kind: service.iconKind
        color: root.foreground
        implicitWidth: Style.space(18)
        implicitHeight: Style.space(18)
      }
    }
    onPressed: function(buttonCode) {
      if (buttonCode === Qt.RightButton || buttonCode === Qt.MiddleButton) {
        service.refresh()
        service.refreshThemes()
      } else {
        root.toggle()
      }
    }
  }

  // ---- panel: appearance controls + theme pairing ------------------------------

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    centerOnBar: true
    contentWidth: panel.fittedContentWidth(Style.space(352))
    contentHeight: panel.fittedContentHeight(content.implicitHeight)

    ColumnLayout {
      id: content
      anchors.fill: parent
      spacing: Style.space(12)

      PanelHero {
        Layout.fillWidth: true
        title: "Dusk"
        meta: service.configured ? service.appearanceLabel + " · " + service.modeLabel : "Not configured"
        detail: service.busy
          ? "Applying your appearance choice..."
          : service.configured
            ? (service.desiredKind && service.appearanceLabel.toLowerCase() !== service.desiredKind
              ? "Target: " + service.desiredKind + " · Next: " + service.nextTransitionText()
              : "Next: " + service.nextTransitionText())
          : "Pick the themes below to start switching"
        foreground: root.foreground
        fontFamily: root.fontFamily
        iconOpacity: 1.0
        iconComponent: Component {
          Icon {
            kind: service.iconKind
            color: root.foreground
            implicitWidth: Style.space(18)
            implicitHeight: Style.space(18)
          }
        }
      }

      ColumnLayout {
        Layout.fillWidth: true
        spacing: Style.space(6)

        Text {
          text: "Appearance"
          color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.68)
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          font.bold: true
        }

        RowLayout {
          Layout.fillWidth: true
          spacing: Style.space(6)

          ModeButton {
            label: "Auto"
            on: service.mode === "solar" || service.mode === "scheduled"
            onPress: service.setMode("auto")
          }
          ModeButton {
            label: "Light"
            on: service.mode === "manual" && service.desiredKind === "light"
            onPress: service.setMode("light")
          }
          ModeButton {
            label: "Dark"
            on: service.mode === "manual" && service.desiredKind === "dark"
            onPress: service.setMode("dark")
          }
        }
      }

      ColumnLayout {
        Layout.fillWidth: true
        spacing: Style.space(8)

        Text {
          text: "Theme pairing"
          color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.68)
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          font.bold: true
        }

        ThemeSelect {
          id: lightSelect
          label: "Light theme"
          value: service.lightTheme
          options: service.themeOptions
          onExpandedChanged: if (expanded) darkSelect.expanded = false
          onChosen: function(v) { service.setLightTheme(v) }
        }

        ThemeSelect {
          id: darkSelect
          label: "Dark theme"
          value: service.darkTheme
          options: service.themeOptions
          onExpandedChanged: if (expanded) lightSelect.expanded = false
          onChosen: function(v) { service.setDarkTheme(v) }
        }
      }

      StatusNotice {
        Layout.fillWidth: true
        visible: service.solarUnavailable !== ""
        text: "Using fallback times: " + service.solarUnavailable
      }

      StatusNotice {
        Layout.fillWidth: true
        visible: service.lastError !== ""
        text: service.lastError
        error: true
      }

      StatusNotice {
        Layout.fillWidth: true
        visible: !service.daemonRunning
        text: "Scheduler is not running. Changes apply when it starts."
      }
    }
  }

  // ---- mode selector -----------------------------------------------------------

  // Match Omarchy's provider selector: the shared Button renders its selected
  // state from the neutral control tokens instead of the urgent status color.
  component ModeButton: Button {
    id: modeBtn

    required property string label
    required property bool on
    signal press()

    Layout.fillWidth: true
    implicitHeight: Style.space(40)
    text: modeBtn.label
    selected: modeBtn.on
    bordered: true
    focusable: true
    foreground: root.foreground
    fontFamily: root.fontFamily
    fontSize: Style.font.body
    opacity: service.busy ? 0.5 : 1
    enabled: !service.busy
    onClicked: modeBtn.press()
  }

  // ---- inline expandable theme picker -----------------------------------------

  component ThemeSelect: Item {
    id: themeSelect

    required property string label
    required property string value
    required property var options
    property bool expanded: false
    signal chosen(string value)

    Layout.fillWidth: true
    implicitHeight: body.implicitHeight
    opacity: service.busy ? 0.5 : 1

    readonly property string currentLabel: {
      for (var i = 0; i < themeSelect.options.length; i++) {
        if (String(themeSelect.options[i].value) === themeSelect.value) return String(themeSelect.options[i].label)
      }
      return themeSelect.value !== "" ? themeSelect.value : "(unset)"
    }

    Column {
      id: body
      anchors.left: parent.left
      anchors.right: parent.right
      spacing: Style.spacing.labelGap

      Text {
        text: themeSelect.label
        color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.68)
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
      }

      Rectangle {
        id: trigger
        width: parent.width
        height: Style.space(40)
        radius: Style.cornerRadius
        color: themeSelect.expanded ? Qt.rgba(root.activeColor.r, root.activeColor.g, root.activeColor.b, 0.12)
          : triggerMouse.containsMouse ? Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.07) : "transparent"
        border.width: 1
        border.color: themeSelect.expanded
          ? Qt.rgba(root.activeColor.r, root.activeColor.g, root.activeColor.b, 0.48)
          : Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.12)
        Behavior on color { ColorAnimation { duration: 120 } }
        Behavior on border.color { ColorAnimation { duration: 120 } }

        Text {
          anchors.left: parent.left
          anchors.right: chevron.left
          anchors.verticalCenter: parent.verticalCenter
          anchors.leftMargin: Style.space(10)
          anchors.rightMargin: Style.space(8)
          text: themeSelect.currentLabel
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          elide: Text.ElideRight
        }

        Text {
          id: chevron
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          anchors.rightMargin: Style.space(10)
          text: "▾"
          color: Qt.darker(root.foreground, 1.2)
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          rotation: themeSelect.expanded ? 180 : 0
          Behavior on rotation { NumberAnimation { duration: 120 } }
        }

        MouseArea {
          id: triggerMouse
          anchors.fill: parent
          enabled: !service.busy
          hoverEnabled: true
          activeFocusOnTab: true
          cursorShape: Qt.PointingHandCursor
          onClicked: themeSelect.expanded = !themeSelect.expanded
          Keys.onReturnPressed: themeSelect.expanded = !themeSelect.expanded
          Keys.onSpacePressed: themeSelect.expanded = !themeSelect.expanded
        }
      }

      Flickable {
        id: list
        visible: themeSelect.expanded
        width: parent.width
        height: visible ? Math.min(column.implicitHeight, Style.space(38) * 7) : 0
        contentHeight: column.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds

        Column {
          id: column
          width: parent.width
          spacing: Style.spacing.labelGap

          Repeater {
            model: themeSelect.options

            delegate: Rectangle {
              required property var modelData

              width: parent.width
              height: Style.space(38)
              radius: Style.cornerRadius - 2
              color: String(modelData.value) === themeSelect.value
                ? Qt.rgba(root.activeColor.r, root.activeColor.g, root.activeColor.b, 0.14)
                : itemMouse.containsMouse ? Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.07) : "transparent"
              Behavior on color { ColorAnimation { duration: 100 } }

              Text {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: Style.space(10)
                anchors.rightMargin: Style.space(10)
                text: modelData.label
                color: String(modelData.value) === themeSelect.value ? root.activeColor : root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
                font.bold: String(modelData.value) === themeSelect.value
                elide: Text.ElideRight
              }

              MouseArea {
                id: itemMouse
                anchors.fill: parent
                enabled: !service.busy
                hoverEnabled: true
                activeFocusOnTab: true
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                  themeSelect.chosen(String(modelData.value))
                  themeSelect.expanded = false
                }
                Keys.onReturnPressed: {
                  themeSelect.chosen(String(modelData.value))
                  themeSelect.expanded = false
                }
                Keys.onSpacePressed: {
                  themeSelect.chosen(String(modelData.value))
                  themeSelect.expanded = false
                }
              }
            }
          }
        }
      }
    }
  }

  component StatusNotice: Rectangle {
    id: notice

    required property string text
    property bool error: false

    implicitHeight: message.implicitHeight + Style.space(18)
    radius: Style.cornerRadius
    color: notice.error
      ? Qt.rgba(1, 0.28, 0.28, 0.10)
      : Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.06)
    border.width: 1
    border.color: notice.error
      ? Qt.rgba(1, 0.36, 0.36, 0.42)
      : Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.10)

    Text {
      id: message
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.margins: Style.space(9)
      text: notice.text
      color: notice.error ? Qt.rgba(1, 0.52, 0.52, 1) : Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.74)
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
      wrapMode: Text.WordWrap
    }
  }
}
