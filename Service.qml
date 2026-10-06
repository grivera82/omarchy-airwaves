import QtQuick
import Quickshell
import Quickshell.Io

// Owns the single `airwaves daemon` process. The daemon drives mpv, follows
// what each station is playing and keeps likes/history; bar widgets on every
// monitor share this state. mpv runs detached, so music keeps playing across
// shell reloads and the next daemon picks it back up.
Item {
  id: root

  property var shell: null
  property var manifest: null

  readonly property string cli: String(Qt.resolvedUrl("bin/airwaves")).replace(/^file:\/\//, "")

  property var state: ({ status: "starting" })
  property string lastError: ""
  property int serial: 0

  readonly property bool running: daemon.running
  readonly property string status: state.status || "starting"
  readonly property bool playing: status === "playing"
  readonly property bool active: status === "playing" || status === "buffering" || status === "paused"
  readonly property var config: state.config || ({})
  readonly property var station: state.station || null
  readonly property var track: state.track || null
  readonly property var stations: state.stations || []
  readonly property var networks: state.networks || []
  readonly property var favorites: state.favorites || []
  readonly property var liked: state.liked || []
  readonly property var history: state.history || []
  readonly property int volume: state.volume === undefined ? 70 : state.volume

  // Live loudness from mpv (0..1), ~20 updates a second while playing.
  property real level: 0
  property real peak: 0
  // A fresh random spread per update gives the bars an equaliser feel
  // around the real level.
  property var bands: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]

  readonly property var stationById: {
    var m = {}
    for (var i = 0; i < stations.length; i++) m[stations[i].id] = stations[i]
    return m
  }
  readonly property var networkById: {
    var m = {}
    for (var i = 0; i < networks.length; i++) m[networks[i].id] = networks[i]
    return m
  }

  function send(cmd, args) {
    if (!daemon.running) return false
    daemon.write(JSON.stringify(Object.assign({ cmd: cmd, id: ++serial }, args || {})) + "\n")
    return true
  }

  function play(id) { return send("play", id ? { station: id } : {}) }
  function toggle() { return send("toggle") }
  function stop() { return send("stop") }
  function next() { return send("next") }
  function prev() { return send("prev") }
  function setVolume(v) { return send("volume", { value: Math.round(v) }) }
  function nudgeVolume(d) { return send("volume", { delta: d }) }
  function favorite(id, on) { return send("favorite", { station: id, on: on }) }
  function isFavorite(id) { return favorites.indexOf(id) >= 0 }
  function like(key) { return send("like", key ? { key: key } : {}) }
  function setConfig(key, value) { var a = {}; a[key] = value; return send("config", a) }

  function handleLine(line) {
    var msg
    try { msg = JSON.parse(line) } catch (e) { return }
    if (msg.type === "level") {
      root.level = msg.r || 0
      root.peak = msg.p || 0
      var b = []
      // Expand the loudness curve so quiet and loud passages look different.
      var base = Math.pow(root.level, 1.6) * 1.25
      for (var i = 0; i < 24; i++) {
        // Lower bands carry more energy; peaks lift the middle.
        var shape = 0.5 + 0.5 * Math.sin((i / 23) * Math.PI * 0.9 + 0.35)
        var v = base * shape * (0.25 + Math.random() * 1.05) + root.peak * 0.35 * Math.random() * Math.random()
        b.push(Math.max(0, Math.min(1, v)))
      }
      root.bands = b
    } else if (msg.type === "state") {
      root.state = msg.state || {}
    } else if (msg.type === "result" && !msg.ok) {
      root.lastError = msg.error || "command failed"
      clearError.restart()
    } else if (msg.type === "log" && msg.error) {
      console.warn("grivera.airwaves:", msg.error)
    }
  }

  Process {
    id: daemon
    command: [root.cli, "daemon"]
    running: true
    stdinEnabled: true
    stdout: SplitParser { onRead: function(line) { root.handleLine(line) } }
    onRunningChanged: {
      if (running) return
      root.state = Object.assign({}, root.state, { status: "offline" })
      restart.restart()
    }
  }

  Timer {
    id: restart
    interval: 5000
    onTriggered: daemon.running = true
  }

  Timer {
    id: clearError
    interval: 6000
    onTriggered: root.lastError = ""
  }
}
