import QtQuick
import Quickshell.Io

// All dusk state for the widget, spoken to only through the
// `omarchy-auto-theme` CLI (which in turn drives the scheduler daemon and,
// for theme changes, `omarchy theme set`).
Item {
  id: root

  property var settings: ({})

  property string mode: ""
  property bool configured: false
  property string currentTheme: ""
  property string desiredKind: ""
  property string desiredTheme: ""
  property string nextTransition: ""
  property string nextTransitionKind: ""
  property string locationSource: ""
  property string solarUnavailable: ""
  property string lastError: ""
  property bool daemonRunning: false
  property bool busy: false

  property string lightTheme: ""
  property string darkTheme: ""
  property var themeOptions: []

  property string _statusOutput: ""
  property string _statusError: ""
  property string _themesOutput: ""
  property string _themesError: ""
  property string _actionOutput: ""
  property string _actionError: ""

  readonly property string appearanceLabel: {
    if (!configured) return "Not configured"
    if (currentTheme === lightTheme) return "Light"
    if (currentTheme === darkTheme) return "Dark"
    return "Other theme active"
  }
  readonly property string iconKind: {
    if (currentTheme === lightTheme) return "light"
    if (currentTheme === darkTheme) return "dark"
    return "auto"
  }
  readonly property string modeLabel: {
    if (mode === "solar") return "Solar"
    if (mode === "scheduled") return "Scheduled"
    if (mode === "manual") return "Manual"
    return "Unconfigured"
  }
  readonly property string scheduleLabel: {
    if (mode === "solar") return "Sunrise & sunset"
    if (mode === "scheduled") return "Fixed times"
    if (mode === "manual") return "Manual"
    return "Unconfigured"
  }

  // Ticks once a minute purely so bindings that call nextTransitionText()
  // recompute; nextTransition itself does not change between transitions.
  property real _nowTick: Date.now()

  Timer {
    interval: 60000
    repeat: true
    running: true
    onTriggered: root._nowTick = Date.now()
  }

  signal stateLoaded()

  function commandFor(args) {
    // Quickshell may not inherit ~/.local/bin. DUSK_CLI permits an explicit
    // override while the installer default remains usable in a fresh session.
    return ["/bin/sh", "-c", "exec \"${DUSK_CLI:-$HOME/.local/bin/omarchy-auto-theme}\" \"$@\"", "dusk"].concat(args)
  }

  function refresh() {
    if (statusProcess.running) return
    _statusOutput = ""
    _statusError = ""
    statusProcess.command = commandFor(["status", "--json"])
    statusProcess.running = true
  }

  function refreshThemes() {
    if (themesProcess.running) return
    _themesOutput = ""
    _themesError = ""
    themesProcess.command = commandFor(["themes", "--json"])
    themesProcess.running = true
  }

  function runAction(args) {
    if (actionProcess.running) return
    busy = true
    _actionOutput = ""
    _actionError = ""
    actionProcess.command = commandFor(args)
    actionProcess.running = true
  }

  // ---- mode + theme selection, delegated to the scheduler CLI -------------

  function setMode(kind) {
    if (kind === "auto") {
      // A saved fixed schedule is already automatic; do not replace it.
      if (mode !== "scheduled") runAction(["solar"])
    }
    else if (kind === "light") runAction(["manual", "light"])
    else if (kind === "dark") runAction(["manual", "dark"])
  }

  function setLightTheme(slug) {
    if (!slug || slug === root.lightTheme) return
    runAction(["themes", "--light", slug])
  }

  function setDarkTheme(slug) {
    if (!slug || slug === root.darkTheme) return
    runAction(["themes", "--dark", slug])
  }

  function _parse(payload) {
    if (!payload) return
    if (payload.daemonRunning !== undefined) root.daemonRunning = payload.daemonRunning
    if (payload.mode !== undefined) root.mode = String(payload.mode || "")
    if (payload.configured !== undefined) root.configured = payload.configured === true
    if (payload.currentTheme !== undefined) root.currentTheme = String(payload.currentTheme || "")
    if (payload.desiredKind !== undefined) root.desiredKind = String(payload.desiredKind || "")
    if (payload.desiredTheme !== undefined) root.desiredTheme = String(payload.desiredTheme || "")
    if (payload.nextTransition !== undefined) root.nextTransition = String(payload.nextTransition || "")
    if (payload.nextTransitionKind !== undefined) root.nextTransitionKind = String(payload.nextTransitionKind || "")
    if (payload.locationSource !== undefined) root.locationSource = String(payload.locationSource || "")
    if (payload.solarUnavailable !== undefined) root.solarUnavailable = String(payload.solarUnavailable || "")
    if (payload.lastError !== undefined) root.lastError = String(payload.lastError || "")
    root.stateLoaded()
  }

  function nextTransitionText() {
    if (!root.nextTransition) return "none"
    var iso = new Date(root.nextTransition)
    if (isNaN(iso.getTime())) return root.nextTransition
    var hh = iso.getHours()
    var mm = ("0" + iso.getMinutes()).slice(-2)
    var kind = root.nextTransitionKind
      ? root.nextTransitionKind.charAt(0).toUpperCase() + root.nextTransitionKind.slice(1)
      : "Theme"
    var diffMs = iso.getTime() - root._nowTick
    return kind + " " + hh + ":" + mm + " · " + formatCountdown(diffMs)
  }

  function formatCountdown(diffMs) {
    if (!(diffMs > 0)) return "due now"
    var minutes = Math.floor(diffMs / 60000)
    var hours = Math.floor(minutes / 60)
    return hours > 0 ? "in " + hours + "h " + (minutes % 60) + "m" : "in " + Math.max(1, minutes) + "m"
  }

  Process {
    id: statusProcess
    running: false
    command: []
    stdout: StdioCollector { id: statusStdout; waitForEnd: true; onStreamFinished: root._statusOutput = text }
    stderr: StdioCollector { id: statusStderr; waitForEnd: true; onStreamFinished: root._statusError = text }
    onExited: function(exitCode) {
      if (exitCode === 0) {
        try {
          root._parse(JSON.parse(root._statusOutput))
        } catch (err) {
          root.lastError = "could not parse dusk status"
        }
      } else {
        root.lastError = root._statusError.trim() !== "" ? root._statusError : "dusk status failed"
        root.daemonRunning = false
      }
    }
  }

  Process {
    id: themesProcess
    running: false
    command: []
    stdout: StdioCollector { id: themesStdout; waitForEnd: true; onStreamFinished: root._themesOutput = text }
    stderr: StdioCollector { id: themesStderr; waitForEnd: true; onStreamFinished: root._themesError = text }
    onExited: function(exitCode) {
      if (exitCode === 0) {
        try {
          var payload = JSON.parse(root._themesOutput)
          var list = []
          for (var i = 0; i < payload.themes.length; i++) {
            var t = payload.themes[i]
            list.push({ value: String(t.slug), label: String(t.name) })
          }
          root.themeOptions = list
          root.lightTheme = String(payload.lightTheme || "")
          root.darkTheme = String(payload.darkTheme || "")
        } catch (err) {
          root.lastError = "could not parse dusk themes"
        }
      } else {
        root.lastError = root._themesError.trim() !== "" ? root._themesError : "dusk themes failed"
      }
    }
  }

  Process {
    id: actionProcess
    running: false
    command: []
    stdout: StdioCollector { id: actionStdout; waitForEnd: true; onStreamFinished: root._actionOutput = text }
    stderr: StdioCollector { id: actionStderr; waitForEnd: true; onStreamFinished: root._actionError = text }
    onExited: function(exitCode) {
      root.busy = false
      if (exitCode !== 0) root.lastError = root._actionError.trim() !== "" ? root._actionError : "dusk action failed"
      else root.lastError = ""
      // Actions change config; refresh reflects the scheduler's decision.
      Qt.callLater(function() { root.refresh(); root.refreshThemes(); followUpRefresh.restart() })
    }
  }

  Timer {
    id: followUpRefresh
    interval: 1500
    onTriggered: root.refresh()
  }

  Component.onCompleted: {
    refresh()
    refreshThemes()
  }

  onStateLoaded: {
    // Keep the bar buttons live even when the panel is closed.
    root.busy = actionProcess.running
  }
}
