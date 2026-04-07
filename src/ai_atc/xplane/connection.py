from __future__ import annotations
import logging
import socket
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Callable
logger = logging.getLogger(__name__)
@dataclass
class DatarefSubscription:
    dataref: str
    freq_hz: int
    index: int
    callback: Callable[[float], None] | None = None
    last_value: float = 0.0
class XPlaneConnection:
    def __init__(
        self,
        host: str = "127.0.0.1",
        xplane_port: int = 49000,
        listen_port: int = 49008,
    ) -> None:
        self.host = host
        self.xplane_port = xplane_port
        self.listen_port = listen_port
        self._socket: socket.socket | None = None
        self._subscriptions: dict[int, DatarefSubscription] = {}
        self._next_index = 0
        self._running = False
        self._recv_thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._last_recv_time: float = 0.0
        self._connected = False
    @property
    def connected(self) -> bool:
        if self._last_recv_time == 0:
            return False
        return (time.time() - self._last_recv_time) < 5.0
    def connect(self) -> None:
        if self._running:
            return
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        self._socket.setblocking(False)
        self._socket.bind(("0.0.0.0", self.listen_port))
        self._running = True
        self._recv_thread = threading.Thread(
            target=self._receive_loop, daemon=True, name="xplane-recv"
        )
        self._recv_thread.start()
        logger.info(
            "X-Plane UDP connection started (send=%s:%d, listen=%d)",
            self.host,
            self.xplane_port,
            self.listen_port,
        )
    def disconnect(self) -> None:
        self._running = False
        for sub in list(self._subscriptions.values()):
            self._send_rref(sub.index, 0, sub.dataref)
        self._subscriptions.clear()
        if self._socket:
            self._socket.close()
            self._socket = None
        self._connected = False
        logger.info("X-Plane UDP connection closed.")
    def subscribe(
        self,
        dataref: str,
        freq_hz: int = 5,
        callback: Callable[[float], None] | None = None,
    ) -> int:
        with self._lock:
            idx = self._next_index
            self._next_index += 1
        sub = DatarefSubscription(
            dataref=dataref,
            freq_hz=freq_hz,
            index=idx,
            callback=callback,
        )
        self._subscriptions[idx] = sub
        self._send_rref(idx, freq_hz, dataref)
        logger.debug("Subscribed to %s at %d Hz (index=%d)", dataref, freq_hz, idx)
        return idx
    def unsubscribe(self, index: int) -> None:
        if index in self._subscriptions:
            sub = self._subscriptions.pop(index)
            self._send_rref(index, 0, sub.dataref)
            logger.debug("Unsubscribed from %s (index=%d)", sub.dataref, index)
    def get_value(self, index: int) -> float:
        if index in self._subscriptions:
            return self._subscriptions[index].last_value
        return 0.0
    def set_dataref(self, dataref: str, value: float) -> None:
        dataref_bytes = dataref.encode("utf-8")
        msg = b"DREF\x00" + struct.pack("<f", value) + dataref_bytes.ljust(500, b"\x00")
        self._send(msg)
        logger.debug("Set %s = %f", dataref, value)
    def send_command(self, command: str) -> None:
        msg = b"CMND\x00" + command.encode("utf-8") + b"\x00"
        self._send(msg)
        logger.debug("Sent command: %s", command)
    def _send_rref(self, index: int, freq: int, dataref: str) -> None:
        dataref_bytes = dataref.encode("utf-8")
        msg = b"RREF\x00" + struct.pack("<ii", freq, index) + dataref_bytes.ljust(400, b"\x00")
        self._send(msg)
    def _send(self, data: bytes) -> None:
        if self._socket:
            try:
                self._socket.sendto(data, (self.host, self.xplane_port))
            except OSError as e:
                logger.warning("Failed to send to X-Plane: %s", e)
    def _receive_loop(self) -> None:
        while self._running:
            if not self._socket:
                time.sleep(0.1)
                continue
            try:
                data, _ = self._socket.recvfrom(4096)
                self._process_packet(data)
                self._last_recv_time = time.time()
                if not self._connected:
                    self._connected = True
                    logger.info("Receiving data from X-Plane.")
            except BlockingIOError:
                time.sleep(0.01)
            except OSError:
                if self._running:
                    time.sleep(0.1)
    def _process_packet(self, data: bytes) -> None:
        header = data[:4]
        if header != b"RREF":
            return
        offset = 5
        while offset + 8 <= len(data):
            idx, value = struct.unpack_from("<if", data, offset)
            offset += 8
            if idx in self._subscriptions:
                sub = self._subscriptions[idx]
                sub.last_value = value
                if sub.callback:
                    try:
                        sub.callback(value)
                    except Exception:
                        logger.exception("Error in callback for %s", sub.dataref)