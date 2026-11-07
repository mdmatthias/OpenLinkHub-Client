"""Exercise cluster controls through the same status-zero reply as the daemon."""

import json

import httpx
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from olhclient.api.client import ApiClient
from tests.test_qml_smoke import settle, ui


def test_cluster_page(ui, qtbot, monkeypatch):
    backend, window, warnings = ui
    backend.refresh()
    cluster = backend.cluster
    members = [{"Product": "Memory", "Serial": serial} for serial in ("i2c15-3", "i2c15-1")]
    profile = {"RGBProfile": "nebula", "BrightnessSlider": 100}
    writes = []

    def handle(request):
        if request.method == "GET":
            assert request.url.path == "/api/devices/cluster"
            return httpx.Response(200, json={"status": 0, "device": {"DeviceProfile": profile,
                                  "RGBModes": ["nebula", "rain"], "Controllers": members}})
        data = json.loads(request.content)
        writes.append((request.url.path, data))
        if request.url.path == "/api/color":
            profile["RGBProfile"] = data["profile"]
        else:
            profile["BrightnessSlider"] = data["brightness"]
        return httpx.Response(200, json={"status": 1})

    api = ApiClient(transport=httpx.MockTransport(handle))
    monkeypatch.setattr(cluster, "api", api)
    window.setProperty("page", "cluster")
    settle(qtbot)
    assert window.property("title") == "RGB Cluster — OpenLinkHub"
    assert cluster.data["members"] == members
    slider = window.findChild(type(window.contentItem()), "clusterBrightness")
    point = slider.mapToScene(QPointF(slider.width() / 2, slider.height() / 2))
    QTest.mouseClick(window, Qt.LeftButton, pos=point.toPoint())
    cluster.setEffect("rain")
    settle(qtbot)
    assert writes == [
        ("/api/brightness/gradual", {"deviceId": "cluster", "brightness": 50}),
        ("/api/color", {"deviceId": "cluster", "channelId": 0, "profile": "rain"}),
    ]
    assert cluster.data["effect"] == "rain"
    assert warnings == []
    api.close()
