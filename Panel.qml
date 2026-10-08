import QtQuick
import QtQuick.Controls
import QtQuick.Effects
import Quickshell
import Quickshell.Io
import qs.Ui
import qs.Commons

// Airwaves: ad-free radio in the bar. Playback, metadata and storage live in
// the daemon behind Service.qml; this widget renders its state.
Panel {
  id: root
  moduleName: "grivera.airwaves"
  ipcTarget: "grivera.airwaves"
  manageIpc: false

  // Panel commands plus status(), which voice assistants (Jarvis) and scripts
  // read: `omarchy-shell grivera.airwaves status`.
  IpcHandler {
    target: root.ipcTarget
    function open(): void { root.open() }
    function close(): void { root.close() }
    function show(): void { root.open() }
    function hide(): void { root.close() }
    function toggle(): void { root.toggle() }
    function status(): string { return JSON.stringify(root.statusSummary()) }
  }

  function statusTime(ts) { return ts ? Qt.formatDateTime(new Date(ts * 1000), "ddd MMM d, h:mm AP") : "" }

  // What's on, the station, and the last few songs.
  function statusSummary() {
    if (!svc) return { error: "Airwaves isn't running" }
    var s = svc.state || {}
    var st = s.station, t = s.track
    var o = { status: s.status || "stopped", volume: s.volume, muted: !!s.muted }
    if (st) o.station = { name: st.name, network: st.net, genre: st.genre, about: (st.desc || "").slice(0, 160),
                          listeners: st.listeners || null }
    if (t && (t.title || t.artist)) o.nowPlaying = { title: t.title || "", artist: t.artist || "", album: t.album || "", show: !!t.show }
    if (s.sleepAt) o.sleepTimerEnds = root.statusTime(s.sleepAt)
    o.recentSongs = (s.history || []).slice(0, 6).map(function(h) { return h.artist + " - " + h.title + " (" + h.stationName + ")" })
    o.favoriteStations = (s.favorites || []).map(function(id) {
      var x = (s.stations || []).filter(function(y) { return y.id === id })[0]
      return x ? x.name : id
    })
    o.likedSongs = (s.liked || []).length
    return o
  }


  readonly property var svc: root.bar && root.bar.shell ? root.bar.shell.serviceFor("grivera.airwaves") : null
  readonly property var st: svc ? svc.state : ({})
  readonly property var config: svc ? svc.config : ({})
  readonly property string status: svc ? svc.status : "offline"
  readonly property bool active: svc ? svc.active : false
  readonly property bool playing: status === "playing"
  readonly property var station: svc ? svc.station : null
  readonly property var track: svc ? svc.track : null

  readonly property color fg: root.bar ? root.bar.foreground : Color.foreground
  readonly property color dim: Qt.darker(fg, 1.4)
  readonly property color faint: Qt.rgba(fg.r, fg.g, fg.b, 0.10)
  readonly property color urgent: root.bar ? root.bar.urgent : Color.urgent
  readonly property color love: "#ff4f7b"
  readonly property string fontFamily: root.bar ? root.bar.fontFamily : Style.font.family

  readonly property string gRadio: String.fromCodePoint(0xF0439)
  readonly property string gPlay: String.fromCodePoint(0xF040A)
  readonly property string gPause: String.fromCodePoint(0xF03E4)
  readonly property string gStop: String.fromCodePoint(0xF04DB)
  readonly property string gNext: String.fromCodePoint(0xF04AD)
  readonly property string gPrev: String.fromCodePoint(0xF04AE)
  readonly property string gHeart: String.fromCodePoint(0xF02D1)
  readonly property string gHeartO: String.fromCodePoint(0xF02D5)
  readonly property string gStar: String.fromCodePoint(0xF04CE)
  readonly property string gStarO: String.fromCodePoint(0xF04D2)
  readonly property string gVolHi: String.fromCodePoint(0xF057E)
  readonly property string gVolMid: String.fromCodePoint(0xF057F)
  readonly property string gVolLo: String.fromCodePoint(0xF057D)
  readonly property string gVolOff: String.fromCodePoint(0xF0581)
  readonly property string gSearch: String.fromCodePoint(0xF0349)
  readonly property string gCopy: String.fromCodePoint(0xF018F)
  readonly property string gSleep: String.fromCodePoint(0xF04B2)
  readonly property string gPeople: String.fromCodePoint(0xF0849)
  readonly property string gLive: String.fromCodePoint(0xF0003)
  readonly property string gNote: String.fromCodePoint(0xF075A)
  readonly property string gClose: String.fromCodePoint(0xF0156)
  readonly property string gPlus: String.fromCodePoint(0xF0415)
  readonly property string gOpen: String.fromCodePoint(0xF03CC)

  property string tab: "now"
  property string filter: (svc && svc.favorites.length) ? "fav" : "all"
  property string query: ""
  property int cursor: 0

  property double nowMs: Date.now()
  Timer {
    interval: 1000
    repeat: true
    running: root.opened || (root.st.sleepAt || 0) > 0
    triggeredOnStart: true
    onTriggered: root.nowMs = Date.now()
  }

  // Gentle pulse for buffering.
  property real pulse: 1
  SequentialAnimation on pulse {
    running: root.status === "buffering"
    loops: Animation.Infinite
    alwaysRunToEnd: true
    NumberAnimation { to: 0.3; duration: 650; easing.type: Easing.InOutSine }
    NumberAnimation { to: 1; duration: 650; easing.type: Easing.InOutSine }
  }

  readonly property bool vertical: root.bar ? root.bar.vertical : false
  readonly property bool showTitle: active && config.barTitle !== false && !vertical && barText() !== ""

  implicitWidth: titleButton.visible ? titleButton.implicitWidth : iconButton.implicitWidth
  implicitHeight: titleButton.visible ? titleButton.implicitHeight : iconButton.implicitHeight

  // ---- helpers ----

  function art(path) { return path ? "file://" + path : "" }
  function net(id) { return svc && svc.networkById[id] ? svc.networkById[id] : ({ id: id, name: id, short: id, color: "" }) }
  function netColor(id) { var c = net(id).color; return c ? c : Color.accent }
  function stationOf(id) { return svc && svc.stationById[id] ? svc.stationById[id] : null }
  function songLine(t) {
    if (!t) return ""
    if (t.show) return t.title || ""
    return [t.artist, t.title].filter(function(x) { return !!x }).join(" – ")
  }
  function barText() {
    if (!station) return ""
    var s = songLine(track)
    return s || station.name
  }
  function compact(n) {
    n = Number(n || 0)
    if (n >= 10000) return Math.round(n / 1000) + "k"
    if (n >= 1000) return (n / 1000).toFixed(1).replace(/\.0$/, "") + "k"
    return String(n)
  }
  function ago(ts) {
    var s = Math.max(0, Math.floor(nowMs / 1000 - ts))
    if (s < 60) return "just now"
    if (s < 3600) return Math.floor(s / 60) + " min ago"
    if (s < 86400) return Math.floor(s / 3600) + " h ago"
    var d = new Date(ts * 1000)
    return Qt.formatDate(d, "MMM d")
  }
  function volumeGlyph() {
    if (!svc || st.muted || svc.volume === 0) return gVolOff
    return svc.volume > 66 ? gVolHi : svc.volume > 33 ? gVolMid : gVolLo
  }
  function sleepLeft() {
    var at = st.sleepAt || 0
    if (!at) return ""
    var s = Math.max(0, Math.round(at - nowMs / 1000))
    var m = Math.floor(s / 60)
    return m >= 1 ? m + " min" : s + " s"
  }
  function tooltip() {
    if (!svc) return "Airwaves"
    if (!active) return "Airwaves — ad-free radio\nMiddle-click to play " + (stationOf(st.lastStation) ? stationOf(st.lastStation).name : "")
    var lines = [station ? station.name + "  ·  " + net(station.net).name : ""]
    var s = songLine(track)
    if (s) lines.push(s)
    if (status !== "playing") lines.push(status === "paused" ? "Paused" : "Tuning in…")
    if (st.sleepAt) lines.push(gSleep + "  " + sleepLeft())
    lines.push("Middle-click play/pause · right-click next · scroll volume")
    return lines.join("\n")
  }

  readonly property var filterOptions: {
    var o = [{ value: "fav", label: "★" }, { value: "all", label: "All" }]
    var ns = svc ? svc.networks : []
    for (var i = 0; i < ns.length; i++) o.push({ value: ns[i].id, label: ns[i].short })
    return o
  }

  readonly property var visibleStations: {
    if (!svc) return []
    var q = query.toLowerCase().trim()
    var list
    if (filter === "fav") list = svc.favorites.map(function(id) { return svc.stationById[id] }).filter(function(x) { return !!x })
    else list = svc.stations.filter(function(s) { return filter === "all" || s.net === filter })
    if (!q) return list
    return list.filter(function(s) {
      var now = s.now ? (s.now.artist || "") + " " + (s.now.title || "") : ""
      return (s.name + " " + s.genre + " " + s.desc + " " + now + " " + net(s.net).name).toLowerCase().indexOf(q) >= 0
    })
  }

  readonly property var tabs: [
    { value: "now", label: "Now Playing" },
    { value: "stations", label: "Stations" },
    { value: "liked", label: "Liked" + (svc && svc.liked.length ? " · " + svc.liked.length : "") },
    { value: "settings", label: "Settings" }
  ]

  function setTab(t) {
    tab = t
    flick.contentY = 0
    if (t === "stations") cursor = Math.max(0, Math.min(cursor, visibleStations.length - 1))
  }

  function cycleFilter(dx) {
    var i = 0
    for (var k = 0; k < filterOptions.length; k++) if (filterOptions[k].value === filter) i = k
    filter = filterOptions[(i + dx + filterOptions.length) % filterOptions.length].value
    cursor = 0
  }

  function ensureVisible(item) {
    if (!item) return
    var p = item.mapToItem(column, 0, 0)
    if (p.y < flick.contentY) flick.contentY = Math.max(0, p.y - Style.space(8))
    else if (p.y + item.height > flick.contentY + flick.height)
      flick.contentY = Math.min(flick.contentHeight - flick.height, p.y + item.height - flick.height + Style.space(8))
  }

  // ---- bar ----

  BarIconButton {
    id: iconButton
    anchors.fill: parent
    visible: !titleButton.visible
    bar: root.bar
    text: root.gRadio
    opacity: root.svc && root.svc.running ? 1 : 0.5
    iconComponent: root.active && root.config.visualizer !== false ? barVizComponent : null
    tooltipText: root.tooltip()
    onPressed: function(b) { root.barPress(b) }
    onWheelMoved: function(d) { root.barWheel(d) }
  }

  WidgetButton {
    id: titleButton
    anchors.fill: parent
    visible: root.showTitle
    bar: root.bar
    labelVisible: false
    hasVisualContent: true
    fixedWidth: titleRow.implicitWidth + Style.space(17)
    tooltipText: root.tooltip()
    onPressed: function(b) { root.barPress(b) }
    onWheelMoved: function(d) { root.barWheel(d) }

    Row {
      id: titleRow
      anchors.centerIn: parent
      spacing: Style.space(7)

      Item {
        width: Style.bar.iconCanvas
        height: Style.bar.iconCanvas
        anchors.verticalCenter: parent.verticalCenter
        Loader {
          anchors.fill: parent
          sourceComponent: root.config.visualizer !== false ? barVizComponent : barGlyphComponent
        }
      }

      Marquee {
        anchors.verticalCenter: parent.verticalCenter
        maxWidth: Style.space(root.config.barTitleWidth || 180)
        text: root.barText()
        color: root.bar ? root.bar.barForeground : root.fg
        opacity: root.status === "paused" ? 0.55 : 1
        fontSize: Style.font.body
      }
    }
  }

  Component {
    id: barGlyphComponent
    Text {
      textFormat: Text.PlainText
      text: root.gRadio
      color: root.bar ? root.bar.barForeground : root.fg
      font.family: root.fontFamily
      font.pixelSize: Style.bar.iconFont
      horizontalAlignment: Text.AlignHCenter
      verticalAlignment: Text.AlignVCenter
    }
  }

  Component {
    id: barVizComponent
    Viz {
      count: 4
      bands: root.svc ? root.svc.bands : []
      color: root.bar ? root.bar.barForeground : root.fg
      gap: Math.max(2, Math.round(width * 0.09))
      idle: root.status !== "playing"
      opacity: root.status === "buffering" ? root.pulse : root.status === "paused" ? 0.5 : 1
    }
  }

  function barPress(b) {
    if (!svc) return
    if (b === Qt.MiddleButton) svc.toggle()
    else if (b === Qt.RightButton) svc.next()
    else root.toggle()
  }

  function barWheel(d) {
    if (svc && d !== 0) svc.nudgeVolume(d > 0 ? 5 : -5)
  }

  // ---- panel ----

  KeyboardPanel {
    id: panel
    anchorItem: titleButton.visible ? titleButton : iconButton
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(460))
    contentHeight: panel.fittedContentHeight(column.implicitHeight, Style.space(800))

    onOpenChanged: if (root.svc) root.svc.send("panel", { open: open })

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: searchField.activeFocus || addName.activeFocus || addUrl.activeFocus
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onMoveRequested: function(dx, dy) {
        if (root.tab === "stations") {
          if (dx) root.cycleFilter(dx)
          if (dy) {
            root.cursor = Math.max(0, Math.min(root.visibleStations.length - 1, root.cursor + dy))
            Qt.callLater(function() { root.ensureVisible(stationRepeater.itemAt(root.cursor)) })
          }
        } else if (root.tab === "now" && dx && root.svc) {
          if (dx > 0) root.svc.next(); else root.svc.prev()
        } else if (dy) {
          flick.contentY = Math.max(0, Math.min(flick.contentHeight - flick.height, flick.contentY + dy * Style.space(80)))
        }
      }
      onActivateRequested: {
        if (!root.svc) return
        if (root.tab === "stations" && root.visibleStations[root.cursor]) root.svc.play(root.visibleStations[root.cursor].id)
        else root.svc.toggle()
      }
      onTextKey: function(t) {
        if (!root.svc) return
        if (/^[1-4]$/.test(t)) root.setTab(root.tabs[Number(t) - 1].value)
        else if (t === "/") { root.setTab("stations"); searchField.forceActiveFocus() }
        else if (t === "+" || t === "=") root.svc.nudgeVolume(5)
        else if (t === "-") root.svc.nudgeVolume(-5)
        else if (t === "m") root.svc.send("mute")
        else if (t === "s") root.svc.stop()
        else if (t === "n") root.svc.next()
        else if (t === "p") root.svc.prev()
        else if (t === "L" || t === "♥") root.svc.like()
        else if (t === "f") {
          var s = root.tab === "stations" ? root.visibleStations[root.cursor] : root.station
          if (s) root.svc.favorite(s.id, !root.svc.isFavorite(s.id))
        }
      }

      Flickable {
        id: flick
        anchors.fill: parent
        contentHeight: column.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        interactive: contentHeight > height
        ScrollBar.vertical: ScrollBar { policy: flick.interactive ? ScrollBar.AsNeeded : ScrollBar.AlwaysOff; width: Style.space(4) }

        Column {
          id: column
          width: parent.width
          spacing: Style.space(12)

          // Header: the big card on Now Playing, a slim player elsewhere.
          Loader {
            width: parent.width
            sourceComponent: root.tab === "now" ? (root.active ? nowCard : idleCard) : miniPlayer
          }

          ButtonGroup {
            options: root.tabs
            value: root.tab
            foreground: root.fg
            fontFamily: root.fontFamily
            fontSize: Style.font.bodySmall
            focusable: false
            onChanged: function(v) { root.setTab(v) }
          }

          Text {
            visible: text !== ""
            width: parent.width
            wrapMode: Text.WordWrap
            text: !root.svc ? "Service not loaded"
              : !root.svc.running ? "Backend stopped, restarting…"
              : root.st.mpv === false ? "mpv isn't installed. Install the mpv package to play radio."
              : root.svc.lastError || root.st.error || ""
            color: root.urgent
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }

          // ================================================== now playing
          Column {
            visible: root.tab === "now"
            width: parent.width
            spacing: Style.space(12)

            // Transport
            Item {
              visible: root.active
              width: parent.width
              height: Style.space(52)

              Row {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                spacing: Style.space(6)

                RoundButton { glyph: root.gPrev; tip: "Previous station (h)"; onClicked: root.svc.prev() }
                RoundButton {
                  glyph: root.status === "paused" ? root.gPlay : root.gPause
                  tip: root.status === "paused" ? "Play (space)" : "Pause (space)"
                  big: true
                  filled: true
                  onClicked: root.svc.toggle()
                }
                RoundButton { glyph: root.gNext; tip: "Next station (l)"; onClicked: root.svc.next() }
                RoundButton { glyph: root.gStop; tip: "Stop (s)"; onClicked: root.svc.stop() }
              }

              Row {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                spacing: Style.space(4)

                RoundButton {
                  visible: !!root.track && !!root.track.title
                  glyph: root.track && root.track.liked ? root.gHeart : root.gHeartO
                  tint: root.track && root.track.liked ? root.love : root.fg
                  tip: root.track && root.track.liked ? "Unlike (L)" : "Like this song (L)"
                  onClicked: root.svc.like()
                }
                RoundButton {
                  visible: !!root.track && !!root.track.title
                  glyph: root.gSearch
                  tip: "Find it on " + root.searchName()
                  onClicked: root.svc.send("search")
                }
                RoundButton {
                  visible: !!root.track && !!root.track.title
                  glyph: root.gCopy
                  tip: "Copy artist and title"
                  onClicked: root.svc.send("copy")
                }
              }
            }

            // Volume
            Item {
              visible: root.active
              width: parent.width
              height: volSlider.implicitHeight

              Text {
                id: volIcon
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                width: Style.space(22)
                textFormat: Text.PlainText
                text: root.volumeGlyph()
                color: root.st.muted ? root.dim : root.fg
                font.family: root.fontFamily
                font.pixelSize: Style.font.heading
                MouseArea {
                  anchors.fill: parent
                  cursorShape: Qt.PointingHandCursor
                  onClicked: root.svc.send("mute")
                }
              }
              PanelSlider {
                id: volSlider
                anchors.left: volIcon.right
                anchors.leftMargin: Style.space(6)
                anchors.right: volText.left
                anchors.rightMargin: Style.space(8)
                anchors.verticalCenter: parent.verticalCenter
                bar: root.bar
                minimum: 0
                maximum: 100
                step: 1
                integer: true
                value: root.svc ? root.svc.volume : 0
                onMoved: function(v) { root.svc.setVolume(v) }
                onReleased: function(v) { root.svc.setVolume(v) }
                onRightClicked: root.svc.send("mute")
              }
              Text {
                id: volText
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                width: Style.space(30)
                horizontalAlignment: Text.AlignRight
                text: root.st.muted ? "muted" : Math.round(volSlider.liveValue) + "%"
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
              }
            }

            // Sleep timer
            Item {
              visible: root.active
              width: parent.width
              implicitHeight: sleepGroup.implicitHeight

              Text {
                id: sleepLabel
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                text: root.gSleep + "  Sleep"
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
              }
              ButtonGroup {
                id: sleepGroup
                anchors.left: sleepLabel.right
                anchors.leftMargin: Style.space(10)
                anchors.verticalCenter: parent.verticalCenter
                options: [
                  { value: "0", label: "Off" }, { value: "15", label: "15m" }, { value: "30", label: "30m" },
                  { value: "60", label: "1h" }, { value: "90", label: "90m" }
                ]
                value: root.sleepChoice
                foreground: root.fg
                fontFamily: root.fontFamily
                fontSize: Style.font.caption
                focusable: false
                onChanged: function(v) { root.sleepChoice = v; root.svc.send("sleep", { minutes: Number(v) }) }
              }
              Text {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                visible: !!root.st.sleepAt
                text: root.sleepLeft() + " left"
                color: Color.accent
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                font.bold: true
              }
            }

            // Recently played
            Column {
              visible: root.svc && root.svc.history.length > 0
              width: parent.width
              spacing: Style.space(2)

              PanelSectionHeader {
                text: "RECENTLY PLAYED"
                foreground: root.fg
                fontFamily: root.fontFamily
                bottomPadding: Style.space(4)
              }
              Repeater {
                model: root.svc ? root.svc.history.slice(0, 8) : []
                SongRow { required property var modelData; width: parent.width; song: modelData; showAgo: true }
              }
            }
          }

          // ================================================== stations
          Column {
            visible: root.tab === "stations"
            width: parent.width
            spacing: Style.space(8)

            TextField {
              id: searchField
              width: parent.width
              placeholderText: "Search " + (root.svc ? root.svc.stations.length : "") + " stations, genres, songs on air…"
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
              foreground: root.fg
              text: root.query
              onTextChanged: { root.query = text; root.cursor = 0 }
              Keys.onEscapePressed: { if (text) text = ""; else keyCatcher.forceActiveFocus() }
              Keys.onReturnPressed: {
                if (root.visibleStations.length) root.svc.play(root.visibleStations[0].id)
                keyCatcher.forceActiveFocus()
              }
              Keys.onDownPressed: keyCatcher.forceActiveFocus()
            }

            ButtonGroup {
              options: root.filterOptions
              value: root.filter
              foreground: root.fg
              fontFamily: root.fontFamily
              fontSize: Style.font.caption
              focusable: false
              onChanged: function(v) { root.filter = v; root.cursor = 0 }
            }

            Text {
              visible: root.visibleStations.length === 0
              width: parent.width
              topPadding: Style.space(18)
              bottomPadding: Style.space(18)
              horizontalAlignment: Text.AlignHCenter
              wrapMode: Text.WordWrap
              text: root.query ? "No station matches “" + root.query + "”."
                : root.filter === "fav" ? "No favorites yet. Star stations in the other lists and they'll line up here; next and previous step through them."
                : "Loading stations…"
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
            }

            Column {
              width: parent.width
              spacing: Style.space(2)
              Repeater {
                id: stationRepeater
                model: root.visibleStations
                StationRow {
                  required property var modelData
                  required property int index
                  width: parent.width
                  s: modelData
                  cursorOn: root.tab === "stations" && root.cursor === index && keyCatcher.activeFocus
                }
              }
            }

            // About the network, with a way to support it.
            Rectangle {
              id: aboutBox
              readonly property var n: root.filter !== "all" && root.filter !== "fav" ? root.net(root.filter) : null
              visible: !!n && !!n.about
              width: parent.width
              height: aboutCol.implicitHeight + Style.space(20)
              radius: Style.cornerRadius
              color: Qt.rgba(root.fg.r, root.fg.g, root.fg.b, 0.04)
              border.width: 1
              border.color: root.faint

              Column {
                id: aboutCol
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.margins: Style.space(12)
                spacing: Style.space(8)
                Text {
                  width: parent.width
                  wrapMode: Text.WordWrap
                  text: aboutBox.n ? aboutBox.n.about : ""
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                }
                Button {
                  visible: !!(aboutBox.n && aboutBox.n.support)
                  text: "Support " + (aboutBox.n ? aboutBox.n.name : "")
                  iconText: root.gHeart
                  bordered: true
                  foreground: root.fg
                  fontFamily: root.fontFamily
                  fontSize: Style.font.caption
                  onClicked: root.svc.send("open", { url: aboutBox.n.support })
                }
              }
            }

            Text {
              width: parent.width
              wrapMode: Text.WordWrap
              text: "Click to play · ★ to favorite · next/previous step through the list you started from. Keys: j/k move, Enter play, f favorite, h/l switch network, / search."
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              font.italic: true
            }
          }

          // ================================================== liked
          Column {
            visible: root.tab === "liked"
            width: parent.width
            spacing: Style.space(2)

            Text {
              visible: root.svc && root.svc.liked.length === 0
              width: parent.width
              topPadding: Style.space(24)
              bottomPadding: Style.space(24)
              horizontalAlignment: Text.AlignHCenter
              wrapMode: Text.WordWrap
              text: root.gHeartO + "\n\nHear something you love? Tap the heart (or press L, or bind `airwaves like` to a key) and it lands here, ready to find on " + root.searchName() + "."
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
            }

            Repeater {
              model: root.svc ? root.svc.liked : []
              SongRow { required property var modelData; width: parent.width; song: modelData; likedList: true }
            }
          }

          // ================================================== settings
          Column {
            visible: root.tab === "settings"
            width: parent.width
            spacing: Style.space(10)

            PanelSectionHeader { text: "BAR"; foreground: root.fg; fontFamily: root.fontFamily }
            SettingToggle { key: "visualizer"; label: "Live visualizer"; description: "Bars in the bar that move with the music." }
            SettingToggle { key: "barTitle"; label: "Song title in the bar"; description: "Scrolls when it doesn't fit." }

            PanelSectionHeader { text: "LISTENING"; foreground: root.fg; fontFamily: root.fontFamily }
            SettingToggle { key: "resume"; label: "Resume after login"; description: "If the radio was on when you logged out, pick up where you left off." }
            SettingToggle { key: "notify"; label: "Song change notifications"; description: "The Omarchy media OSD already shows new songs; this adds a notification too." }
            SettingToggle { key: "lookupArt"; label: "Find album art"; description: "Looks up covers for SomaFM and your own stations on the iTunes Search API." }

            SettingRow {
              label: "Stream quality"
              ButtonGroup {
                options: [{ value: "high", label: "High" }, { value: "low", label: "Data saver" }]
                value: root.config.quality || "high"
                foreground: root.fg
                fontFamily: root.fontFamily
                fontSize: Style.font.caption
                focusable: false
                onChanged: function(v) { root.svc.setConfig("quality", v) }
              }
            }
            SettingRow {
              label: "Find songs on"
              ButtonGroup {
                options: [{ value: "youtube", label: "YouTube Music" }, { value: "spotify", label: "Spotify" }, { value: "apple", label: "Apple Music" }]
                value: root.config.search || "youtube"
                foreground: root.fg
                fontFamily: root.fontFamily
                fontSize: Style.font.caption
                focusable: false
                onChanged: function(v) { root.svc.setConfig("search", v) }
              }
            }

            PanelSectionHeader { text: "YOUR STATIONS"; foreground: root.fg; fontFamily: root.fontFamily }
            Text {
              width: parent.width
              wrapMode: Text.WordWrap
              text: "Add any Icecast/Shoutcast stream. It shows up under Mine."
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }
            Row {
              width: parent.width
              spacing: Style.space(6)
              TextField {
                id: addName
                width: Style.space(120)
                placeholderText: "Name"
                font.family: root.fontFamily
                font.pixelSize: Style.font.bodySmall
                foreground: root.fg
                Keys.onEscapePressed: keyCatcher.forceActiveFocus()
                Keys.onReturnPressed: addUrl.forceActiveFocus()
              }
              TextField {
                id: addUrl
                width: parent.width - addName.width - addButton.width - Style.space(12)
                placeholderText: "https://…/stream"
                font.family: root.fontFamily
                font.pixelSize: Style.font.bodySmall
                foreground: root.fg
                Keys.onEscapePressed: keyCatcher.forceActiveFocus()
                Keys.onReturnPressed: addButton.clicked()
              }
              Button {
                id: addButton
                text: "Add"
                iconText: root.gPlus
                bordered: true
                foreground: root.fg
                fontFamily: root.fontFamily
                fontSize: Style.font.caption
                enabled: addUrl.text.length > 8
                onClicked: {
                  if (!root.svc.send("addStation", { name: addName.text, url: addUrl.text })) return
                  addName.text = ""
                  addUrl.text = ""
                  keyCatcher.forceActiveFocus()
                }
              }
            }
            Repeater {
              model: root.svc ? root.svc.stations.filter(function(s) { return s.net === "custom" }) : []
              Item {
                required property var modelData
                width: parent.width
                height: Style.space(26)
                Text {
                  anchors.left: parent.left
                  anchors.right: rm.left
                  anchors.verticalCenter: parent.verticalCenter
                  text: modelData.name
                  elide: Text.ElideRight
                  color: root.fg
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.body
                }
                PanelActionButton {
                  id: rm
                  anchors.right: parent.right
                  anchors.verticalCenter: parent.verticalCenter
                  iconText: root.gClose
                  tooltipText: "Remove " + modelData.name
                  foreground: root.dim
                  hoverColor: root.urgent
                  fontSize: Style.font.body
                  onClicked: root.svc.send("removeStation", { station: modelData.id })
                }
              }
            }

            PanelSectionHeader { text: "KEYS & COMMAND LINE"; foreground: root.fg; fontFamily: root.fontFamily }
            Text {
              width: parent.width
              wrapMode: Text.WordWrap
              text: (root.st.mpris ? "Media keys work out of the box: play/pause, and next/previous switch stations."
                                   : "Install the mpv-mpris package so media keys can control Airwaves.")
                + "\n\nFor your own bindings:\n" + (root.svc ? root.svc.cli : "airwaves") + " toggle | next | prev | like | stop | play <name> | volume +5 | sleep 30"
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              textFormat: Text.PlainText
            }
          }

          Item { width: parent.width; height: Style.space(2) }
        }
      }
    }
  }

  property string sleepChoice: "0"
  Connections {
    target: root.svc
    function onStateChanged() { if (!root.st.sleepAt) root.sleepChoice = "0" }
  }

  function searchName() {
    var s = config.search || "youtube"
    return s === "spotify" ? "Spotify" : s === "apple" ? "Apple Music" : "YouTube Music"
  }

  // ================================================================ cards

  Component {
    id: nowCard
    Item {
      id: card
      width: parent ? parent.width : 0
      height: Style.space(236)
      readonly property string cover: root.track && root.track.artLocal ? root.art(root.track.artLocal) : root.station ? root.art(root.station.logo) : ""
      readonly property color tint: root.station ? root.netColor(root.station.net) : Color.accent

      Rectangle {
        id: cardBg
        anchors.fill: parent
        radius: Math.max(Style.cornerRadius, Style.space(6))
        color: Qt.rgba(card.tint.r, card.tint.g, card.tint.b, 0.10)
        border.width: 1
        border.color: root.faint
        clip: true

        // Blurred cover as a backdrop.
        Image {
          id: backdrop
          anchors.fill: parent
          source: card.cover
          fillMode: Image.PreserveAspectCrop
          sourceSize.width: 256
          sourceSize.height: 256
          asynchronous: true
          visible: false
        }
        MultiEffect {
          anchors.fill: parent
          source: backdrop
          visible: backdrop.status === Image.Ready
          blurEnabled: true
          blur: 1.0
          blurMax: 64
          saturation: 0.15
          opacity: 0.42
        }
        Rectangle {
          anchors.fill: parent
          gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.rgba(Color.popups.background.r, Color.popups.background.g, Color.popups.background.b, 0.15) }
            GradientStop { position: 1.0; color: Qt.rgba(Color.popups.background.r, Color.popups.background.g, Color.popups.background.b, 0.80) }
          }
        }

        // Spectrum along the bottom edge.
        Viz {
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.bottom: parent.bottom
          anchors.margins: Style.space(14)
          height: Style.space(30)
          count: 24
          bands: root.svc ? root.svc.bands : []
          color: card.tint
          gap: Style.space(3)
          bottomAligned: true
          idle: root.status !== "playing"
          opacity: root.status === "playing" ? 0.85 : 0.35
        }
      }

      Item {
        id: coverBox
        x: Style.space(16)
        y: Style.space(16)
        width: Style.space(132)
        height: width
        scale: root.playing ? 1 + (root.svc ? root.svc.level : 0) * 0.025 : 1
        Behavior on scale { NumberAnimation { duration: 90 } }

        Rectangle {
          anchors.fill: parent
          anchors.margins: -1
          radius: Style.space(8)
          color: "transparent"
          border.width: 1
          border.color: Qt.rgba(root.fg.r, root.fg.g, root.fg.b, 0.18)
        }
        Cover {
          anchors.fill: parent
          source: card.cover
          stationRef: root.station
          radiusPx: Style.space(7)
        }
      }

      Column {
        anchors.left: coverBox.right
        anchors.leftMargin: Style.space(14)
        anchors.right: parent.right
        anchors.rightMargin: Style.space(14)
        y: Style.space(18)
        spacing: Style.space(5)

        Row {
          spacing: Style.space(6)
          Rectangle {
            width: Style.space(7); height: width; radius: width / 2
            anchors.verticalCenter: parent.verticalCenter
            color: card.tint
          }
          Text {
            text: (root.station ? root.net(root.station.net).name : "").toUpperCase()
            color: root.fg
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            font.bold: true
            font.letterSpacing: 1.2
          }
          Text {
            text: root.status === "buffering" ? "· TUNING IN" : root.status === "paused" ? "· PAUSED" : "· " + root.gLive + " LIVE"
            color: root.status === "playing" ? root.urgent : root.dim
            opacity: root.status === "buffering" ? root.pulse : 1
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            font.bold: true
          }
        }

        Text {
          width: parent.width
          textFormat: Text.PlainText
          text: root.track && root.track.title ? root.track.title : root.station ? root.station.name : ""
          color: root.fg
          wrapMode: Text.WordWrap
          maximumLineCount: 3
          elide: Text.ElideRight
          font.family: root.fontFamily
          font.pixelSize: Style.font.heading
          font.bold: true
        }
        Text {
          visible: text !== ""
          width: parent.width
          textFormat: Text.PlainText
          text: root.track ? (root.track.artist || "") : (root.station ? root.station.genre : "")
          color: root.fg
          opacity: 0.85
          elide: Text.ElideRight
          font.family: root.fontFamily
          font.pixelSize: Style.font.subtitle
        }
        Text {
          visible: text !== ""
          width: parent.width
          textFormat: Text.PlainText
          text: !root.track ? "" : root.track.show
            ? ((root.track.genres || []).join(" · ") + (root.track.next ? ((root.track.genres || []).length ? "\n" : "") + "Next: " + root.track.next : ""))
            : [root.track.album, root.track.year].filter(function(x) { return !!x }).join(" · ")
          color: root.dim
          wrapMode: Text.WordWrap
          maximumLineCount: 2
          elide: Text.ElideRight
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
        }

        Item { width: 1; height: Style.space(2) }

        // Station line with favorite star.
        Row {
          spacing: Style.space(6)
          Text {
            textFormat: Text.PlainText
            text: root.station ? (root.track && root.track.title ? "on " + root.station.name : root.station.desc) : ""
            width: Math.min(implicitWidth, card.width - coverBox.width - Style.space(90))
            elide: Text.ElideRight
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            anchors.verticalCenter: parent.verticalCenter
          }
          Text {
            readonly property bool fav: root.station && root.svc && root.svc.isFavorite(root.station.id)
            text: fav ? root.gStar : root.gStarO
            color: fav ? Color.accent : root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            anchors.verticalCenter: parent.verticalCenter
            MouseArea {
              anchors.fill: parent
              anchors.margins: -4
              cursorShape: Qt.PointingHandCursor
              onClicked: root.svc.favorite(root.station.id, !parent.fav)
            }
          }
        }

        Text {
          visible: root.st.bitrate > 0
          text: root.st.bitrate + " kbps " + (root.st.codec || "").toUpperCase() + (root.station && root.station.listeners ? "   " + root.gPeople + " " + root.compact(root.station.listeners) : "")
          color: root.dim
          opacity: 0.8
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
        }
      }
    }
  }

  // Shown on Now Playing while nothing is on.
  Component {
    id: idleCard
    Column {
      id: idleRoot
      width: parent ? parent.width : 0
      spacing: Style.space(12)
      readonly property var last: root.stationOf(root.st.lastStation)

      Rectangle {
        width: parent.width
        height: idleCol.implicitHeight + Style.space(36)
        radius: Math.max(Style.cornerRadius, Style.space(6))
        color: Qt.rgba(Color.accent.r, Color.accent.g, Color.accent.b, 0.07)
        border.width: 1
        border.color: root.faint

        Column {
          id: idleCol
          anchors.centerIn: parent
          width: parent.width - Style.space(40)
          spacing: Style.space(10)

          Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.gRadio
            color: Color.accent
            font.family: root.fontFamily
            font.pixelSize: Style.font.displayLarge * 1.5
          }
          Text {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            text: "Airwaves"
            color: root.fg
            font.family: root.fontFamily
            font.pixelSize: Style.font.heading
            font.bold: true
          }
          Text {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            text: (root.svc ? root.svc.stations.length : 0) + " ad-free stations from SomaFM, Radio Paradise, NTS and FIP: listener-supported radio, curated by people, with no commercials."
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
          }
          Button {
            anchors.horizontalCenter: parent.horizontalCenter
            text: idleRoot.last ? "Play " + idleRoot.last.name : "Start listening"
            iconText: root.gPlay
            bordered: true
            foreground: root.fg
            fontFamily: root.fontFamily
            onClicked: root.svc.play(idleRoot.last ? idleRoot.last.id : "")
          }
        }
      }

      // Favorites as quick-start tiles.
      Grid {
        visible: root.svc && root.svc.favorites.length > 0
        columns: 4
        spacing: Style.space(8)
        readonly property real tile: (parent.width - 3 * spacing) / 4
        Repeater {
          model: root.svc ? root.svc.favorites.slice(0, 8) : []
          Item {
            id: tileItem
            required property var modelData
            readonly property var s: root.stationOf(modelData)
            visible: !!s
            width: parent.tile
            height: parent.tile + Style.space(18)
            Cover {
              width: parent.width
              height: width
              source: tileItem.s ? root.art(tileItem.s.logo) : ""
              stationRef: tileItem.s
              radiusPx: Style.space(6)
              scale: tileMouse.containsMouse ? 1.04 : 1
              Behavior on scale { NumberAnimation { duration: 120 } }
            }
            Text {
              anchors.bottom: parent.bottom
              width: parent.width
              horizontalAlignment: Text.AlignHCenter
              text: tileItem.s ? tileItem.s.name : ""
              elide: Text.ElideRight
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }
            MouseArea {
              id: tileMouse
              anchors.fill: parent
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onClicked: root.svc.play(tileItem.modelData)
            }
          }
        }
      }
    }
  }

  // Slim player above the other tabs.
  Component {
    id: miniPlayer
    Item {
      width: parent ? parent.width : 0
      height: root.active ? Style.space(48) : 0
      visible: root.active

      Cover {
        id: miniCover
        width: Style.space(44)
        height: width
        anchors.verticalCenter: parent.verticalCenter
        source: root.track && root.track.artLocal ? root.art(root.track.artLocal) : root.station ? root.art(root.station.logo) : ""
        stationRef: root.station
        radiusPx: Style.space(5)
      }
      Column {
        anchors.left: miniCover.right
        anchors.leftMargin: Style.space(10)
        anchors.right: miniButtons.left
        anchors.rightMargin: Style.space(8)
        anchors.verticalCenter: parent.verticalCenter
        spacing: Style.space(2)
        Text {
          width: parent.width
          textFormat: Text.PlainText
          text: root.track && root.track.title ? root.track.title : root.station ? root.station.name : ""
          elide: Text.ElideRight
          color: root.fg
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          font.bold: true
        }
        Text {
          width: parent.width
          textFormat: Text.PlainText
          text: [root.track && !root.track.show ? root.track.artist : "", root.station ? root.station.name : ""].filter(function(x) { return !!x }).join("  ·  ")
          elide: Text.ElideRight
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
        }
      }
      Row {
        id: miniButtons
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        spacing: Style.space(2)
        RoundButton {
          visible: !!root.track && !!root.track.title
          glyph: root.track && root.track.liked ? root.gHeart : root.gHeartO
          tint: root.track && root.track.liked ? root.love : root.fg
          tip: "Like"
          small: true
          onClicked: root.svc.like()
        }
        RoundButton { glyph: root.status === "paused" ? root.gPlay : root.gPause; small: true; filled: true; onClicked: root.svc.toggle() }
        RoundButton { glyph: root.gNext; small: true; onClicked: root.svc.next() }
      }
    }
  }

  // ================================================================ pieces

  // Level bars. Heights follow the service's bands; Behavior smooths them.
  component Viz: Item {
    id: viz
    property int count: 4
    property var bands: []
    property color color: root.fg
    property real gap: 2
    property bool idle: false
    property bool bottomAligned: false
    readonly property real barW: Math.max(1, (width - gap * (count - 1)) / count)

    Repeater {
      model: viz.count
      Rectangle {
        required property int index
        readonly property real v: viz.idle ? 0.12 + 0.06 * ((index * 7) % 3)
          : (viz.bands.length ? viz.bands[Math.floor(index * viz.bands.length / viz.count) % viz.bands.length] : 0)
        x: index * (viz.barW + viz.gap)
        width: viz.barW
        height: Math.max(viz.barW * 0.9, viz.height * (0.12 + 0.88 * v))
        y: viz.bottomAligned ? viz.height - height : (viz.height - height) / 2
        radius: Math.min(width / 2, Style.space(2))
        color: viz.color
        Behavior on height { NumberAnimation { duration: 95; easing.type: Easing.OutQuad } }
      }
    }
  }

  // Text that scrolls back and forth when it doesn't fit.
  component Marquee: Item {
    id: mq
    property string text: ""
    property real maxWidth: 160
    property color color: root.fg
    property real fontSize: Style.font.body
    readonly property bool overflow: label.implicitWidth > maxWidth
    implicitWidth: Math.min(label.implicitWidth, maxWidth)
    implicitHeight: label.implicitHeight
    clip: true

    Text {
      id: label
      textFormat: Text.PlainText
      text: mq.text
      color: mq.color
      font.family: root.fontFamily
      font.pixelSize: mq.fontSize
      renderType: Text.NativeRendering
      onTextChanged: x = 0
    }

    SequentialAnimation {
      id: scroller
      running: mq.overflow && mq.visible
      loops: Animation.Infinite
      PauseAnimation { duration: 2500 }
      NumberAnimation {
        target: label; property: "x"; to: mq.maxWidth - label.implicitWidth
        duration: Math.max(1500, (label.implicitWidth - mq.maxWidth) * 28); easing.type: Easing.InOutSine
      }
      PauseAnimation { duration: 2000 }
      NumberAnimation { target: label; property: "x"; to: 0; duration: 600; easing.type: Easing.InOutQuad }
    }
  }

  // Cover art with rounded corners, or a station monogram until it loads.
  component Cover: Item {
    id: cov
    property string source: ""
    property var stationRef: null
    property real radiusPx: Style.space(6)
    readonly property color tint: stationRef ? root.netColor(stationRef.net) : Color.accent

    Rectangle {
      anchors.fill: parent
      visible: img.status !== Image.Ready
      radius: cov.radiusPx
      gradient: Gradient {
        GradientStop { position: 0; color: Qt.lighter(cov.tint, 1.15) }
        GradientStop { position: 1; color: Qt.darker(cov.tint, 1.6) }
      }
      Column {
        anchors.centerIn: parent
        width: parent.width - Style.space(8)
        spacing: 0
        Text {
          width: parent.width
          horizontalAlignment: Text.AlignHCenter
          text: cov.stationRef ? root.net(cov.stationRef.net).short.toUpperCase() : root.gRadio
          color: "#ffffff"
          opacity: 0.75
          font.family: root.fontFamily
          font.pixelSize: Math.max(7, cov.height * 0.13)
          font.bold: true
          font.letterSpacing: 1
        }
        Text {
          width: parent.width
          horizontalAlignment: Text.AlignHCenter
          text: cov.stationRef ? cov.stationRef.name.replace(/^(FIP|NTS)\s*/, "") || cov.stationRef.name : ""
          color: "#ffffff"
          elide: Text.ElideRight
          wrapMode: Text.WordWrap
          maximumLineCount: 2
          font.family: root.fontFamily
          font.pixelSize: Math.max(8, cov.height * 0.17)
          font.bold: true
        }
      }
    }

    Image {
      id: img
      anchors.fill: parent
      source: cov.source
      sourceSize.width: Math.ceil(cov.width * 2)
      sourceSize.height: Math.ceil(cov.height * 2)
      fillMode: Image.PreserveAspectCrop
      asynchronous: true
      smooth: true
      mipmap: true
      visible: false
    }
    Rectangle {
      id: mask
      anchors.fill: parent
      radius: cov.radiusPx
      visible: false
      layer.enabled: true
    }
    MultiEffect {
      anchors.fill: parent
      source: img
      visible: img.status === Image.Ready
      maskEnabled: true
      maskSource: mask
      maskThresholdMin: 0.5
      maskSpreadAtMin: 1.0
    }
  }

  component RoundButton: Item {
    id: rb
    property string glyph: ""
    property string tip: ""
    property bool big: false
    property bool small: false
    property bool filled: false
    property color tint: root.fg
    signal clicked()
    width: big ? Style.space(48) : small ? Style.space(30) : Style.space(36)
    height: width

    Rectangle {
      anchors.fill: parent
      radius: width / 2
      color: rb.filled ? Color.accent : Qt.rgba(root.fg.r, root.fg.g, root.fg.b, rbMouse.containsMouse ? 0.12 : 0.0)
      border.width: rb.filled ? 0 : 1
      border.color: rbMouse.containsMouse ? Qt.rgba(root.fg.r, root.fg.g, root.fg.b, 0.35) : root.faint
      scale: rbMouse.pressed ? 0.92 : rbMouse.containsMouse && rb.filled ? 1.05 : 1
      Behavior on scale { NumberAnimation { duration: 90 } }
      Behavior on color { ColorAnimation { duration: 120 } }
    }
    Text {
      anchors.centerIn: parent
      textFormat: Text.PlainText
      text: rb.glyph
      color: rb.filled ? Color.popups.background : rb.tint
      font.family: root.fontFamily
      font.pixelSize: rb.big ? Style.font.display : rb.small ? Style.font.body : Style.font.heading
    }
    MouseArea {
      id: rbMouse
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: rb.clicked()
    }
    ToolTip.visible: rbMouse.containsMouse && rb.tip !== ""
    ToolTip.text: rb.tip
    ToolTip.delay: 500
  }

  component StationRow: Item {
    id: row
    property var s: ({})
    property bool cursorOn: false
    readonly property bool current: root.active && root.station && root.station.id === s.id
    readonly property bool fav: root.svc ? root.svc.isFavorite(s.id) : false
    implicitHeight: Style.space(58)

    Rectangle {
      anchors.fill: parent
      radius: Style.cornerRadius
      color: row.current ? Qt.rgba(Color.accent.r, Color.accent.g, Color.accent.b, rowMouse.containsMouse ? 0.22 : 0.14)
        : Qt.rgba(root.fg.r, root.fg.g, root.fg.b, rowMouse.containsMouse || row.cursorOn ? 0.07 : 0)
      border.width: row.cursorOn ? 1 : 0
      border.color: Qt.rgba(root.fg.r, root.fg.g, root.fg.b, 0.3)
      Behavior on color { ColorAnimation { duration: 110 } }
    }
    Rectangle {
      visible: row.current
      width: Style.space(3)
      height: parent.height - Style.space(14)
      anchors.verticalCenter: parent.verticalCenter
      radius: width / 2
      color: Color.accent
    }

    MouseArea {
      id: rowMouse
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: if (row.current && root.status === "playing") root.svc.toggle(); else root.svc.play(row.s.id)
    }

    Cover {
      id: rowCover
      x: Style.space(8)
      anchors.verticalCenter: parent.verticalCenter
      width: Style.space(42)
      height: width
      source: root.art(row.s.logo)
      stationRef: row.s
      radiusPx: Style.space(5)

      // Hover/playing overlay
      Rectangle {
        anchors.fill: parent
        radius: Style.space(5)
        visible: rowMouse.containsMouse || row.current
        color: Qt.rgba(0, 0, 0, 0.45)
        Text {
          visible: rowMouse.containsMouse && !(row.current && root.status === "playing")
          anchors.centerIn: parent
          text: root.gPlay
          color: "#ffffff"
          font.family: root.fontFamily
          font.pixelSize: Style.font.display
        }
        Viz {
          visible: row.current && !(rowMouse.containsMouse && root.status !== "playing")
          anchors.centerIn: parent
          width: parent.width * 0.55
          height: parent.height * 0.5
          count: 4
          bands: root.svc ? root.svc.bands : []
          color: "#ffffff"
          gap: 2
          idle: root.status !== "playing"
        }
      }
    }

    Column {
      anchors.left: rowCover.right
      anchors.leftMargin: Style.space(10)
      anchors.right: side.left
      anchors.rightMargin: Style.space(8)
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.space(1)

      Row {
        width: parent.width
        spacing: Style.space(6)
        Text {
          id: nameText
          textFormat: Text.PlainText
          text: row.s.name || ""
          width: Math.min(implicitWidth, parent.width - netTag.width - Style.space(6))
          elide: Text.ElideRight
          color: row.current ? Color.accent : root.fg
          font.family: root.fontFamily
          font.pixelSize: Style.font.body
          font.bold: true
        }
        Text {
          id: netTag
          visible: root.filter === "all" || root.filter === "fav" || root.query !== ""
          anchors.baseline: nameText.baseline
          text: root.net(row.s.net).short
          color: root.netColor(row.s.net)
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          font.bold: true
        }
      }
      Text {
        width: parent.width
        textFormat: Text.PlainText
        text: row.s.genre ? row.s.genre : row.s.desc
        elide: Text.ElideRight
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }
      Text {
        visible: !!row.s.now
        width: parent.width
        textFormat: Text.PlainText
        text: row.s.now ? (row.s.now.show ? root.gLive + " " : root.gNote + " ") + root.songLine(row.s.now) : ""
        elide: Text.ElideRight
        color: root.fg
        opacity: 0.7
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }
    }

    Row {
      id: side
      anchors.right: parent.right
      anchors.rightMargin: Style.space(4)
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.space(4)
      Text {
        visible: row.s.listeners > 0
        anchors.verticalCenter: parent.verticalCenter
        text: root.gPeople + " " + root.compact(row.s.listeners)
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }
      PanelActionButton {
        anchors.verticalCenter: parent.verticalCenter
        iconText: row.fav ? root.gStar : root.gStarO
        tooltipText: row.fav ? "Remove from favorites" : "Add to favorites"
        foreground: row.fav ? Color.accent : root.dim
        hoverColor: Color.accent
        fontSize: Style.font.heading
        onClicked: root.svc.favorite(row.s.id, !row.fav)
      }
    }
  }

  component SongRow: Item {
    id: sr
    property var song: ({})
    property bool showAgo: false
    property bool likedList: false
    readonly property bool isLiked: likedList || !!song.liked
    implicitHeight: Style.space(46)

    Rectangle {
      anchors.fill: parent
      radius: Style.cornerRadius
      color: Qt.rgba(root.fg.r, root.fg.g, root.fg.b, srMouse.containsMouse ? 0.07 : 0)
    }
    MouseArea {
      id: srMouse
      anchors.fill: parent
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: root.svc.send("search", { key: sr.song.key })
    }

    Cover {
      id: srCover
      x: Style.space(6)
      anchors.verticalCenter: parent.verticalCenter
      width: Style.space(36)
      height: width
      source: root.art(sr.song.artLocal)
      stationRef: root.stationOf(sr.song.station) || { net: sr.song.net, name: sr.song.stationName || "" }
      radiusPx: Style.space(4)
    }

    Column {
      anchors.left: srCover.right
      anchors.leftMargin: Style.space(10)
      anchors.right: srButtons.left
      anchors.rightMargin: Style.space(6)
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.space(1)
      Text {
        width: parent.width
        textFormat: Text.PlainText
        text: sr.song.title || ""
        elide: Text.ElideRight
        color: root.fg
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        font.bold: true
      }
      Text {
        width: parent.width
        textFormat: Text.PlainText
        text: [sr.song.artist, sr.song.stationName, sr.showAgo ? root.ago(sr.song.ts) : (sr.song.ts ? Qt.formatDate(new Date(sr.song.ts * 1000), "MMM d") : "")]
          .filter(function(x) { return !!x }).join("  ·  ")
        elide: Text.ElideRight
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
      }
    }

    Row {
      id: srButtons
      anchors.right: parent.right
      anchors.rightMargin: Style.space(2)
      anchors.verticalCenter: parent.verticalCenter
      spacing: 0
      PanelActionButton {
        iconText: root.gCopy
        tooltipText: "Copy"
        foreground: root.dim
        fontSize: Style.font.body
        onClicked: root.svc.send("copy", { key: sr.song.key })
      }
      PanelActionButton {
        iconText: sr.isLiked ? root.gHeart : root.gHeartO
        tooltipText: sr.isLiked ? "Unlike" : "Like"
        foreground: sr.isLiked ? root.love : root.dim
        hoverColor: root.love
        fontSize: Style.font.body
        onClicked: sr.likedList ? root.svc.send("unlike", { key: sr.song.key }) : root.svc.like(sr.song.key)
      }
    }
  }

  component SettingToggle: Toggle {
    property string key: ""
    width: parent ? parent.width : 0
    foreground: root.fg
    fontFamily: root.fontFamily
    checked: root.config[key] !== false
    onClicked: if (root.svc) root.svc.setConfig(key, !checked)
  }

  component SettingRow: Item {
    id: setRow
    property string label: ""
    default property alias content: holder.data
    width: parent ? parent.width : 0
    implicitHeight: Math.max(lbl.implicitHeight, holder.childrenRect.height)
    Text {
      id: lbl
      anchors.left: parent.left
      anchors.verticalCenter: parent.verticalCenter
      text: setRow.label
      color: root.fg
      font.family: root.fontFamily
      font.pixelSize: Style.font.body
    }
    Item {
      id: holder
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      width: childrenRect.width
      height: childrenRect.height
    }
  }
}
