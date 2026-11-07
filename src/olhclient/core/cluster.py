"""Controls and member devices of the OpenLinkHub RGB cluster."""

from PySide6.QtCore import QObject, Property, Signal, Slot


class Cluster(QObject):
    changed = Signal()
    failed = Signal(object)

    def __init__(self, api, worker, parent):
        super().__init__(parent)
        self.api = api
        self.worker = worker
        self._busy = False
        self._data = {}

    @Property(bool, notify=changed)
    def busy(self):
        return self._busy

    @Property("QVariantMap", notify=changed)
    def data(self):
        return self._data

    def _refresh(self, write=None, *args):
        if self._busy:
            return
        self._busy = True
        self.changed.emit()

        def fetch():
            if write is not None:
                write("cluster", *args)
            device = self.api.get_device("cluster")
            profile = device["DeviceProfile"]
            return {
                "brightness": profile["BrightnessSlider"],
                "effect": profile["RGBProfile"],
                "modes": device.get("RGBModes") or [],
                "members": device.get("Controllers") or [],
            }

        def done(data):
            self._data = data
            self._busy = False
            self.changed.emit()

        def failed(exc):
            done({})
            self.failed.emit(exc)

        self.worker.submit(fetch, on_done=done, on_error=failed, owner=self)

    @Slot()
    def reload(self):
        self._refresh()

    @Slot(int)
    def setBrightness(self, value):
        if 0 <= value <= 100 and value != self._data.get("brightness"):
            self._refresh(self.api.set_brightness, value)

    @Slot(str)
    def setEffect(self, effect):
        if effect in self._data.get("modes", []) and effect != self._data.get("effect"):
            self._refresh(self.api.set_rgb_effect, effect, 0)
