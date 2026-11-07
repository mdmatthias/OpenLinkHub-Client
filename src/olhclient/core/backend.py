"""Root object exposed to QML: connection, device list and the selected device."""

from __future__ import annotations

import logging
from typing import Any, Callable

from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot

from olhclient.api.client import RECEIVER_PRODUCTS, ApiClient, ApiError
from olhclient.api.models import DeviceInfo, DeviceKind, DeviceState, ReceiverState
from olhclient.core.artwork import lit, zone_colors
from olhclient.core.gpu import GpuSession
from olhclient.core.keychron import KeychronSession
from olhclient.core.listmodel import DictListModel
from olhclient.core.cluster import Cluster
from olhclient.core.macros import MacroLibrary
from olhclient.core.receiver import ReceiverSession
from olhclient.core.session import QML_DIR, DeviceSession, file_url, kind_icon
from olhclient.core.worker import Worker
from olhclient.devices.base import DeviceModule
from olhclient.devices.registry import Registry
from olhclient.gpu.device import GpuDevice, LightingStore
from olhclient.gpu.device import connect as connect_gpu
from olhclient.gpu.fusion2 import Fusion2Gpu
from olhclient.keychron.boards import RECEIVERS
from olhclient.keychron.device import KeychronDevice, connect, read_state
from olhclient.keychron.protocol import KeychronClient

log = logging.getLogger(__name__)

DEVICE_ROLES = ("serial", "product", "name", "thumbnail", "battery")
RECEIVER_THUMBNAIL = QML_DIR / "images" / "slipstream.svg"
KIND_ORDER = list(DeviceKind)


def device_json(api: ApiClient, info: DeviceInfo) -> dict[str, Any]:
    """The device JSON, or a minimal stand-in when OpenLinkHub cannot encode the device."""
    try:
        return api.get_device(info.serial)
    except ApiError as exc:
        if exc.auth_required:
            raise
        return {"serial": info.serial, "product": info.product}


