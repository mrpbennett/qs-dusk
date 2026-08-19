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

  readonly property real selectListHeight:
    Math.min(Math.max(service.themeOptions.length, 0), 7) * Style.space(30) + Style.spacing.labelGap
  readonly property real expandedHeight:
    (lightSelect.expanded || darkSelect.expanded) ? root.selectListHeight : 0

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
      service.refreshThemes()
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

  // ---- panel: mode buttons + inline theme pickers ------------------------------

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    centerOnBar: true
    contentWidth: panel.fittedContentWidth(Style.space(340))
    contentHeight: panel.fittedContentHeight(Style.space(380) + root.expandedHeight)

    ColumnLayout {
      anchors.fill: parent
      spacing: Style.space(10)

      PanelHero {
        Layout.fillWidth: true
        title: "Dusk"
        meta: service.configured ? service.appearanceLabel + " · " + service.modeLabel : "Not configured"
        detail: service.configured
          ? "Next: " + service.nextTransitionText()
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

      ThemeSelect {
        id: lightSelect
        label: "Light theme"
        value: service.lightTheme
        options: service.themeOptions
        onChosen: function(v) { service.setLightTheme(v) }
      }

      ThemeSelect {
        id: darkSelect
        label: "Dark theme"
        value: service.darkTheme
        options: service.themeOptions
        onChosen: function(v) { service.setDarkTheme(v) }
      }

      Text {
        Layout.fillWidth: true
        visible: service.solarUnavailable !== ""
        text: "Fallback: " + service.solarUnavailable
        color: Qt.darker(root.foreground, 1.55)
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
        wrapMode: Text.WordWrap
      }

      Text {
        Layout.fillWidth: true
        visible: service.lastError !== ""
        text: "Error: " + service.lastError
        color: Qt.rgba(1, 0.4, 0.4, 1)
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
        wrapMode: Text.WordWrap
      }

      Text {
        Layout.fillWidth: true
        visible: !service.daemonRunning
        text: "Scheduler is not running"
        color: Qt.darker(root.foreground, 1.55)
        font.family: root.fontFamily
        font.pixelSize: Style.font.bodySmall
        wrapMode: Text.WordWrap
      }
    }
  }

  // ---- toggle-style mode button -----------------------------------------------

  component ModeButton: Item {
    id: modeBtn

    required property string label
    required property bool on
    signal press()

    Layout.fillWidth: true
    implicitHeight: Style.space(34)

    Rectangle {
      anchors.fill: parent
      radius: Style.cornerRadius
      color: modeBtn.on ? Qt.rgba(root.activeColor.r, root.activeColor.g, root.activeColor.b, 0.16) : "transparent"
      border.width: 1
      border.color: modeBtn.on
        ? Qt.rgba(root.activeColor.r, root.activeColor.g, root.activeColor.b, 0.5)
        : Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.10)
    }

    Text {
      anchors.centerIn: parent
      text: modeBtn.label
      color: modeBtn.on ? root.activeColor : Qt.darker(root.foreground, 1.35)
      font.family: root.fontFamily
      font.pixelSize: Style.font.body
      font.bold: modeBtn.on
      horizontalAlignment: Text.AlignHCenter
      verticalAlignment: Text.AlignVCenter
    }

    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: modeBtn.press()
    }
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
        color: Qt.darker(root.foreground, 1.4)
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        font.bold: true
      }

      Rectangle {
        id: trigger
        width: parent.width
        height: Style.space(34)
        radius: Style.cornerRadius
        color: themeSelect.expanded ? Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.10) : "transparent"
        border.width: 1
        border.color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.12)

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
          anchors.fill: parent
          cursorShape: Qt.PointingHandCursor
          onClicked: themeSelect.expanded = !themeSelect.expanded
        }
      }

      Flickable {
        id: list
        visible: themeSelect.expanded
        width: parent.width
        height: visible ? Math.min(column.implicitHeight, Style.space(30) * 7) : 0
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
              height: Style.space(30)
              radius: Style.cornerRadius - 2
              color: String(modelData.value) === themeSelect.value
                ? Qt.rgba(root.activeColor.r, root.activeColor.g, root.activeColor.b, 0.14)
                : "transparent"

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
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: {
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
}