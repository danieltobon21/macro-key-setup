#!/usr/bin/env python3
"""
macrokey.py — prototipo de ingeniería inversa para el teclado macro "MINI KeyBoard"
(VID 0x1189). Sin dependencias externas: habla directamente con /dev/hidraw
usando solo la stdlib y lee el descriptor de informes desde /sys.

Uso:
  sudo python3 macrokey.py list                 # enumera dispositivos HID 0x1189
  sudo python3 macrokey.py info  <hidrawN>      # descriptor, report IDs y tamaños
  sudo python3 macrokey.py probe <hidrawN>      # ¿qué 'report ID'/canal acepta? (versión FW)
  sudo python3 macrokey.py key   <hidrawN> --key 1 --codes A --mods ctrl+shift
  sudo python3 macrokey.py key   <hidrawN> --key 1 --mouse left
  sudo python3 macrokey.py key   <hidrawN> --key 1 --media play
  sudo python3 macrokey.py led   <hidrawN> --mode 2 --color blue --layer 1
  sudo python3 macrokey.py clear <hidrawN> --key 1            # deja la tecla sin función
  sudo python3 macrokey.py commit <hidrawN>                   # AA AA (grabar teclas)
  sudo python3 macrokey.py raw    <hidrawN> --report-id 3 --bytes "aa aa 00"

Los códigos de tecla son los 'Usage ID' HID estándar (A=0x04, 1=0x1E ...);
también se aceptan los nombres de la tabla de abajo. Ver ../docs/PROTOCOL.md.

ADVERTENCIA: escribe en la flash del teclado. Primero `probe`, después una tecla
de prueba, y comprueba el resultado en la app del fabricante o en un editor de
texto. Todo lo que se envía aquí está reconstruido del binario del fabricante.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import struct
import sys
from pathlib import Path

VID_OEM = 0x1189
# PIDs reconocidos por la app del fabricante -> (protocolo, new_mul_mouse)
KNOWN_PIDS = {
    0x8890: (0, 0),  # interfaz mi_01, trama corta
    0x8830: (1, 0),
    0x8831: (1, 0),
    0x8832: (1, 0),
    0x8833: (1, 0),
    0x8834: (1, 0),
    0x8840: (1, 1),  # "New_Mul_Mouse": mapa de índices distinto
    0x87D0: (1, 0),
}

# ---------------------------------------------------------------- códigos HID

# Usage IDs de la página Keyboard/Keypad (0x07) — extraídos de BasicKeys.cs/Keytables
HID_KEYS: dict[str, int] = {
    **{chr(ord("A") + i): 0x04 + i for i in range(26)},          # A..Z
    **{str(d): 0x1E + i for i, d in enumerate("1234567890")},     # fila numérica
    "ENTER": 0x28, "ESC": 0x29, "BACKSPACE": 0x2A, "TAB": 0x2B, "SPACE": 0x2C,
    **{f"F{i}": 0x3A + i - 1 for i in range(1, 13)},              # F1..F12
    "PRINTSCREEN": 0x46, "SCROLLLOCK": 0x47, "PAUSE": 0x48,
    "INSERT": 0x49, "HOME": 0x4A, "PAGEUP": 0x4B, "DELETE": 0x4C,
    "END": 0x4D, "PAGEDOWN": 0x4E, "RIGHT": 0x4F, "LEFT": 0x50,
    "DOWN": 0x51, "UP": 0x52, "NUMLOCK": 0x53, "CAPSLOCK": 0x39,
    "MENU": 0x65,
    "MINUS": 0x2D, "EQUAL": 0x2E, "LBRACKET": 0x2F, "RBRACKET": 0x30,
    "BACKSLASH": 0x31, "SEMICOLON": 0x33, "QUOTE": 0x34, "GRAVE": 0x35,
    "COMMA": 0x36, "PERIOD": 0x37, "SLASH": 0x38,
    # teclado numérico
    **{f"KP{d}": 0x59 + i for i, d in enumerate("123456789")},
    "KP0": 0x62, "KPDOT": 0x63, "KPENTER": 0x58, "KPMINUS": 0x56,
    "KPPLUS": 0x57,
}

MODS = {"ctrl": 0x01, "lctrl": 0x01, "rctrl": 0x10,
        "shift": 0x02, "lshift": 0x02, "rshift": 0x20,
        "alt": 0x04, "lalt": 0x04, "altgr": 0x40, "ralt": 0x40,
        "win": 0x08, "super": 0x08, "lwin": 0x08, "rwin": 0x80}

# MULKey.cs — el código depende del "ReportID" detectado (versión del firmware)
MEDIA = {
    "play":     {3: 0xCD, 2: 0x04, 0: 0x40},
    "next":     {3: 0xB5, 2: 0x0A, 0: 0x01},
    "prev":     {3: 0xB6, 2: 0x0B, 0: 0x80},
    "mute":     {3: 0xE2, 2: 0x01, 0: 0x04},
    "volup":    {3: 0xE9, 2: 0x40, 0: 0x02},
    "voldown":  {3: 0xEA, 2: 0x80, 0: 0x01},
}
MOUSE_BUTTONS = {"left": 0x01, "right": 0x02, "middle": 0x04}
LED_COLORS = {"red": 1, "orange": 2, "yellow": 3, "green": 4,
              "cyan": 5, "blue": 6, "purple": 7}

TYPE_NONE, TYPE_KEY, TYPE_MEDIA, TYPE_MOUSE, TYPE_LED = 0x00, 0x01, 0x02, 0x03, 0x08
CMD_WRITE_FLASH = bytes([0xAA, 0xAA])   # Send_WriteFlash_Cmd
CMD_WRITE_LED = bytes([0xAA, 0xA1])     # Send_WriteFlashLED_Cmd
CMD_SW_LAYER = 0xA1                     # Send_SwLayer
KEY_LED_INDEX = 0xB0                    # índice pseudo-tecla del LED

# ------------------------------------------------------------------ hashidraw


class HidrawDevice:
    """Un /dev/hidrawN + la info de /sys que necesitamos."""

    def __init__(self, path: str):
        self.path = path
        self.name = Path(path).name                # hidrawN
        self.sysdir = Path("/sys/class/hidraw") / self.name
        self._read_sys()

    def _read_sys(self):
        self.uevent = {}
        try:
            for line in (self.sysdir / "device" / "uevent").read_text().splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    self.uevent[k] = v
        except OSError:
            pass
        phys = self.uevent.get("HID_PHYS", "")           # usb-0000:00:14.0-2/input1
        self.sys_path = self.uevent.get("HID_NAME", "")
        self.phys = phys
        self.input_index = None
        m = re.search(r"input(\d+)$", phys)
        if m:
            self.input_index = int(m.group(1))
        # OJO: sysdir/device es un symlink -> hay que resolverlo antes de subir por
        # el árbol de dispositivo real, si no se acaba en /sys/class/hidraw.
        base = (self.sysdir / "device").resolve()
        self.vid = self.pid = None
        self.usb_iface = None
        self.usb_name = self.serial = self.manufacturer = ""
        for up in [base, *base.parents]:
            name = up.name
            m = re.match(r"^\d+-[\d.]+:(\d+)\.(\d+)$", name)   # 1-3:1.0 -> interfaz 0
            if m and self.usb_iface is None:
                self.usb_iface = int(m.group(2))
            try:
                v = (up / "idVendor").read_text().strip()
                p = (up / "idProduct").read_text().strip()
            except OSError:
                continue
            self.vid, self.pid = int(v, 16), int(p, 16)
            for attr, field in (("product", "usb_name"), ("serial", "serial"),
                                ("manufacturer", "manufacturer")):
                f = up / attr
                if f.exists():
                    try:
                        setattr(self, field, f.read_text().strip())
                    except OSError:
                        pass
            break

    @property
    def report_descriptor(self) -> bytes:
        try:
            return (self.sysdir / "device" / "report_descriptor").read_bytes()
        except OSError:
            return b""

    def describe_reports(self) -> dict:
        """Parser mínimo de descriptor HID: devuelve informes y sus tamaños."""
        d = self.report_descriptor
        reports: dict[tuple[str, int], int] = {}
        i = 0
        report_id, rsize, rcount = 0, 0, 0
        rtype = None
        usage_page = None
        while i < len(d):
            b = d[i]
            if b == 0xFE:                      # long item
                i += 3 + d[i + 1]
                continue
            size = b & 0x03
            size = 4 if size == 3 else size
            itype = (b >> 2) & 0x03
            tag = (b >> 4) & 0x0F
            data = int.from_bytes(d[i + 1:i + 1 + size], "little") if size else 0
            i += 1 + size
            if itype == 1:                      # Global
                if tag == 0:                    # Usage Page
                    usage_page = data
                elif tag == 7:                  # Report Size (bits)
                    rsize = data
                elif tag == 8:                  # Report ID
                    report_id = data
                elif tag == 9:                  # Report Count
                    rcount = data
            elif itype == 0 and tag == 8:       # Local: Usage
                if usage_page is not None:
                    # El primer usage tras cambiar de report/main item es "el" uso
                    key = {0: "input", 1: "output", 2: "feature"}.get(rtype)
                    if key:
                        reports.setdefault((key, report_id), 0)
                        reports[(key, report_id)] = max(
                            reports[(key, report_id)], (rsize * rcount + 7) // 8
                        )
            elif itype == 0:                    # Main
                if tag in (8, 9, 11, 12) and rtype is None:  # Input/Output/Feature/EndCollection
                    rtype = {8: 0, 9: 1, 11: 2}.get(tag)
                if tag in (8, 9, 11):           # Input(8) Output(9) Feature(11)
                    name = {8: "input", 9: "output", 11: "feature"}[tag]
                    reports.setdefault((name, report_id), 0)
                    reports[(name, report_id)] = max(
                        reports[(name, report_id)], (rsize * rcount + 7) // 8
                    )
                    rtype = None
                elif tag == 12:                 # EndCollection
                    rtype = None
        return reports

    def write(self, data: bytes) -> int:
        with open(self.path, "wb", buffering=0) as fh:
            return fh.write(data)

    def read(self, length: int, timeout_ms: int = 500) -> bytes:
        import select
        with open(self.path, "rb", buffering=0) as fh:
            if select.select([fh], [], [], timeout_ms / 1000)[0]:
                return fh.read(length)
        return b""

    def get_feature(self, report_id: int, length: int) -> bytes:
        import fcntl
        HIDIOCGFEATURE = 0xC0004807  # _IOC_READ|_IOC(0,'H',0x07,64)
        buf = bytearray(length)
        buf[0] = report_id
        with open(self.path, "rb", buffering=0) as fh:
            fcntl.ioctl(fh, HIDIOCGFEATURE, buf, True)
        return bytes(buf)


def enumerate_oem_devices() -> list[HidrawDevice]:
    out = []
    for p in sorted(Path("/sys/class/hidraw").glob("hidraw*"), key=lambda x: int(x.name[6:])):
        dev = HidrawDevice(f"/dev/{p.name}")
        if dev.vid == VID_OEM:
            out.append(dev)
    return out


# ------------------------------------------------- interfaz de configuración (usbfs)
#
# El canal de configuración de estos teclados es una interfaz HID que declara
# informes de 64 bytes con Report ID (el descriptor de nuestro 0x8890 usa el 3) y
# **solo un endpoint OUT** (EP 0x02, interrupt, 64 bytes). Como no tiene endpoint
# de entrada, `usbhid` no la enlaza y NO existe /dev/hidraw para ella: hay que
# hablar con el dispositivo directamente por usbfs (/dev/bus/usb/BBB/DDD),
# reclamando la interfaz y enviando URBs de interrupción.

USBDEVFS_URB_TYPE_INTERRUPT = 1
_IOC_NONE, _IOC_WRITE, _IOC_READ = 0, 1, 2


def _ioc(direction: int, type_: str, nr: int, size: int) -> int:
    return (direction << 30) | (size << 16) | (ord(type_) << 8) | nr


USBDEVFS_SUBMITURB = _ioc(_IOC_READ, "U", 10, 56)
USBDEVFS_DISCARDURB = _ioc(_IOC_NONE, "U", 11, 0)
USBDEVFS_REAPURB = _ioc(_IOC_WRITE, "U", 12, 8)
USBDEVFS_CLAIMINTERFACE = _ioc(_IOC_READ, "U", 15, 4)
USBDEVFS_RELEASEINTERFACE = _ioc(_IOC_READ, "U", 16, 4)


class _UsbdevfsUrb(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_ubyte),
        ("endpoint", ctypes.c_ubyte),
        ("status", ctypes.c_int),
        ("flags", ctypes.c_uint),
        ("buffer", ctypes.c_void_p),
        ("buffer_length", ctypes.c_int),
        ("actual_length", ctypes.c_int),
        ("start_frame", ctypes.c_int),
        ("number_of_packets_or_stream_id", ctypes.c_int),
        ("error_count", ctypes.c_int),
        ("signr", ctypes.c_uint),
        ("usercontext", ctypes.c_void_p),
    ]


_libc = ctypes.CDLL("libc.so.6", use_errno=True)
_libc.ioctl.restype = ctypes.c_int


def _ioctl(fd: int, request: int, arg) -> int:
    """ioctl(2) vía libc, para controlar exactamente si pasamos puntero o valor."""
    res = _libc.ioctl(fd, ctypes.c_ulong(request), arg)
    if res < 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err))
    return res


class UsbfsConfig:
    """Canal de configuración por USB directo (interfaz sin /dev/hidraw)."""

    def __init__(self, bus: int, addr: int, interface: int = 1, endpoint: int = 0x02,
                 transfer_len: int = 65):
        self.bus, self.addr = bus, addr
        self.interface, self.endpoint = interface, endpoint
        self.transfer_len = transfer_len
        self.path = f"/dev/bus/usb/{bus:03d}/{addr:03d}"
        self.fd = -1

    @classmethod
    def find(cls, vid: int, pid: int, interface: int = 1) -> "UsbfsConfig | None":
        base = Path("/sys/bus/usb/devices")
        if not base.is_dir():
            return None
        for d in sorted(base.iterdir()):
            try:
                if (d / "idVendor").read_text().strip().lower() != f"{vid:04x}":
                    continue
                if (d / "idProduct").read_text().strip().lower() != f"{pid:04x}":
                    continue
                bus = int((d / "busnum").read_text())
                addr = int((d / "devnum").read_text())
                return cls(bus, addr, interface)
            except (OSError, ValueError):
                continue
        return None

    # -- ciclo de vida -------------------------------------------------
    def open(self) -> "UsbfsConfig":
        self.fd = os.open(self.path, os.O_RDWR)
        # La interfaz no la tiene ningún driver, así que se puede reclamar.
        _ioctl(self.fd, USBDEVFS_CLAIMINTERFACE, ctypes.byref(ctypes.c_uint(self.interface)))
        return self

    def close(self):
        if self.fd >= 0:
            _ioctl(self.fd, USBDEVFS_RELEASEINTERFACE,
                   ctypes.byref(ctypes.c_uint(self.interface)))
            os.close(self.fd)
            self.fd = -1

    def __enter__(self):
        return self.open() if self.fd < 0 else self

    def __exit__(self, *exc):
        self.close()

    # -- envío ---------------------------------------------------------
    def write(self, data: bytes) -> int:
        """Envía un informe por el endpoint de interrupción. Espera el URB."""
        if self.fd < 0:
            raise RuntimeError("UsbfsConfig.write() sin open()")
        payload = bytes(data[: self.transfer_len]).ljust(self.transfer_len, b"\x00")
        buf = ctypes.create_string_buffer(payload, self.transfer_len)
        urb = _UsbdevfsUrb(
            type=USBDEVFS_URB_TYPE_INTERRUPT,
            endpoint=self.endpoint,
            status=0,
            flags=0,
            buffer=ctypes.cast(buf, ctypes.c_void_p),
            buffer_length=self.transfer_len,
            actual_length=0,
            start_frame=0,
            number_of_packets_or_stream_id=0,
            error_count=0,
            signr=0,
            usercontext=None,
        )
        try:
            _ioctl(self.fd, USBDEVFS_SUBMITURB, ctypes.byref(urb))
            slot = (ctypes.c_void_p * 1)()
            _ioctl(self.fd, USBDEVFS_REAPURB, slot)
            if urb.status != 0:
                raise OSError(-urb.status, f"URB completado con error ({urb.status})")
            return urb.actual_length
        except OSError:
            # Si algo falla, cancelamos el URB pendiente para no dejar la cola sucia.
            try:
                _ioctl(self.fd, USBDEVFS_DISCARDURB, ctypes.byref(urb))
            except OSError:
                pass
            raise


def oem_usb_device(vid: int, pid: int) -> tuple[int, int] | None:
    """(bus, dirección) del dispositivo USB con ese VID:PID."""
    d = UsbfsConfig.find(vid, pid)
    return (d.bus, d.addr) if d else None


# ------------------------------------------------------------------ protocolo


def build_vendor_buffer(key_type: int, entries: list[tuple[str, bytes]],
                        delay_ms: int, new_mul_mouse: int, report_id: int) -> bytearray:
    """Replica `Data_Send_Buff` byte a byte, con las mismas posiciones que usa el
    original (cursor `KEY_Char_Num` = 5, `Key_Fun_Num` = 4):

    * teclado  -> buf[cursor] = código, buf[cursor+1] |= máscara; cursor += 2
    * multimedia -> buf[4] si (new_mul_mouse y report_id != 2), si no buf[5];
                    con report_id == 2 el código va un byte más allá
    * ratón    -> 4 bytes en buf[5..9]; la máscara va en buf[4] si new_mul_mouse,
                  si no en buf[9]
    * contador -> el original recorre pares desde buf[4] y deja el último no nulo
    """
    buf = bytearray(64)   # `Data_Send_Buff` (convención del original)
    buf[1] = key_type
    cursor = 5
    for kind, pay in entries:
        if kind == "key":
            buf[cursor] = pay[0]
            buf[cursor + 1] |= pay[1] if len(pay) > 1 else 0
            cursor += 2
        elif kind == "media":
            pos = 4 if (new_mul_mouse and report_id != 2) else 5
            if report_id == 2:
                pos += 1
            buf[pos] = pay[0]
        elif kind == "mouse":
            buf[5:9] = pay[:4]
            if len(pay) > 4 and pay[4]:                 # máscara de modificador
                if new_mul_mouse:
                    buf[4] |= pay[4]
                else:
                    buf[9] |= pay[4]
    count = 0
    for i in range(18):
        if buf[4 + 2 * i] or buf[5 + 2 * i]:
            count = i + 1
    buf[2] = count
    return buf


def build_long_frame(key_index: int, layer: int, key_type: int,
                     entries: list[tuple[str, bytes]], delay_ms: int = 0,
                     new_mul_mouse: int = 0, report_id: int = 3) -> bytes:
    """Trama de 46 bytes (protocolo 1) replicando Download_Click.

    Ojo: el original copia *literalmente* `Data_Send_Buff[4:40]` a los bytes
    10..45 del reporte, así que el primer código de una tecla acaba en el byte 11.
    """
    buf = build_vendor_buffer(key_type, entries, delay_ms, new_mul_mouse, report_id)
    d = bytearray(46)
    d[0] = 0xFE
    d[1] = key_index
    d[2] = layer
    d[3] = key_type
    # el retardo vive en `Protocol2_Sd_Buff` (otro array del original) y va a los
    # bytes 4 y 5 del reporte, NO al bloque de datos
    d[4] = delay_ms & 0xFF
    d[5] = (delay_ms >> 8) & 0xFF
    d[9] = buf[2]                 # contador de pares (Data_Send_Buff[2])
    d[10:46] = buf[4:40]
    return bytes(d)


def build_short_frames(key_index: int, layer: int, key_type: int,
                       entries: list[tuple[str, bytes]], report_id: int,
                       new_mul_mouse: int = 0, delay_ms: int = 0) -> tuple[list[bytes], bytes]:
    """Tramas de 8 bytes (protocolo 0), **replicando el `switch` por tipo** del
    original (FormMain.Download_Click, ramas de 8 bytes).

    Devuelve (tramas, comando_de_commit). El commit es `AA AA` para teclas y
    `AA A1` para el LED.

    Ojo: cada tipo usa posiciones distintas del buffer en este protocolo:
      * teclado (0/1): array[2]=nº de pares, array[3]=índice del par, array[4..5]=par
      * multimedia (2): array[2]=buf[5], array[3]=buf[6]
      * LED (8):        array[2]=buf[2]  (modo/color)
      * ratón (3):      array[2..6]=buf[5..9]
    """
    buf = build_vendor_buffer(key_type, entries, delay_ms, new_mul_mouse, report_id)
    t = key_type & 0x0F

    def frame(idx: int, extra: dict) -> bytes:
        d = bytearray(8)
        d[0] = idx
        d[1] = (key_type & 0x0F) if report_id == 0 else ((layer << 4) | (key_type & 0x0F))
        for k, v in extra.items():
            d[k] = v
        return bytes(d)

    frames: list[bytes] = []
    commit = CMD_WRITE_FLASH

    if t in (0, 1):
        count = buf[2]
        for b in range(count + 1):                    # el original itera 0..count
            if b == 0:
                a, c = buf[4], 0                      # caso 0: buf[4] y 0
            else:
                # caso n>=1: buf[2n+2], buf[2n+3]  (b=1 -> buf[4],buf[5];
                # b=2 -> buf[6],buf[7]; b=3 -> buf[8],buf[9]; ...)
                a, c = buf[2 * b + 2], buf[2 * b + 3]
            frames.append(frame(key_index, {2: count, 3: b, 4: a, 5: c}))
    elif t == 2:
        frames.append(frame(key_index, {2: buf[5], 3: buf[6]}))
    elif t == 8:
        frames.append(frame(KEY_LED_INDEX, {2: buf[2]}))
        commit = CMD_WRITE_LED
    elif t == 3:
        frames.append(frame(key_index, {2: buf[5], 3: buf[6], 4: buf[7],
                                        5: buf[8], 6: buf[9]}))
    return frames, commit


def entry_keyboard(code: int, mods: int = 0) -> tuple[str, bytes]:
    return ("key", bytes([code & 0xFF, mods & 0xFF]))


def entry_mouse(buttons: int = 0, dx: int = 0, dy: int = 0, wheel: int = 0,
                mods: int = 0) -> tuple[str, bytes]:
    return ("mouse", bytes([buttons & 0xFF, dx & 0xFF, dy & 0xFF, wheel & 0xFF]) + bytes([mods & 0xFF]))


def entry_media(code: int) -> tuple[str, bytes]:
    return ("media", bytes([code & 0xFF]))


# ----------------------------------------------------------------------- CLI


def pad_report(payload: bytes, out_len: int) -> bytes:
    """Ajusta al tamaño real del output report declarado (ID incluido)."""
    if len(payload) > out_len:
        raise SystemExit(f"trama de {len(payload)} B > output report de {out_len} B")
    return payload + bytes(out_len - len(payload))


class Link:
    """Transporte hacia el teclado.

    * `hidraw`: modelos cuyo canal de configuración SÍ aparece como /dev/hidraw.
    * `usbfs` : modelos cuyo canal es una interfaz HID con solo endpoint OUT
      (el nuestro, 0x8890/mi_01): se reclama la interfaz y se envían URBs de
      interrupción de 65 bytes = [report id] + 64 de datos.
    """

    def __init__(self, args):
        self.args = args
        self.kind: str | None = None
        self.dev: HidrawDevice | None = None
        self.cfg: UsbfsConfig | None = None
        self.reps: dict = {}
        self.out_len = 65
        self.pid: int | None = None
        self.proto = 1
        self.nmm = 0
        self._select()

    # -- selección del transporte ---------------------------------------
    def _known(self) -> tuple[int, int]:
        return KNOWN_PIDS.get(self.pid, (None, 0))  # type: ignore[arg-type]

    def _select(self):
        want = getattr(self.args, "transport", "auto")
        explicit = getattr(self.args, "device", None)

        # 1) nodo hidraw indicado a mano
        if explicit:
            dev = _pick(self.args)
            self._use_hidraw(dev, want)
            return

        devs = enumerate_oem_devices()
        pid = devs[0].pid if devs else None
        proto, nmm = KNOWN_PIDS.get(pid, (0, 0)) if pid else (1, 0)
        # La interfaz de configuración es mi_01 en los modelos de protocolo 0
        # (0x8890) y mi_00 en el resto. Si esa interfaz no está expuesta como
        # hidraw (nuestro caso: no tiene endpoint de entrada), hay que ir por USB.
        cfg_iface = 1 if proto == 0 else 0
        dev = next((d for d in devs if d.usb_iface == cfg_iface), None)
        if dev is not None and want in ("auto", "hidraw"):
            self._use_hidraw(dev, want)
            return
        if want in ("auto", "usbfs"):
            cfg = UsbfsConfig.find(VID_OEM, pid, cfg_iface) if pid else None
            if cfg is None:
                for p in KNOWN_PIDS:
                    i = 1 if KNOWN_PIDS[p][0] == 0 else 0
                    cfg = UsbfsConfig.find(VID_OEM, p, i)
                    if cfg:
                        pid = p
                        break
            if cfg is not None:
                self.kind = "usbfs"
                self.cfg = cfg
                self.pid = pid
                proto, nmm = KNOWN_PIDS[pid]
                self.proto = (self.args.protocol if
                              getattr(self.args, "protocol", None) is not None else proto)
                self.nmm = nmm
                return
        raise SystemExit(
            "No encuentro el canal de configuración del teclado (VID 0x1189). "
            "¿Está conectado? Prueba `list`.")

    def _use_hidraw(self, dev: HidrawDevice, want: str):
        self.kind = "hidraw"
        self.dev = dev
        self.pid = dev.pid
        proto, nmm = KNOWN_PIDS.get(dev.pid, (None, 0))
        self.proto = (self.args.protocol if getattr(self.args, "protocol", None) is not None
                      else (proto or 1))
        self.nmm = nmm
        self.reps = dev.describe_reports()
        self.out_len = (self.reps.get(("output", self.args.report_id))
                        or self.reps.get(("output", 0)) or 65)

    # -- ciclo de vida --------------------------------------------------
    def __enter__(self):
        if self.kind == "usbfs" and self.cfg and getattr(self.args, "dry_run", False):
            return self          # en dry-run no hace falta abrir el aparato
        if self.kind == "usbfs" and self.cfg and self.cfg.fd < 0:
            self.cfg.open()
        return self

    def __exit__(self, *exc):
        if self.kind == "usbfs" and self.cfg and self.cfg.fd >= 0:
            self.cfg.close()

    @property
    def where(self) -> str:
        if self.kind == "hidraw" and self.dev:
            return self.dev.path
        return f"{self.cfg.path} (interfaz {self.cfg.interface}, EP 0x{self.cfg.endpoint:02x})" if self.cfg else "?"

    # -- envío ----------------------------------------------------------
    def send(self, report_id: int, data: bytes, label: str = "", dry_run: bool = False) -> int:
        if dry_run:
            print(f"  [dry-run] {label}: id={report_id} {data[:20].hex(' ')}")
            return len(data)
        if self.kind == "hidraw":
            payload = pad_report(bytes([report_id]) + data, self.out_len)
            n = self.dev.write(payload)  # type: ignore[union-attr]
        else:
            payload = bytes([report_id]) + data
            n = self.cfg.write(payload)  # type: ignore[union-attr]
        print(f"  -> {label}: {n} bytes enviados  {payload[:20].hex(' ')}"
              + (" ..." if len(payload) > 20 else ""))
        return n

    def commit(self, report_id: int, cmd: bytes, dry_run: bool = False) -> int:
        name = "AA AA" if cmd == CMD_WRITE_FLASH else "AA A1"
        return self.send(report_id, cmd, f"commit {name}", dry_run)


def cmd_list(_args):
    found = False
    for d in enumerate_oem_devices():
        found = True
        proto, nmm = KNOWN_PIDS.get(d.pid, (None, 0))
        print(f"/dev/{d.name}  VID:PID = {d.vid:04x}:{d.pid:04x}  interfaz USB = {d.usb_iface}  "
              f"proto={proto}  new_mul_mouse={nmm}   informes={d.describe_reports()}")
    # interfaces USB del aparato (incluidas las que el kernel no expone como hidraw)
    for pid in KNOWN_PIDS:
        cfg = UsbfsConfig.find(VID_OEM, pid, 1)
        if cfg:
            found = True
            proto, nmm = KNOWN_PIDS[pid]
            print(f"{cfg.path}  VID:PID = {VID_OEM:04x}:{pid:04x}  interfaz de configuración = "
                  f"{cfg.interface} (EP 0x{cfg.endpoint:02x}, informes de 64 B con Report ID 3)  "
                  f"proto={proto}  new_mul_mouse={nmm}  [usa --transport usbfs]")
    if not found:
        print(f"No hay ningún dispositivo con VID 0x{VID_OEM:04x} conectado.")
        print("Conecta el teclado macro y vuelve a intentarlo (comprueba `lsusb | grep 1189`).")
        return 1
    return 0


def _pick(args) -> HidrawDevice:
    dev = HidrawDevice(args.device if args.device.startswith("/dev/")
                       else f"/dev/{args.device}")
    if dev.vid != VID_OEM:
        print(f"AVISO: {dev.path} no es VID 0x{VID_OEM:04x} (es {dev.vid:04x})", file=sys.stderr)
    return dev


def cmd_info(args):
    with Link(args) as link:
        print(f"transporte: {link.kind}   destino: {link.where}")
        print(f"VID:PID {VID_OEM:04x}:{link.pid:04x}  protocolo={link.proto}  "
              f"new_mul_mouse={link.nmm}  report id={args.report_id}")
        if link.kind == "hidraw" and link.dev:
            print(f"interfaz USB {link.dev.usb_iface}  {link.dev.usb_name}")
            for k in sorted(link.reps):
                print(f"  informe {k[0]:<8} id={k[1]:<3} {link.reps[k]} bytes de datos")
            print("descriptor:", link.dev.report_descriptor.hex(" ")[:200], "...")
        else:
            print("interfaz de configuración: HID vendor-defined (Usage Page 0xFF00), "
                  "Report ID 3, informes de 64 B, EP OUT de interrupción de 64 B")
            print("transferencia: 65 bytes = [report id] + 64 de datos")
    return 0


def cmd_probe(args):
    """Reproduce KeyBoardVersion_Check: comprueba el 'report id' que acepta el aparato."""
    with Link(args) as link:
        print(f"{link.where}: {VID_OEM:04x}:{link.pid:04x}  transporte={link.kind}")
        if link.kind == "hidraw":
            ok = []
            for rid in (3, 0, 2):
                try:
                    link.send(rid, bytes(8), f"sondeo id={rid}", args.dry_run)
                    ok.append(rid)
                except OSError as e:
                    print(f"  report id {rid}: error {e}")
            if ok:
                print(f"\nreport id a usar: {ok[0]}")
                return 0
            return 1
        # usbfs: el descriptor de la interfaz declara Report ID 3, y una escritura
        # por USB siempre se completa, así que se informa del hallazgo del descriptor
        # y se manda la trama de ceros (lo primero que hace el original).
        print("el descriptor de la interfaz de configuración declara Report ID 3 "
              "(y como fallback el original prueba 0 y 2)")
        link.send(args.report_id, bytes(8), f"sondeo id={args.report_id} (trama de ceros)",
                  args.dry_run)
        return 0


def cmd_key(args):
    with Link(args) as link:
        report_id = args.report_id
        entries: list[tuple[str, bytes]] = []
        key_type = TYPE_KEY
        if args.clear:
            key_type = TYPE_NONE
        elif args.mouse:
            key_type = TYPE_MOUSE
            wheel = 1 if args.mouse == "wheelup" else (0xFF if args.mouse == "wheeldown" else 0)
            mods = 0
            for m in (args.mods or "").split("+"):
                if m:
                    mods |= MODS[m.strip().lower()]
            entries = [entry_mouse(MOUSE_BUTTONS.get(args.mouse, 0), wheel=wheel, mods=mods)]
        elif args.media:
            key_type = TYPE_MEDIA
            entries = [entry_media(MEDIA[args.media][report_id])]
        else:
            mods = 0
            for m in (args.mods or "").split("+"):
                if m:
                    mods |= MODS[m.strip().lower()]
            entries = [entry_keyboard(HID_KEYS[c.strip().upper()], mods if i == 0 else 0)
                       for i, c in enumerate(args.codes.split(","))]

        index = resolve_key(args.key, link.nmm)
        print(f"{link.where}: tecla {index}, capa {args.layer}, tipo {key_type}, "
              f"protocolo {link.proto}, report id {report_id}, new_mul_mouse {link.nmm}")
        if link.proto == 1:
            frame = build_long_frame(index, args.layer, key_type, entries,
                                     args.delay, link.nmm, report_id)
            link.send(report_id, frame, "trama larga", args.dry_run)
            print("  (protocolo 1: la trama 0xFE ya graba; no se manda AA AA)")
        else:
            link.send(report_id, bytes([CMD_SW_LAYER, args.layer]), "cambiar capa", args.dry_run)
            frames, commit = build_short_frames(index, args.layer, key_type, entries,
                                                report_id, link.nmm, args.delay)
            for f in frames:
                link.send(report_id, f, "trama corta", args.dry_run)
            link.commit(report_id, commit, args.dry_run)
    return 0


def cmd_led(args):
    with Link(args) as link:
        byte = ((LED_COLORS[args.color] << 4) | (args.mode & 0x0F)) if args.mode is not None else 0
        if link.proto == 1:
            data = bytearray(46)
            data[0], data[1], data[2], data[3] = 0xFE, KEY_LED_INDEX, args.layer, TYPE_LED
            data[9] = 1
            data[10] = args.layer
            data[11] = byte
            link.send(args.report_id, bytes(data), "LED (trama larga)", args.dry_run)
        else:
            link.send(args.report_id, bytes([CMD_SW_LAYER, args.layer]), "cambiar capa",
                      args.dry_run)
            frames, commit = build_short_frames(KEY_LED_INDEX, args.layer, TYPE_LED, [], 
                                                args.report_id, link.nmm, 0)
            for f in frames:
                link.send(args.report_id, f, "LED (trama corta)", args.dry_run)
            link.commit(args.report_id, commit, args.dry_run)
        print(f"LED: capa {args.layer}, modo {args.mode}, color {args.color} (byte 0x{byte:02x})")
    return 0


def cmd_commit(args):
    with Link(args) as link:
        link.commit(args.report_id, CMD_WRITE_FLASH, args.dry_run)
    return 0


def cmd_raw(args):
    with Link(args) as link:
        data = bytes.fromhex(args.bytes.replace(",", " "))
        link.send(args.report_id, data, "crudo", args.dry_run)
    return 0


def binding_to_steps(b: dict, report_id: int) -> tuple[int, list[tuple[str, bytes]], int]:
    """Convierte una asignación de perfil en (tipo, elementos, retardo)."""
    delay = int(b.get("delay_ms", 0))
    if b.get("clear"):
        return TYPE_NONE, [], delay
    mods = 0
    for m in b.get("mods", []):
        mods |= MODS[str(m).strip().lower()]
    if b.get("media"):
        return TYPE_MEDIA, [entry_media(MEDIA[str(b["media"])][report_id])], delay
    if b.get("mouse"):
        action = str(b["mouse"]).lower()
        buttons = MOUSE_BUTTONS.get(action, 0)
        wheel = 1 if action == "wheelup" else (0xFF if action == "wheeldown" else 0)
        return TYPE_MOUSE, [entry_mouse(buttons, wheel=wheel, mods=mods)], delay
    codes = b.get("codes", [])
    if not codes:
        raise SystemExit(f"binding de la tecla {b.get('key')} sin codes/media/mouse/clear")
    steps = [entry_keyboard(HID_KEYS[str(c).strip().upper()], mods if i == 0 else 0)
             for i, c in enumerate(codes)]
    return TYPE_KEY, steps, delay


def cmd_apply(args):
    import tomllib
    with open(args.profile, "rb") as fh:
        prof = tomllib.load(fh)
    bindings = prof.get("binding", [])
    with Link(args) as link:
        print(f"perfil: {prof.get('name', args.profile)}  ({len(bindings)} asignaciones)  "
              f"destino: {link.where}  protocolo {link.proto}")
        led = prof.get("led")
        if led:
            layer = int(led.get("layer", 1))
            color = LED_COLORS[str(led.get("color", "green")).lower()]
            mode = int(led.get("mode", 0))
            byte = (color << 4) | (mode & 0x0F)
            link.send(args.report_id, bytes([CMD_SW_LAYER, layer]), "cambiar capa (LED)",
                      args.dry_run)
            frames, commit = build_short_frames(KEY_LED_INDEX, layer, TYPE_LED, [],
                                                args.report_id, link.nmm, 0)
            for f in frames:
                link.send(args.report_id, f, "LED", args.dry_run)
            link.commit(args.report_id, commit, args.dry_run)
            print(f"  LED capa {layer}: modo {mode}, color {led.get('color')} (0x{byte:02x})")
        for b in bindings:
            index = resolve_key(b["key"], link.nmm)
            key_type, entries, delay = binding_to_steps(b, args.report_id)
            layer = int(b.get("layer", 1))
            print(f"tecla {index} (capa {layer}): {json.dumps(b, ensure_ascii=False)}")
            if link.proto == 1:
                frame = build_long_frame(index, layer, key_type, entries, delay,
                                         link.nmm, args.report_id)
                link.send(args.report_id, frame, "trama larga", args.dry_run)
            else:
                link.send(args.report_id, bytes([CMD_SW_LAYER, layer]), "cambiar capa",
                          args.dry_run)
                frames, commit = build_short_frames(index, layer, key_type, entries,
                                                    args.report_id, link.nmm, delay)
                for f in frames:
                    link.send(args.report_id, f, "trama corta", args.dry_run)
                link.commit(args.report_id, commit, args.dry_run)
    print("perfil aplicado.")
    return 0


def resolve_key(name: str, new_mul_mouse: int = 0) -> int:
    n = str(name).strip().lower()
    if n.isdigit():
        return int(n)
    k1, kp, kr = (16, 17, 18) if new_mul_mouse else (13, 14, 15)
    return {"knob-left": k1, "knob-back": k1, "knob-push": kp, "knob-press": kp,
            "knob-right": kr, "knob-fwd": kr, "knob-forward": kr}[n]


def build_led_long_frame(layer: int, color: int, mode: int) -> bytes:
    """Trama LED del protocolo 1: buf[4]=capa, buf[5]=(color<<4)|modo."""
    d = bytearray(46)
    d[0], d[1], d[2], d[3] = 0xFE, 0xB0, layer, TYPE_LED
    d[9] = 1
    d[10] = layer
    d[11] = (color << 4) | (mode & 0x0F)
    return bytes(d)


def cmd_frames(args):
    """Construye las tramas sin dispositivo (para validar el protocolo offline)."""
    nmm = args.new_mul_mouse
    if args.led:
        if args.protocol == 1:
            f = build_led_long_frame(args.layer, LED_COLORS[args.color], args.mode)
            print(f"LED capa {args.layer}, modo {args.mode}, color {args.color}:")
            print("  trama larga:", f.hex(" "))
        else:
            frames, commit = build_short_frames(KEY_LED_INDEX, args.layer, TYPE_LED, [],
                                                args.report_id, nmm, 0)
            print(f"LED capa {args.layer}, modo {args.mode}, color {args.color} "
                  f"(protocolo 0, report id {args.report_id}):")
            print("  cambiar capa:", bytes([CMD_SW_LAYER, args.layer]).hex(" "))
            for f in frames:
                print("  trama corta:", f.hex(" "))
            print("  commit:", commit.hex(" "))
        return 0
    index = resolve_key(args.key, nmm)
    key_type = TYPE_KEY
    if args.mouse:
        key_type = TYPE_MOUSE
        wheel = 1 if args.mouse == "wheelup" else (0xFF if args.mouse == "wheeldown" else 0)
        mods = 0
        for m in (args.mods or "").split("+"):
            if m:
                mods |= MODS[m.strip().lower()]
        entries = [entry_mouse(MOUSE_BUTTONS.get(args.mouse, 0), wheel=wheel, mods=mods)]
    elif args.media:
        key_type = TYPE_MEDIA
        entries = [entry_media(MEDIA[args.media][args.report_id])]
    elif not args.codes:
        key_type = TYPE_NONE
        entries = []
    else:
        mods = 0
        for m in (args.mods or "").split("+"):
            if m:
                mods |= MODS[m.strip().lower()]
        entries = [entry_keyboard(HID_KEYS[c.strip().upper()], mods if i == 0 else 0)
                   for i, c in enumerate(args.codes.split(","))]

    print(f"tecla {index}, capa {args.layer}, tipo {key_type}, "
          f"protocolo {args.protocol}, report id {args.report_id}, new_mul_mouse {nmm}")
    if args.protocol == 1:
        f = build_long_frame(index, args.layer, key_type, entries,
                             args.delay, nmm, args.report_id)
        print("trama larga (46 B):")
        for off in range(0, len(f), 16):
            print(f"  {off:02d}: " + f[off:off + 16].hex(" "))
    else:
        print("cambiar capa:", bytes([CMD_SW_LAYER, args.layer]).hex(" "))
        frames, commit = build_short_frames(index, args.layer, key_type, entries,
                                            args.report_id, nmm, args.delay)
        for f in frames:
            print("  trama corta:", f.hex(" "))
        print("commit:", commit.hex(" "))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("device", nargs="?", default=None,
                       help="p.ej. /dev/hidraw3; si se omite, se autodetecta")
        p.add_argument("--report-id", type=int, default=3)
        p.add_argument("--protocol", type=int, choices=[0, 1], default=None)
        p.add_argument("--transport", choices=["auto", "hidraw", "usbfs"], default="auto",
                       help="auto: hidraw si el canal está expuesto, si no USB directo")
        p.add_argument("--dry-run", action="store_true", help="solo mostrar las tramas")

    def add(name, func):
        p = sub.add_parser(name)
        common(p)
        p.set_defaults(func=func)
        return p

    sub.add_parser("list").set_defaults(func=cmd_list)
    add("info", cmd_info)
    add("probe", cmd_probe)
    add("commit", cmd_commit)

    # Prueba offline: construye las tramas sin hablar con ningún aparato.
    fr = sub.add_parser("frames", help="construir y mostrar tramas (sin dispositivo)")
    fr.add_argument("--key", default="1")
    fr.add_argument("--layer", type=int, default=1)
    fr.add_argument("--codes", default="")
    fr.add_argument("--mods", default="")
    fr.add_argument("--media", choices=sorted(MEDIA))
    fr.add_argument("--mouse", choices=["left", "right", "middle", "wheelup", "wheeldown"])
    fr.add_argument("--delay", type=int, default=0)
    fr.add_argument("--protocol", type=int, choices=[0, 1], default=1)
    fr.add_argument("--report-id", type=int, default=3)
    fr.add_argument("--new-mul-mouse", type=int, choices=[0, 1], default=0)
    fr.add_argument("--led", action="store_true", help="construir la trama de LED")
    fr.add_argument("--color", choices=sorted(LED_COLORS), default="green")
    fr.add_argument("--mode", type=int, default=0, choices=range(6))
    fr.set_defaults(func=cmd_frames)

    ap_apply = add("apply", cmd_apply)
    ap_apply.add_argument("--profile", required=True, help="fichero de perfil TOML")

    k = add("key", cmd_key)
    k.add_argument("--key", required=True,
                   help="1..24, 176 (LED) o knob-left / knob-push / knob-right")
    k.add_argument("--layer", type=int, default=1, choices=[1, 2, 3])
    k.add_argument("--codes", default="", help="códigos HID separados por coma (A,B,1,F5)")
    k.add_argument("--mods", default="", help="ctrl+shift+alt+win")
    k.add_argument("--media", choices=sorted(MEDIA))
    k.add_argument("--mouse", choices=["left", "right", "middle", "wheelup", "wheeldown"])
    k.add_argument("--delay", type=int, default=0, help="ms entre elementos de la secuencia")
    k.add_argument("--clear", action="store_true", help="deja la tecla sin función")
    k.set_defaults(func=cmd_key)

    led = sub.add_parser("led")
    common(led)
    led.add_argument("--layer", type=int, default=1, choices=[1, 2, 3])
    led.add_argument("--mode", type=int, choices=range(6))
    led.add_argument("--color", choices=sorted(LED_COLORS))
    led.set_defaults(func=cmd_led)

    raw = sub.add_parser("raw")
    common(raw)
    raw.add_argument("--bytes", required=True, help="p.ej. 'aa aa 00 00'")
    raw.set_defaults(func=cmd_raw)

    args = ap.parse_args(argv)
    if os.geteuid() != 0 and args.cmd != "list":
        print("AVISO: /dev/hidraw* suele ser solo-root (0600). Usa sudo o instala la "
              "regla udev de udev/99-macrokey.rules", file=sys.stderr)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
