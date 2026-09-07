import QtQuick
import Quickshell.Io

// Self-bootstrap for the Dusk widget: the first time it loads without an
// valid Dusk installation, runs the bundled dusk-bootstrap to repair the
// command links and service unit and start the scheduler.
//
// Install orchestration lives here so Service.qml stays reflection + intent:
// this item reports `installed()` or `failed(message)` and nothing else.
Item {
  id: root

  signal installed()
  signal failed(string message)

  // Absolute path of the plugin folder, derived from where this file loads.
  // Used to locate the bundled scheduler/CLI and to run dusk-bootstrap.
  readonly property string pluginDir: {
    var path = String(Qt.resolvedUrl(".") || "")
    if (path.indexOf("file://") === 0) path = path.substring(7)
    try { path = decodeURIComponent(path) } catch (err) {}
    return path
  }

  function ensureInstalled() {
    if (setupProbe.running || bootstrapProcess.running) return
    setupProbe.command = [root.pluginDir + "/bin/dusk-bootstrap", "--check"]
    setupProbe.running = true
  }

  function finishSetup() {
    root.installed()
  }

  Process {
    id: setupProbe
    running: false
    command: []
    onExited: function(exitCode) {
      if (exitCode !== 0) {
        bootstrapProcess.command = [root.pluginDir + "/bin/dusk-bootstrap"]
        bootstrapProcess.running = true
      } else {
        root.finishSetup()
      }
    }
  }

  Process {
    id: bootstrapProcess
    running: false
    command: []
    stdout: StdioCollector { id: bootstrapStdout; waitForEnd: true }
    stderr: StdioCollector { id: bootstrapStderr; waitForEnd: true }
    onExited: function(exitCode) {
      if (exitCode !== 0) {
        var err = bootstrapStderr.text.trim()
        root.failed(err !== "" ? err : "dusk bootstrap failed")
      } else {
        root.finishSetup()
      }
    }
  }

  Component.onCompleted: {
    root.ensureInstalled()
  }
}
