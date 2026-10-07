#!/usr/bin/env python3
"""Compara, byte a byte, las tramas del prototipo Python y de la app Rust.

Las dos construyen las tramas sin abrir el aparato (`frames` / `key --dry-run`),
así que sirve como prueba de regresión del protocolo reconstruido.

Uso:  python3 tools/comparar-tramas.py
"""
import re
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PY = ["python3", "proto/macrokey.py", "frames", "--protocol", "0", "--report-id", "3"]
RS = ["./rust/target/release/macrokey", "key", "--protocol", "0", "--report-id", "3",
      "--dry-run"]

CASOS = [
    ("tecla 1 Ctrl+C", ["--key", "1", "--codes", "C", "--mods", "ctrl"]),
    ("tecla 2 Ctrl+V", ["--key", "2", "--codes", "V", "--mods", "ctrl"]),
    ("tecla 3 Ctrl+X", ["--key", "3", "--codes", "X", "--mods", "ctrl"]),
    ("tecla 4 Esc", ["--key", "4", "--codes", "ESC"]),
    ("secuencia HOLA", ["--key", "1", "--codes", "H,O,L,A"]),
    ("Ctrl+Shift+S", ["--key", "1", "--codes", "S", "--mods", "ctrl+shift"]),
    ("Alt+F4", ["--key", "1", "--codes", "F4", "--mods", "alt"]),
    ("ratón central", ["--key", "5", "--mouse", "middle"]),
    ("ratón derecho", ["--key", "6", "--mouse", "right"]),
    ("ratón izquierdo", ["--key", "5", "--mouse", "left"]),
    ("rueda arriba", ["--key", "5", "--mouse", "wheelup"]),
    ("rueda abajo", ["--key", "5", "--mouse", "wheeldown"]),
    ("Ctrl+rueda arriba", ["--key", "5", "--mouse", "wheelup", "--mods", "ctrl"]),
    ("perilla <- vol-", ["--key", "knob-left", "--media", "voldown"]),
    ("perilla pulsar play", ["--key", "knob-push", "--media", "play"]),
    ("perilla -> vol+", ["--key", "knob-right", "--media", "volup"]),
    ("mute", ["--key", "knob-push", "--media", "mute"]),
    ("siguiente", ["--key", "knob-right", "--media", "next"]),
    ("borrar (clear)", ["--key", "7", "--clear"]),
    ("dos teclas + retardo 250", ["--key", "1", "--codes", "A,B", "--delay", "250"]),
]

# Línea con tramas: en Python "  trama corta: aa bb", en Rust "… -> aa bb".
RE_HEX = re.compile(r"((?:[0-9a-f]{2}(?: |$))+)$")
CLAVES = ("trama", "commit", "grabar", "capa")


def tramas(salida: str) -> list[str]:
    out = []
    for ln in salida.splitlines():
        if not any(k in ln.lower() for k in CLAVES):
            continue
        m = RE_HEX.search(ln.strip())
        if m:
            out.append(m.group(1).strip())
    return out


def correr(cmd: list[str]) -> tuple[list[str], str]:
    p = subprocess.run(cmd, cwd=RAIZ, capture_output=True, text=True)
    return tramas(p.stdout + p.stderr), p.stdout + p.stderr


def main() -> int:
    fallos = 0
    for nombre, args in CASOS:
        a, sa = correr(PY + args)
        b, sb = correr(RS + args)
        if not a:
            print(f"  ??  {nombre}: el prototipo Python no produjo tramas")
            print("      " + (sa.strip().splitlines() or ["(sin salida)"])[-1])
            fallos += 1
            continue
        if not b:
            print(f"  ??  {nombre}: la app Rust no produjo tramas")
            print("      " + (sb.strip().splitlines() or ["(sin salida)"])[-1])
            fallos += 1
            continue
        if a == b:
            print(f"  OK  {nombre}  ({len(a)} tramas)")
        else:
            print(f"  XX  {nombre}: DIFIEREN")
            for i in range(max(len(a), len(b))):
                x = a[i] if i < len(a) else "—"
                y = b[i] if i < len(b) else "—"
                marca = "" if x == y else "   <-- "
                print(f"        {i}: py={x:<26} rs={y}{marca}")
            fallos += 1
    print()
    print(f"{len(CASOS) - fallos}/{len(CASOS)} casos idénticos byte a byte")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
