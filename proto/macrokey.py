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
                       new_mul_mouse: int = 0, delay_ms: int = 0) -> list[bytes]:
    """Tramas de 8 bytes (protocolo 0), una escritura por elemento, con el mismo
    `switch (b)` (y sus rarezas) que el original."""
    buf = build_vendor_buffer(key_type, entries, delay_ms, new_mul_mouse, report_id)
    count = max(1, buf[2])
    frames = []
    for b in range(count + 1):
        d = bytearray(8)
        d[0] = key_index
        d[1] = (key_type & 0x0F) if report_id == 0 else ((layer << 4) | (key_type & 0x0F))
        d[2] = count
        d[3] = b
        if b == 0:
            d[4], d[5] = buf[4], 0
        elif b == 1:
            d[4], d[5] = buf[4], buf[5]
        else:
            d[4], d[5] = buf[2 * b], buf[2 * b + 1]
        frames.append(bytes(d))
    return frames


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


def do_write(dev: HidrawDevice, report_id: int, data: bytes, reports: dict,
             numbered: bool, verbose: bool = True) -> int:
    out_len = reports.get(("output", report_id)) or reports.get(("output", 0)) or 8
    payload = (bytes([report_id]) if numbered else b"") + data
    payload = pad_report(payload, out_len + (1 if numbered else 0))
    n = dev.write(payload)
    if verbose:
        print(f"  -> write({dev.path}, id={report_id}, {len(payload)}B) = {n}  {payload[:16].hex(' ')}"
              + (" ..." if len(payload) > 16 else ""))
    return n


def cmd_list(_args):
    devs = enumerate_oem_devices()
    if not devs:
        print(f"No hay ningún dispositivo HID con VID 0x{VID_OEM:04x} conectado.")
        print("Conecta el teclado macro y vuelve a intentarlo (y comprueba `lsusb | grep 1189`).")
        return 1
    for d in devs:
        proto, nmm = KNOWN_PIDS.get(d.pid, (None, 0))
        print(f"/dev/{d.name}  VID:PID = {d.vid:04x}:{d.pid:04x}  interfaz USB = {d.usb_iface}  "
              f"proto={proto}  new_mul_mouse={nmm}")
        print(f"    nombre sysfs : {d.usb_name or d.sys_path}")
        print(f"    fabricante   : {d.manufacturer or '-'}   serial: {d.serial or '-'}")
        print(f"    informes     : {d.describe_reports()}")
    return 0


def _pick(args) -> HidrawDevice:
    dev = HidrawDevice(args.device if args.device.startswith("/dev/")
                       else f"/dev/{args.device}")
    if dev.vid != VID_OEM:
        print(f"AVISO: {dev.path} no es VID 0x{VID_OEM:04x} (es {dev.vid:04x})", file=sys.stderr)
    return dev


def cmd_info(args):
    dev = _pick(args)
    reps = dev.describe_reports()
    print(f"{dev.path}: {dev.vid:04x}:{dev.pid:04x}  interfaz {dev.usb_iface}  {dev.usb_name}")
    print(f"protocolo conocido: {KNOWN_PIDS.get(dev.pid)}")
    for k in sorted(reps):
        print(f"  report {k[0]:<8} id={k[1]:<3} {reps[k]} bytes de datos"
              f" (+1 de id si son numerados)")
    print("descriptor:", dev.report_descriptor.hex(" ")[:200], "...")
    return 0


def cmd_probe(args):
    """Reproduce KeyBoardVersion_Check: busca el 'report id' que acepta el aparato."""
    dev = _pick(args)
    reps = dev.describe_reports()
    print(f"{dev.path}  {dev.vid:04x}:{dev.pid:04x}  informes={reps}")
    ok = []
    zeros = bytes(8)
    for rid in (3, 0, 2):
        try:
            n = do_write(dev, rid, zeros, reps, numbered=True)
            if n > 0:
                ok.append(rid)
                print(f"  report id {rid}: ACEPTADO ({n} bytes escritos)")
            else:
                print(f"  report id {rid}: rechazado")
        except OSError as e:
            print(f"  report id {rid}: error {e}")
    if ok:
        print(f"\nReportID a usar = {ok[0]}  (si el firmware es de la familia moderna "
              f"usa los códigos multimedia estándar)")
    else:
        print("\nNingún report id aceptado: prueba a leer primero un informe de entrada, "
              "o revisa permisos/udev.")
    return 0 if ok else 1