class Backend(QObject):
    connectedChanged = Signal()
    statusChanged = Signal()
    sessionChanged = Signal()
    authRequiredChanged = Signal()
    busyChanged = Signal()
    #: text, is_error
    temperatureFormLoaded = Signal("QVariantMap")
    temperatureFormFailed = Signal()
    temperatureSelected = Signal(str, "QVariantMap")
    temperatureSaved = Signal(str, int)
    temperatureDeleted = Signal(str)
    temperatureCreated = Signal(str)
    temperatureSavingChanged = Signal()
    notify = Signal(str, bool)

    def __init__(self, api: ApiClient | None, registry: Registry, *, poll_interval: float = 5.0,
                 worker: Worker | None = None,
                 keychron_scan: Callable[[], dict[str, KeychronDevice]] | None = None,
                 keychron_connect: Callable[[KeychronDevice], KeychronClient] = connect,
                 gpu_scan: Callable[[], dict[str, GpuDevice]] | None = None,
                 gpu_connect: Callable[[GpuDevice], Fusion2Gpu] = connect_gpu,
                 gpu_store: LightingStore | None = None,
                 brand: str = "OpenLinkHub",
                 parent: QObject | None = None):
        """``api`` None leaves OpenLinkHub out (OpenDeviceHub); ``keychron_scan`` finds Keychron
        keyboards (keychron.device.scan), without it there are none; ``gpu_scan`` likewise finds
        graphics cards (gpu.device.scan), once. ``brand`` names the app in the UI."""
        super().__init__(parent)
        self._temperature_saving = False
        self.api = api
        self.registry = registry
        self.worker = worker or Worker(self)
        self.worker.failed.connect(self._report_error)
        self.worker.busyChanged.connect(self.busyChanged)
        self._devices = DictListModel(DEVICE_ROLES, self)
        self._modules: dict[str, DeviceModule] = {}
        self._infos: dict[str, DeviceInfo] = {}
        # serial -> thumbnail (in the device's lighting colours when it has artwork), as last seen
        self._thumbnails: dict[str, str] = {}
        self._receivers: dict[str, str] = {}
        # Keychron keyboards, found on USB rather than through OpenLinkHub
        self._keychron_scan = keychron_scan
        self._keychron_connect = keychron_connect
        self._keychron: dict[str, KeychronDevice] = {}
        self._identified: dict[str, str] = {}  # receiver serial -> model of the keyboard behind it
        self._scanning = False
        # graphics cards, found on I2C buses
        self._gpu_scan = gpu_scan
        self._gpu_connect = gpu_connect
        self._gpu_store = gpu_store or LightingStore()
        self._gpus: dict[str, GpuDevice] = {}
        self._gpus_scanned = False
        # a Keychron keyboard or graphics card is being opened
        self._opening_direct = False
        # OpenLinkHub answered (or failed) once: until then a scan does not pick a keyboard to show,
        # so OpenLinkHub's devices come first as before
        self._polled_once = api is None
        # device list rows: OpenLinkHub devices, then receivers
        self._olh_items: list[dict[str, Any]] = []
        self._receiver_items: list[dict[str, Any]] = []
        self._brand = brand
        self._cluster = Cluster(api, self.worker, self) if api is not None else None
        if self._cluster is not None:
            self._cluster.failed.connect(self._report_error)
        self._macros = MacroLibrary(api, self.worker, self) if api is not None else None
        if self._macros is not None:
            self._macros.message.connect(self.notify)
        self._session: DeviceSession | KeychronSession | GpuSession | None = None
        self._receiver: ReceiverSession | None = None
        self._connected = False
        self._status = "Connecting…" if api is not None else "Looking for devices…"
        self._auth_required = False
        self._refreshing = False
        self._timer = QTimer(self)
        self._timer.setInterval(int(poll_interval * 1000))
        self._timer.timeout.connect(self.refresh)

    def start(self) -> None:
        self.refresh()
        self._timer.start()

    # -- polling -----------------------------------------------------------

    @Slot()
    def refresh(self) -> None:
        self._scan_gpus()
        self._scan_keychron()
        if self.api is None or self._refreshing or self._auth_required:
            return
        self._refreshing = True
        known = set(self._modules)

        def poll() -> dict[str, Any]:
            listed = self.api.list_devices()
            devices = {serial: info for serial, info in listed.items() if not info.hidden}
            receivers = {serial: info.product for serial, info in listed.items()
                         if info.hidden and info.product in RECEIVER_PRODUCTS}
            # Only new devices need their full JSON to pick a module.
            new = {serial: device_json(self.api, info) for serial, info in devices.items() if serial not in known}
            try:
                battery = self.api.battery_levels()
            except ApiError:
                battery = {}
            return {"devices": devices, "new": new, "battery": battery, "receivers": receivers}

        self.worker.submit(poll, on_done=self._polled, on_error=self._poll_failed)

    def _polled(self, result: dict[str, Any]) -> None:
        self._refreshing = False
        self._polled_once = True
        self._set_connected(True, f"Connected to {self.api.base_url}")
        self._infos = result["devices"]
        self._receivers = result["receivers"]

        for serial, device in sorted(result["new"].items(), key=lambda kv: self._order(kv[0])):
            module = self._modules[serial] = self.registry.match(device)
            state = DeviceState.from_json(device, self._infos[serial].kind)
            self._thumbnails[serial] = self._thumbnail(module, state)
            if self._session is None and self._receiver is None:
                self._open_session(serial, device)
        for gone in set(self._modules) - set(self._infos):
            del self._modules[gone]
            self._thumbnails.pop(gone, None)

        device_items = [
            {
                "serial": serial,
                "product": info.product,
                "name": self._modules[serial].name if self._modules[serial].layout.views else info.kind.title,
                "thumbnail": self._thumbnails[serial],
                "battery": result["battery"].get(serial, -1),
            }
            for serial, info in sorted(self._infos.items(), key=lambda kv: self._order(kv[0]))
            if serial in self._modules
        ]
        self._receiver_items = [
            {
                "serial": serial,
                "product": f"{product} RECEIVER",
                "name": "Slipstream receiver",
                "thumbnail": file_url(RECEIVER_THUMBNAIL),
                "battery": -1,
            }
            for serial, product in sorted(self._receivers.items())
        ]
        self._olh_items = device_items
        self._publish()

        if isinstance(self._session, (KeychronSession, GpuSession)):
            pass  # the Keychron scan looks after keyboards; a card stays
        elif self._session is not None:
            if self._session.serial in self._modules:
                self._session.reload()
            else:
                self._select_first()
        elif self._receiver is not None:
            if self._receiver.serial in self._receivers:
                self._receiver.reload()
            elif not self._receiver.may_be_restarting:  # a receiver may restart after a new polling rate
                self._select_first()
        elif self._devices.count and not self._opening_direct:  # e.g. only a receiver is connected
            self.selectDevice(self._devices.get(0)["serial"])

    def _publish(self) -> None:
        keychron_items = [
            {
                "serial": serial,
                "product": f"KEYCHRON {self._keychron_model(serial, device).upper()}",
                "name": device.board.title if device.board else "Keychron keyboard",
                "thumbnail": file_url(kind_icon(DeviceKind.KEYBOARD)),
                "battery": -1,
            }
            for serial, device in sorted(self._keychron.items())
        ]
        gpu_items = [
            {
                "serial": serial,
                "product": device.name.upper(),
                "name": DeviceKind.GPU.title,
                "thumbnail": file_url(kind_icon(DeviceKind.GPU)),
                "battery": -1,
            }
            for serial, device in sorted(self._gpus.items())
        ]
        self._devices.set_items(self._olh_items + keychron_items + gpu_items + self._receiver_items)

    # -- Keychron keyboards ----------------------------------------------------

    def _keychron_model(self, serial: str, device: KeychronDevice) -> str:
        if device.board is not None:
            return device.board.model
        return self._identified.get(serial) or RECEIVERS[device.interface.product_id]

    def _scan_keychron(self) -> None:
        if self._keychron_scan is None or self._scanning:
            return
        self._scanning = True
        self.worker.submit(self._keychron_scan, on_done=self._scanned, on_error=self._scan_failed)

    def _scanned(self, devices: dict[str, KeychronDevice]) -> None:
        self._scanning = False
        if devices != self._keychron:
            self._keychron = devices
            self._publish()
        self._report_direct()
        if isinstance(self._session, KeychronSession):
            if self._session.serial in devices:
                self._session.reload()
            else:
                self._select_first()
        elif self._polled_once and not self._olh_items:
            self._open_first_direct()

    def _report_direct(self) -> None:
        """Without OpenLinkHub, the status bar counts the keyboards and cards."""
        if self.api is None:
            count = len(self._keychron) + len(self._gpus)
            self._set_connected(True, f"{count} device{'s' if count != 1 else ''} found" if count
                                else "No devices found")

    def _open_first_direct(self) -> None:
        """Show a Keychron keyboard, else a graphics card, when nothing else is shown."""
        if self._session is None and self._receiver is None and not self._opening_direct:
            serials = sorted(self._keychron) + sorted(self._gpus)
            if serials:
                self.selectDevice(serials[0])

    def _scan_failed(self, exc: Exception) -> None:
        self._scanning = False
        log.debug("Keychron scan failed: %s", exc)

    def _open_keychron(self, device: KeychronDevice) -> None:
        connect_to = self._keychron_connect

        def open_keyboard() -> tuple[KeychronClient, Any]:
            client = connect_to(device)
            try:
                return client, read_state(client, device)
            except Exception:
                client.close()
                raise

        def opened(result: tuple[KeychronClient, Any]) -> None:
            self._opening_direct = False
            client, state = result
            if device.board is None and self._identified.get(device.serial) != state.board.model:
                self._identified[device.serial] = state.board.model
                self._publish()
            session = KeychronSession(client, self.worker, state, self)
            session.message.connect(self.notify)
            self._set_session(session)

        def failed(exc: Exception) -> None:
            self._opening_direct = False
            self._report_error(exc)

        self._opening_direct = True
        self.worker.submit(open_keyboard, on_done=opened, on_error=failed)

    # -- graphics cards ----------------------------------------------------------

    def _scan_gpus(self) -> None:
        if self._gpu_scan is None or self._gpus_scanned:
            return
        self._gpus_scanned = True  # probing writes to the I2C bus: once is enough, cards are not hot-plugged
        self.worker.submit(self._gpu_scan, on_done=self._gpus_found, on_error=self._gpu_scan_failed)

    def _gpus_found(self, devices: dict[str, GpuDevice]) -> None:
        self._gpus = devices
        self._publish()
        self._report_direct()
        if self._polled_once and not self._olh_items:
            self._open_first_direct()

    def _gpu_scan_failed(self, exc: Exception) -> None:
        log.debug("Graphics card scan failed: %s", exc)

    def _open_gpu(self, device: GpuDevice) -> None:
        connect_to = self._gpu_connect

        def opened(client: Fusion2Gpu) -> None:
            self._opening_direct = False
            session = GpuSession(client, self.worker, device, self._gpu_store, self)
            session.message.connect(self.notify)
            self._set_session(session)

        def failed(exc: Exception) -> None:
            self._opening_direct = False
            self._report_error(exc)

        self._opening_direct = True
        self.worker.submit(connect_to, device, on_done=opened, on_error=failed)

    def _order(self, serial: str) -> tuple[int, str]:
        """Devices are listed by kind (mice first), then by name."""
        info = self._infos[serial]
        return KIND_ORDER.index(info.kind), info.product.lower()

    @staticmethod
    def _thumbnail(module: DeviceModule, state: DeviceState) -> str:
        if module.layout.thumbnail is None:
            return file_url(kind_icon(state.kind))
        return file_url(lit(module.layout.thumbnail, zone_colors(state), module.missing_buttons))

    def _poll_failed(self, exc: Exception) -> None:
        self._refreshing = False
        self._polled_once = True
        self._open_first_direct()  # Keychron keyboards and cards work without OpenLinkHub
        if isinstance(exc, ApiError) and exc.auth_required:
            self._set_auth_required(True)
            self._set_connected(False, "Login required")
            return
        self._set_connected(False, exc.message if isinstance(exc, ApiError) else str(exc))

    # -- sessions ----------------------------------------------------------

    def _open_session(self, serial: str, device: dict[str, Any], macros: dict[int, str] | None = None) -> None:
        state = DeviceState.from_json(device, self._infos[serial].kind)
        session = DeviceSession(self.api, self.worker, self._modules[serial], state, macros, self)
        session.message.connect(self.notify)
        session.stateChanged.connect(lambda: self._update_thumbnail(serial, session.thumbnail))
        self._set_session(session)
        if macros is None:
            session.reload()  # also loads macro names

    def _update_thumbnail(self, serial: str, thumbnail: str) -> None:
        """Show the selected device's tile in its current lighting colours right away."""
        if self._thumbnails.get(serial) == thumbnail or serial not in self._modules:
            return
        self._thumbnails[serial] = thumbnail
        self._devices.set_items(
            {**item, "thumbnail": thumbnail} if item["serial"] == serial else item for item in self._devices.items()
        )

    def _open_receiver(self, data: dict[str, Any]) -> None:
        receiver = ReceiverSession(self.api, self.worker, ReceiverState.from_json(data), self)
        receiver.message.connect(self.notify)
        self._set_session(None, receiver)

    def _set_session(self, session: DeviceSession | KeychronSession | GpuSession | None,
                     receiver: ReceiverSession | None = None) -> None:
        """Show ``session`` (a device) or ``receiver``; at most one is selected."""
        for old in (self._session, self._receiver):
            if isinstance(old, (KeychronSession, GpuSession)):
                # on the worker: the close waits for a request in flight, up to its timeout
                self.worker.submit(old.client.close)
            if old is not None:
                old.deleteLater()
        self._session = session
        self._receiver = receiver
        self.sessionChanged.emit()

    def _select_first(self) -> None:
        self._set_session(None)
        if self._devices.count:
            self.selectDevice(self._devices.get(0)["serial"])

    @Slot(str)
    def selectDevice(self, serial: str) -> None:
        if serial == self.selectedSerial:
            return
        if serial in self._receivers:
            self.worker.submit(self.api.get_receiver, serial, on_done=self._open_receiver)
            return
        if serial in self._keychron:
            self._open_keychron(self._keychron[serial])
            return
        if serial in self._gpus:
            self._open_gpu(self._gpus[serial])
            return
        if serial not in self._modules:
            return

        info = self._infos[serial]

        def fetch() -> tuple[dict[str, Any], dict[int, str]]:
            return device_json(self.api, info), self.api.macros()

        self.worker.submit(fetch, on_done=lambda r: self._open_session(serial, *r))

    # -- auth --------------------------------------------------------------

    @Slot(str, str)
    def login(self, username: str, password: str) -> None:
        def done(_: Any) -> None:
            self._set_auth_required(False)
            self.notify.emit("Logged in", False)
            self.refresh()

        self.worker.submit(self.api.login, username, password, on_done=done)

    # -- helpers -----------------------------------------------------------

    def _report_error(self, exc: Exception) -> None:
        self.notify.emit(getattr(exc, "message", None) or str(exc), True)

    def _set_connected(self, connected: bool, status: str) -> None:
        if connected != self._connected:
            self._connected = connected
            self.connectedChanged.emit()
        if status != self._status:
            self._status = status
            self.statusChanged.emit()

    def _set_auth_required(self, value: bool) -> None:
        if value != self._auth_required:
            self._auth_required = value
            self.authRequiredChanged.emit()

    # -- QML API -----------------------------------------------------------

    @Property("QVariant", constant=True)
    def cluster(self):
        return self._cluster

    @Slot()
    def loadTemperatureForm(self) -> None:
        def failed(exc):
            self.temperatureFormFailed.emit()
            self._report_error(exc)

        self.worker.submit(self.api.temperature_form, on_done=self.temperatureFormLoaded.emit,
                           on_error=failed, owner=self)

    @Property(bool, notify=temperatureSavingChanged)
    def temperatureSaving(self):
        return self._temperature_saving

    @Slot(str)
    def selectTemperatureProfile(self, name):
        self.worker.submit(self.api.temperature_profile, name,
                           on_done=lambda data: self.temperatureSelected.emit(name, data),
                           on_error=self._report_error, owner=self)

    def _temperature_write(self, method, args, done):
        if self._temperature_saving:
            return
        self._temperature_saving = True
        self.temperatureSavingChanged.emit()

        def finish():
            self._temperature_saving = False
            self.temperatureSavingChanged.emit()

        def success(_):
            finish()
            done()

        def failed(exc):
            finish()
            self._report_error(exc)

        self.worker.submit(method, *args, on_done=success, on_error=failed, owner=self)

    @Slot("QVariantMap")
    def createTemperatureProfile(self, payload):
        name = payload["profile"]

        def done():
            if isinstance(self._session, DeviceSession):
                fans = self._session.controller("fans")
                if fans:
                    fans.add_profile(name)
            self.temperatureCreated.emit(name)
            self.notify.emit(f"Temperature profile {name} created", False)

        self._temperature_write(self.api.create_temperature_profile, (payload,), done)

    def _saved_temperature(self, name, kind):
        self.temperatureSaved.emit(name, kind)
        self.notify.emit(f"Temperature profile {name} saved", False)

    @Slot(str, int, "QVariantList")
    def saveTemperatureCurve(self, name, kind, points):
        self._temperature_write(self.api.save_temperature_curve, (name, kind, points),
                                lambda: self._saved_temperature(name, kind))

    @Slot(str, "QVariantMap")
    def saveTemperatureRanges(self, name, ranges):
        self._temperature_write(self.api.save_temperature_ranges, (name, ranges),
                                lambda: self._saved_temperature(name, -1))

    @Slot(str)
    def deleteTemperatureProfile(self, name):
        def done():
            if isinstance(self._session, DeviceSession):
                fans = self._session.controller("fans")
                if fans:
                    fans.remove_profile(name)
            self.temperatureDeleted.emit(name)
            self.notify.emit(f"Temperature profile {name} deleted", False)

        self._temperature_write(self.api.delete_temperature_profile, (name,), done)

    @Property(QObject, constant=True)
    def devices(self) -> DictListModel:
        return self._devices

    # QVariant, not QObject: None (no OpenLinkHub) would reach QML as an invalid object.
    @Property("QVariant", constant=True)
    def macros(self) -> MacroLibrary | None:
        return self._macros

    @Property(bool, constant=True)
    def openLinkHub(self) -> bool:
        """Whether this app drives devices through OpenLinkHub (not OpenDeviceHub)."""
        return self.api is not None

    @Property(str, constant=True)
    def brand(self) -> str:
        return self._brand

    @Property(QObject, notify=sessionChanged)
    def session(self) -> DeviceSession | KeychronSession | GpuSession | None:
        return self._session

    @Property(QObject, notify=sessionChanged)
    def receiver(self) -> ReceiverSession | None:
        return self._receiver

    @Property(str, notify=sessionChanged)
    def selectedSerial(self) -> str:
        current = self._session or self._receiver
        return current.serial if current is not None else ""

    @Property(bool, notify=connectedChanged)
    def connected(self) -> bool:
        return self._connected

    @Property(str, notify=statusChanged)
    def status(self) -> str:
        return self._status

    @Property(bool, notify=authRequiredChanged)
    def authRequired(self) -> bool:
        return self._auth_required

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self.worker.busy

    @Property(str, constant=True)
    def serverUrl(self) -> str:
        return self.api.base_url if self.api is not None else ""
