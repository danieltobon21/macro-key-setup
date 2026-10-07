#!/usr/bin/env python3
"""Escribe el plan de tramas de un experimento concreto (se ejecuta una vez, con root).

Cada entrada: (etiqueta, tramas a enviar, ¿commit?).
Las tramas son los 8 bytes de datos del protocolo 0 (el report id lo añade Link).
"""
import pathlib
import sys
from argparse import Namespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "proto"))
import macrokey as mk  # noqa: E402

PLAN = [
    # --- teclado: ¿basta con que el primer paso sea (0,0), o hace falta además un
    #     paso final de liberación para que no se quede el Ctrl pegado? ---
    ("tecla 1 = Ctrl+C  (idx0 reset, sin liberación final)",
     ["01 11 01 00 00 00 00 00",
      "01 11 01 01 01 06 00 00"]),
    ("tecla 2 = Ctrl+V  (idx0 reset + paso final de liberación)",
     ["02 11 02 00 00 00 00 00",
      "02 11 02 01 01 19 00 00",
      "02 11 02 02 00 00 00 00"]),
    ("tecla 3 = Ctrl+X  (igual que la 2)",
     ["03 11 02 00 00 00 00 00",
      "03 11 02 01 01 1b 00 00",
      "03 11 02 02 00 00 00 00"]),
    ("tecla 4 = Esc     (sin modificador)",
     ["04 11 01 00 00 00 00 00",
      "04 11 01 01 00 29 00 00"]),

    # --- ratón: el firmware lee la rueda de [2]; ¿dónde lee los botones? probamos [3] ---
    ("tecla 5 = ratón botón 3 (central) en [3]  -> 05 13 00 04 ...",
     ["05 13 00 04 00 00 00 00"]),
    ("tecla 6 = ratón botón 2 (derecho) en [3]  -> 06 13 00 02 ...",
     ["06 13 00 02 00 00 00 00"]),

    # --- perilla: códigos multimedia distintos para ver qué emite de verdad ---
    ("perilla <- (13) = mute 0xE2", ["0d 12 e2 00 00 00 00 00"]),
    ("perilla pulsada (14) = play 0xCD", ["0e 12 cd 00 00 00 00 00"]),
    ("perilla -> (15) = vol+ 0xE9", ["0f 12 e9 00 00 00 00 00"]),
]


def main(dry_run: bool) -> int:
    args = Namespace(device=None, report_id=3, protocol=0, transport="auto", dry_run=dry_run)
    with mk.Link(args) as link:
        print(f"destino: {link.where}  protocolo {link.proto}  report id {args.report_id}\n")
        for label, frames, *rest in PLAN:
            print(f"— {label}")
            for f in frames:
                link.send(args.report_id, bytes.fromhex(f), "trama")
            link.commit(args.report_id, mk.CMD_WRITE_FLASH)
            print()
    print("plan aplicado.")
    return 0


if __name__ == "__main__":
    sys.exit(main("--dry-run" in sys.argv))
