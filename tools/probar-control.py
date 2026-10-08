#!/usr/bin/env python3
"""¿Se puede LEER algo del canal de configuración? (tubería de control, EP0)

El endpoint de interrupción de entrada no existe en la interfaz 1, así que por
ahí no llega nada. Pero el estándar HID permite pedir informes por la tubería de
control (GET_REPORT) aunque el dispositivo no tenga interrupt IN: si el firmware
lo implementa, se puede volcar la configuración sin abrir el aparato.

Además sondea peticiones de clase/vendor habituales para ver cuáles contesta.
No escribe nada: sólo lecturas (GET_DESCRIPTOR, GET_REPORT, GET_STATUS...).

Uso:  sudo python3 tools/probar-control.py
"""
import ctypes
import fcntl
import os
import pathlib
import struct
import sys

VID = 0x1189
PID = 0x8890
IFACE = 1  # canal de configuración (mi_01)

# _IOWR('U', 0, struct usbdevfs_ctrltransfer): 24 B en 64 bits
USBDEVFS_CONTROL = 0xC0185500


class Ctrl(ctypes.Structure):
    _fields_ = [
        ("bRequestType", ctypes.c_uint8),
        ("bRequest", ctypes.c_uint8),
        ("wValue", ctypes.c_uint16),
        ("wIndex", ctypes.c_uint16),
        ("wLength", ctypes.c_uint16),
        ("timeout", ctypes.c_uint32),
        ("data", ctypes.c_void_p),
    ]


def ruta_usb() -> pathlib.Path:
    """Localiza /dev/bus/usb/BBB/DDD del aparato a partir de sysfs."""
    for dev in pathlib.Path("/sys/bus/usb/devices").glob("*"):
        try:
            if (dev / "idVendor").read_text().strip().lower() != f"{VID:04x}":
                continue
            if (dev / "idProduct").read_text().strip().lower() != f"{PID:04x}":
                continue
            bus = int((dev / "busnum").read_text())
            num = int((dev / "devnum").read_text())
            return pathlib.Path(f"/dev/bus/usb/{bus:03d}/{num:03d}")
        except (OSError, ValueError):
            continue
    raise SystemExit(f"no encuentro el aparato {VID:04x}:{PID:04x}")


def control(fd: int, tipo: int, req: int, valor: int, indice: int, largo: int,
            timeout_ms: int = 1000):
    """Devuelve (ok, bytes_o_errno, datos). El errno NO es un éxito."""
    buf = ctypes.create_string_buffer(max(largo, 1))
    pkt = Ctrl(tipo, req, valor, indice, largo, timeout_ms,
               ctypes.cast(buf, ctypes.c_void_p))
    try:
        n = fcntl.ioctl(fd, USBDEVFS_CONTROL, pkt)
        return True, n, bytes(buf.raw[:largo])
    except OSError as e:
        return False, e.errno, b""


def prueba(fd: int, etiqueta: str, tipo: int, req: int, valor: int, indice: int,
           largo: int) -> bool:
    ok, n, datos = control(fd, tipo, req, valor, indice, largo)
    if ok:
        print(f"  OK   {etiqueta:<50} {n:>3} B  {datos.hex(' ')}")
        return True
    # errno 32 = EPIPE: el aparato rechaza (STALL) esa petición -> no la implementa
    print(f"  --   {etiqueta:<50} errno {n} ({os.strerror(n)})")
    return False


def main() -> int:
    ruta = ruta_usb()
    print(f"aparato: {ruta}")
    fd = os.open(ruta, os.O_RDWR | os.O_NONBLOCK)
    try:
        # reclamar la interfaz (algunos kernels exigen el claim para GET_REPORT)
        try:
            fcntl.ioctl(fd, 0x8004550F, IFACE)   # USBDEVFS_CLAIMINTERFACE
            print(f"interfaz {IFACE} reclamada")
        except OSError as e:
            print(f"(no puedo reclamar la interfaz {IFACE}: {e})")
        print("\n== la tubería de control responde (referencia) ==")
        prueba(fd, "GET_DESCRIPTOR device (18 B)", 0x80, 0x06, 0x0100, 0, 18)
        prueba(fd, "GET_DESCRIPTOR config (9 B)", 0x80, 0x06, 0x0200, 0, 9)
        prueba(fd, "GET_DESCRIPTOR string[0] (idiomas)", 0x80, 0x06, 0x0300, 0, 4)

        print("\n== informes HID de la interfaz 1 por control ==")
        for tipo_reporte, nombre in ((1, "Input"), (2, "Output"), (3, "Feature")):
            for rid in (3, 0, 2, 1):
                prueba(fd, f"GET_REPORT {nombre} id={rid}", 0xA1, 0x01,
                       (tipo_reporte << 8) | rid, IFACE, 64)

        print("\n== otras lecturas de clase HID ==")
        prueba(fd, "GET_IDLE (interfaz 1)", 0xA1, 0x02, 0, IFACE, 1)
        prueba(fd, "GET_PROTOCOL (interfaz 1)", 0xA1, 0x03, 0, IFACE, 1)
        prueba(fd, "GET_STATUS (interfaz 1)", 0x81, 0x00, 0, IFACE, 2)
        prueba(fd, "GET_STATUS (endpoint 0x02)", 0x82, 0x00, 0, 0x02, 2)

        print("\n== peticiones vendor habituales en 'leer flash' (solo lectura) ==")
        for req in (0x90, 0x91, 0x92, 0xA0, 0xAA, 0xB0, 0xC0, 0xF0, 0xFE):
            prueba(fd, f"vendor IN req=0x{req:02x} (64 B)", 0xC0, req, 0, IFACE, 64)
    finally:
        os.close(fd)
    print("\n(si todo sale con errno, el firmware no implementa lectura: "
          "la configuración es de solo escritura)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
