#!/usr/bin/env python3
"""Prueba de control para saber si el canal de configuración es legible.

Si GET_REPORT funciona en este aparato, tiene que responder en las interfaces
que SÍ tienen endpoint de entrada (0 = teclado, 3 = ratón). Eso distingue dos
cosas que se ven igual en un volcado suelto:

* el firmware no implementa GET_REPORT en ninguna interfaz  -> 0xaa/EPIPE en todas,
* sólo el canal de configuración no tiene informes legibles -> el teclado y el
  ratón responden y la interfaz 1 no.

Uso:  sudo python3 tools/probar-lectura.py
"""
import ctypes
import fcntl
import os
import pathlib
import sys
import time

VID, PID = 0x1189, 0x8890
USBDEVFS_CONTROL = 0xC0185500


class Ctrl(ctypes.Structure):
    _fields_ = [("bRequestType", ctypes.c_uint8), ("bRequest", ctypes.c_uint8),
                ("wValue", ctypes.c_uint16), ("wIndex", ctypes.c_uint16),
                ("wLength", ctypes.c_uint16), ("timeout", ctypes.c_uint32),
                ("data", ctypes.c_void_p)]


def ruta_usb() -> pathlib.Path:
    for dev in pathlib.Path("/sys/bus/usb/devices").glob("*"):
        try:
            if (dev / "idVendor").read_text().strip().lower() != f"{VID:04x}":
                continue
            if (dev / "idProduct").read_text().strip().lower() != f"{PID:04x}":
                continue
            return pathlib.Path(
                f"/dev/bus/usb/{int((dev / 'busnum').read_text()):03d}"
                f"/{int((dev / 'devnum').read_text()):03d}")
        except (OSError, ValueError):
            continue
    raise SystemExit("no encuentro el aparato")


def pedir(fd, tipo, req, valor, indice, largo, intentos=3):
    """(ok, n_o_errno, datos) con reintentos: el aparato a veces contesta STALL."""
    ultimo = None
    for i in range(intentos):
        buf = ctypes.create_string_buffer(max(largo, 1))
        pkt = Ctrl(tipo, req, valor, indice, largo, 1500,
                   ctypes.cast(buf, ctypes.c_void_p))
        try:
            n = fcntl.ioctl(fd, USBDEVFS_CONTROL, pkt)
            return True, n, bytes(buf.raw[:largo])
        except OSError as e:
            ultimo = (False, e.errno, b"")
            time.sleep(0.15)
    return ultimo


PRUEBAS = [
    # ---- control: las interfaces con endpoint de entrada deben responder ----
    ("int0 teclado  GET_REPORT Input id0 (8 B)", 0xA1, 0x01, 0x0100, 0, 8),
    ("int0 teclado  GET_REPORT Input id1 (8 B)", 0xA1, 0x01, 0x0101, 0, 8),
    ("int3 raton    GET_REPORT Input id0 (4 B)", 0xA1, 0x01, 0x0100, 3, 4),
    ("int2 consumer GET_REPORT Input id2 (2 B)", 0xA1, 0x01, 0x0102, 2, 2),
    # ---- el canal de configuración (interfaz 1) ----
    ("int1 config   GET_REPORT Input id3 (64 B)", 0xA1, 0x01, 0x0103, 1, 64),
    ("int1 config   GET_REPORT Input id3 (8 B)", 0xA1, 0x01, 0x0103, 1, 8),
    ("int1 config   GET_REPORT Input id3 (1 B)", 0xA1, 0x01, 0x0103, 1, 1),
    ("int1 config   GET_REPORT Feature id3 (64 B)", 0xA1, 0x01, 0x0303, 1, 64),
    ("int1 config   GET_REPORT Feature id3 (8 B)", 0xA1, 0x01, 0x0303, 1, 8),
    ("int1 config   GET_REPORT Feature id0 (8 B)", 0xA1, 0x01, 0x0300, 1, 8),
    ("int1 config   GET_REPORT Output id3 (8 B)", 0xA1, 0x01, 0x0203, 1, 8),
]


def main() -> int:
    ruta = ruta_usb()
    print(f"aparato: {ruta}\n")
    fd = os.open(ruta, os.O_RDWR | os.O_NONBLOCK)
    try:
        for etiqueta, tipo, req, valor, indice, largo in PRUEBAS:
            ok, n, datos = pedir(fd, tipo, req, valor, indice, largo)
            if ok:
                print(f"  OK  {etiqueta:<44} {n:>3} B  {datos[:16].hex(' ')}")
            else:
                print(f"  --  {etiqueta:<44} errno {n} ({os.strerror(n)})")
        # ¿cambia el valor entre lecturas? (informes vivos del teclado)
        print("\n  teclado, 4 lecturas seguidas (debería cambiar si lees informes vivos):")
        for _ in range(4):
            ok, n, datos = pedir(fd, 0xA1, 0x01, 0x0100, 0, 8, intentos=1)
            print("   ", datos.hex(" ") if ok else f"errno {n}")
            time.sleep(0.4)
    finally:
        os.close(fd)
    return 0


if __name__ == "__main__":
    sys.exit(main())
