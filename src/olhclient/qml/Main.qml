import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "theme"
import "components"
import "layout"

ApplicationWindow {
    id: window
    required property var backend
    property string defaultUsername: ""
    // core/updater.py; null when the client runs without one (tests)
    property var updater: null

    readonly property var session: backend.session
    // A Slipstream receiver is selected instead of a mouse.
    readonly property var receiver: backend.receiver
    property string featureId: ""
    property string page: "devices"
    readonly property var feature: {
        if (!session)
            return null
        for (const f of session.features)
            if (f.id === featureId)
                return f
        return session.features.length ? session.features[0] : null
    }

    // Feature panels are (re)created together with their controller so a panel
    // never sees the controller of another feature.
    function loadFeature() {
        if (!session || !feature) {
            listLoader.source = ""
            editorLoader.source = ""
            return
        }
        const props = { session: session, controller: session.controller(feature.id) }
        listLoader.setSource(feature.listQml, props)
        editorLoader.setSource(feature.editorQml, props)
    }
    onFeatureChanged: loadFeature()

    width: 1320
    height: 840
    minimumWidth: 1120
    minimumHeight: 700
    visible: true
    title: page === "macros" ? "Macros — " + backend.brand
        : page === "cluster" ? "RGB Cluster — " + backend.brand
        : page === "profiles" ? "Profiles — " + backend.brand
        : session ? session.product + " — " + backend.brand
        : receiver ? receiver.product + " — " + backend.brand : backend.brand
    color: Theme.window

    header: TopBar {
        backend: window.backend
        updater: window.updater
        page: window.page
        onPageSelected: page => window.page = page
    }
    footer: StatusBar { backend: window.backend }

    Connections {
        target: window.backend
        function onNotify(text, isError) { toast.show(text, isError) }
    }

    RowLayout {
        anchors.fill: parent
        anchors.margins: Theme.gap
        spacing: Theme.gap
        visible: window.page === "devices"
        enabled: window.session !== null || window.receiver !== null

        // -- left column ---------------------------------------------------
        ColumnLayout {
            visible: window.receiver === null
            Layout.preferredWidth: 310
            Layout.maximumWidth: 310
            Layout.fillHeight: true
            spacing: Theme.gap

            ProfilesPanel {
                Layout.fillWidth: true
                visible: window.session !== null && window.session.profiles.length > 0
                session: window.session
            }

            Panel {
                Layout.fillWidth: true
                Layout.fillHeight: true
                title: window.feature ? window.feature.title : "Actions"
                icon: window.feature ? Qt.resolvedUrl("icons/" + window.feature.id + ".svg") : ""
                highlighted: true

                Loader {
                    id: listLoader
                    anchors.fill: parent
                }
                Text {
                    anchors.fill: parent
                    anchors.margins: 16
                    visible: window.session !== null && window.session.features.length === 0
                    text: "The client has no settings for this device yet. Use \u201cOpen in OpenLinkHub\u201d to change it there."
                    color: Theme.textDim
                    font.pixelSize: Theme.fontNormal
                    wrapMode: Text.WordWrap
                }
            }

            LibraryPanel {
                Layout.fillWidth: true
                features: window.session ? window.session.features : []
                currentId: window.feature ? window.feature.id : ""
                onActivated: id => window.featureId = id
            }
        }

        // -- right column --------------------------------------------------
        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            DevicesStrip {
                Layout.fillWidth: true
                backend: window.backend
            }

            ReceiverView {
                Layout.fillWidth: true
                Layout.fillHeight: true
                visible: window.receiver !== null
                receiver: window.receiver
                backend: window.backend
            }

            // Devices without artwork get a compact header and more room for the editor.
            DeviceHeader {
                visible: window.receiver === null && window.session !== null && !window.session.hasArtwork
                         && !window.session.hasKeyboardLayout
                Layout.fillWidth: true
                session: window.session
            }

            KeyboardView {
                visible: window.receiver === null && window.session !== null && window.session.hasKeyboardLayout
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: 220
                Layout.preferredHeight: 320
                session: window.session
                onKeyActivated: window.featureId = "keyboard_keys"
            }

            DeviceView {
                visible: window.receiver === null && (window.session === null || window.session.hasArtwork)
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: 300
                Layout.preferredHeight: 420
                session: window.session
                onButtonActivated: window.featureId = "key_remap"
            }

            Rectangle {
                visible: window.receiver === null
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.minimumHeight: 280
                Layout.preferredHeight: 330
                color: Theme.panelAlt

                Loader {
                    id: editorLoader
                    anchors.fill: parent
                }
            }
        }
    }

    Loader {
        anchors.fill: parent
        anchors.margins: Theme.gap
        active: window.page === "macros" && window.backend.openLinkHub
        sourceComponent: MacrosView { library: window.backend.macros }
    }

    Loader {
        anchors.fill: parent
        anchors.margins: Theme.gap
        active: window.page === "profiles" && window.backend.openLinkHub && window.backend.connected
                && !window.backend.authRequired
        sourceComponent: TemperatureProfilesView { backend: window.backend }
    }

    Loader {
        anchors.fill: parent
        anchors.margins: Theme.gap
        active: window.page === "cluster" && window.backend.openLinkHub && window.backend.connected
                && !window.backend.authRequired
        sourceComponent: ClusterView { cluster: window.backend.cluster }
    }

    // -- empty / error states ------------------------------------------------
    Rectangle {
        anchors.fill: parent
        visible: !window.backend.authRequired && (window.page !== "devices" ? !window.backend.connected
                 : window.session === null && window.receiver === null)
        color: Qt.rgba(0.08, 0.08, 0.08, 0.92)
        Column {
            anchors.centerIn: parent
            spacing: 10
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: !window.backend.openLinkHub
                    ? (window.backend.devices.count === 0 ? "No devices found" : "Loading device…")
                    : !window.backend.connected ? "Cannot reach OpenLinkHub"
                    : window.backend.devices.count === 0 ? "No devices found" : "Loading device…"
                color: Theme.text
                font.pixelSize: Theme.fontHeader + 3
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: !window.backend.openLinkHub
                    ? "Connect a supported Keychron keyboard by cable or its 2.4 GHz receiver;\nthe list refreshes automatically."
                    : window.backend.connected ? "Connect a device; the list refreshes automatically."
                    : window.backend.status + "\nRetrying every few seconds."
                horizontalAlignment: Text.AlignHCenter
                color: Theme.textDim
                font.pixelSize: Theme.fontNormal
            }
        }
    }

    LoginDialog {
        anchors.centerIn: parent
        visible: window.backend.authRequired
        username: window.defaultUsername
        onLogin: (user, password) => window.backend.login(user, password)
    }

    UpdateDialog {
        anchors.centerIn: parent
        updater: window.updater
    }

    Toast {
        id: toast
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 18
    }
}