def cmd_key(args):
    dev = _pick(args)
    reps = dev.describe_reports()
    proto, nmm = KNOWN_PIDS.get(dev.pid, (args.protocol or 1, 0))
    proto = args.protocol if args.protocol is not None else proto
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

    print(f"{dev.path}: tecla {args.key}, capa {args.layer}, "
          f"tipo {key_type}, protocolo {proto}, report id {report_id}, "
          f"new_mul_mouse {nmm}")
    if proto == 1:
        frame = build_long_frame(args.key, args.layer, key_type, entries,
                                 args.delay, nmm, report_id)
        if args.dry_run:
            print("  [dry-run] trama larga:", frame.hex(" "))
            return 0
        do_write(dev, report_id, frame, reps, numbered=True)
        print("  (protocolo 1: la trama 0xFE ya graba; no se manda AA AA)")
    else:
        if not args.dry_run:
            do_write(dev, report_id, bytes([CMD_SW_LAYER, args.layer]), reps, numbered=True)
        for f in build_short_frames(args.key, args.layer, key_type, entries,
                                    report_id, nmm, args.delay):
            if args.dry_run:
                print("  [dry-run] trama corta:", f.hex(" "))
            else:
                do_write(dev, report_id, f, reps, numbered=True)
        if not args.dry_run:
            do_write(dev, report_id, CMD_WRITE_FLASH, reps, numbered=True)
            print("  + commit AA AA")
    return 0


def cmd_led(args):
    dev = _pick(args)
    reps = dev.describe_reports()
    proto, nmm = KNOWN_PIDS.get(dev.pid, (args.protocol or 1, 0))
    proto = args.protocol if args.protocol is not None else proto
    byte = ((LED_COLORS[args.color] << 4) | (args.mode & 0x0F)) if args.mode is not None else 0
    if proto == 1:
        data = bytearray(46)
        data[0], data[1], data[2], data[3] = 0xFE, 0xB0, args.layer, TYPE_LED
        data[9] = 1                   # un par no nulo (buf[4], buf[5])
        data[10] = args.layer         # buf[4] -> reporte byte 10
        data[11] = byte               # buf[5] -> reporte byte 11
        if args.dry_run:
            print("  [dry-run] LED trama larga:", bytes(data).hex(" "))
            return 0
        do_write(dev, args.report_id, bytes(data), reps, numbered=True)
    else:
        d = bytearray(8)
        d[0], d[1], d[2] = 0xB0, (args.layer << 4) | TYPE_LED, byte
        if args.dry_run:
            print("  [dry-run] LED trama corta:", bytes(d).hex(" "))
            return 0
        do_write(dev, args.report_id, bytes([CMD_SW_LAYER, args.layer]), reps, numbered=True)
        do_write(dev, args.report_id, bytes(d), reps, numbered=True)
        do_write(dev, args.report_id, CMD_WRITE_LED, reps, numbered=True)
    print(f"LED: capa {args.layer}, modo {args.mode}, color {args.color} (byte 0x{byte:02x})")
    return 0


def cmd_commit(args):
    dev = _pick(args)
    reps = dev.describe_reports()
    do_write(dev, args.report_id, CMD_WRITE_FLASH, reps, numbered=True)
    return 0


def cmd_raw(args):
    dev = _pick(args)
    reps = dev.describe_reports()
    data = bytes.fromhex(args.bytes.replace(",", " "))
    do_write(dev, args.report_id, data, reps, numbered=True)
    print("lectura de entrada (si el aparato responde):", dev.read(16).hex(" "))
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
        f = build_led_long_frame(args.layer, LED_COLORS[args.color], args.mode)
        print(f"LED capa {args.layer}, modo {args.mode}, color {args.color}:")
        print("  trama larga:", f.hex(" "))
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
        for f in build_short_frames(index, args.layer, key_type, entries,
                                    args.report_id, nmm, args.delay):
            print("  trama corta:", f.hex(" "))
        print("commit:", CMD_WRITE_FLASH.hex(" "))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("device")
        p.add_argument("--report-id", type=int, default=3)
        p.add_argument("--protocol", type=int, choices=[0, 1], default=None)
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

    k = add("key", cmd_key)
    k.add_argument("--key", type=int, required=True, help="índice de tecla (1..24, 176=LED)")
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
