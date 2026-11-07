import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../theme"
import "../components"

RowLayout {
    id: root
    required property var cluster
    readonly property var state: cluster ? cluster.data : ({})
    readonly property bool loaded: state.brightness !== undefined
    spacing: Theme.gap
    Component.onCompleted: cluster.reload()

    Panel {
        title: "RGB Cluster"
        highlighted: true
        Layout.preferredWidth: 310
        Layout.maximumWidth: 310
        Layout.fillHeight: true
        ColumnLayout {
            anchors.top: parent.top
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.margins: 16
            spacing: 10
            visible: root.loaded
            enabled: root.cluster && !root.cluster.busy
            RowLayout {
                Layout.fillWidth: true
                Text { text: "Brightness"; color: Theme.text }
                Item { Layout.fillWidth: true }
                Text { text: Math.round(slider.value) + "%"; color: Theme.accent }
            }
            DarkSlider {
                id: slider
                objectName: "clusterBrightness"
                Layout.fillWidth: true
                from: 0
                to: 100
                stepSize: 1
                live: false
                value: root.state.brightness ?? 0
                onMoved: if (!pressed) root.cluster.setBrightness(Math.round(value))
                onPressedChanged: if (!pressed && root.loaded) root.cluster.setBrightness(Math.round(value))
            }
            Text { text: "RGB effect"; color: Theme.text }
            DarkComboBox {
                Layout.fillWidth: true
                model: (root.state.modes || []).map(mode => ({value: mode, text: mode}))
                currentIndex: (root.state.modes || []).indexOf(root.state.effect)
                onActivated: root.cluster.setEffect(currentValue)
            }
        }
        AccentButton {
            anchors.centerIn: parent
            visible: !root.loaded && root.cluster && !root.cluster.busy
            text: "Retry loading cluster"
            onClicked: root.cluster.reload()
        }
    }

    Panel {
        title: "Cluster devices"
        highlighted: true
        Layout.fillWidth: true
        Layout.fillHeight: true
        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 16
            spacing: 0
            RowLayout {
                Layout.fillWidth: true
                Layout.preferredHeight: 32
                Text { Layout.preferredWidth: table.width * 0.32; text: "Device"; color: Theme.textDim }
                Text { Layout.fillWidth: true; text: "Device serial"; color: Theme.textDim }
                Text { Layout.preferredWidth: table.width * 0.2; text: "RGB"; color: Theme.textDim }
            }
            ListView {
                id: table
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                model: root.state.members || []
                ScrollBar.vertical: ScrollBar {}
                delegate: RowLayout {
                    required property var modelData
                    width: table.width
                    height: 36
                    Text { Layout.preferredWidth: table.width * 0.32; text: modelData.Product; color: Theme.text; elide: Text.ElideRight }
                    Text { Layout.fillWidth: true; text: modelData.Serial; color: Theme.text; elide: Text.ElideRight }
                    Text { Layout.preferredWidth: table.width * 0.2; text: root.state.effect || ""; color: Theme.accent; elide: Text.ElideRight }
                }
                Text {
                    anchors.centerIn: parent
                    visible: root.loaded && table.count === 0
                    text: "No devices in the RGB cluster"
                    color: Theme.textDim
                }
            }
        }
    }
}
