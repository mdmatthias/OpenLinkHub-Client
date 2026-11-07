import QtQuick
import QtQuick.Layouts
import "../theme"

Rectangle {
    id: root
    property var backend
    property var updater: null
    property string page: "devices"
    signal pageSelected(string page)
    implicitHeight: 40
    color: Theme.topBar

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 14
        anchors.rightMargin: 14
        spacing: 26

        Row {
            spacing: 8
            Image {
                source: "../icons/app.svg"
                sourceSize: Qt.size(22, 22)
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                text: root.backend ? root.backend.brand : ""
                color: Theme.text
                font.pixelSize: Theme.fontLarge
                font.bold: true
                anchors.verticalCenter: parent.verticalCenter
            }
        }
        Repeater {
            model: root.backend && root.backend.openLinkHub
                   ? [{ page: "devices", title: "DEVICES" }, { page: "macros", title: "MACROS" },
                      { page: "profiles", title: "PROFILES" }, { page: "cluster", title: "RGB CLUSTER" }]
                   : [{ page: "devices", title: "DEVICES" }]
            Text {
                id: tab
                required property var modelData
                readonly property bool current: root.page === modelData.page
                text: modelData.title
                color: current || tabArea.containsMouse ? Theme.accent : Theme.textDim
                font.pixelSize: Theme.fontNormal
                Rectangle {
                    anchors.top: parent.bottom
                    anchors.topMargin: 6
                    width: parent.width
                    height: 2
                    color: Theme.accent
                    visible: tab.current
                }
                MouseArea {
                    id: tabArea
                    anchors.fill: parent
                    anchors.margins: -6
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.pageSelected(tab.modelData.page)
                }
            }
        }
        Item { Layout.fillWidth: true }
        Text {
            visible: root.updater !== null && root.updater.updateAvailable
            text: root.updater ? "Update " + root.updater.latestVersion + " available" : ""
            color: Theme.accent
            font.pixelSize: Theme.fontSmall
            font.underline: updateArea.containsMouse
            MouseArea {
                id: updateArea
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.updater.open()
            }
        }
        Row {
            visible: root.backend !== null && root.backend.openLinkHub
            spacing: 8
            Rectangle {
                width: 8
                height: 8
                radius: 4
                anchors.verticalCenter: parent.verticalCenter
                color: root.backend && root.backend.connected ? Theme.success : Theme.danger
            }
            Text {
                text: root.backend ? root.backend.serverUrl : ""
                color: Theme.textDim
                font.pixelSize: Theme.fontSmall
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }
}
