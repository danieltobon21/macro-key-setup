#!/usr/bin/env python3
"""Experimento 2: variantes de combinación con modificador, botones de ratón y perilla.

La tecla 4 (Escape, sin modificador) sirve de DETECTOR: si su informe llega como
`01 00 00 29` (mods=01 + ESC) es que el Ctrl se quedó pegado; si llega como
`00 00 00 29` (mods=00) es que la variante probada se limpia sola.
"""
import pathlib
import sys
from argparse import Namespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "proto"))
import macrokey as mk  # noqa: E402

PLAN = [
    # Variante A: combinación entera en el PRIMER marco (índice 0), un solo elemento.
    ("tecla 1 = Ctrl+C  variante A (todo en idx0)",
     ["01 11 01 00 01 06 00 00"]),

    # Variante B: combinación en idx0 + marco de liberación en idx1 (count=2).
    ("tecla 2 = Ctrl+V  variante B (idx0 combo + idx1 liberación)",
     ["02 11 02 00 01 19 00 00",
      "02 11 02 01 00 00 00 00"]),

    # Variante C (la actual): idx0 vacío + combo en idx1.
    ("tecla 3 = Ctrl+X  variante C (idx0 vacío + combo en idx1)",
     ["03 11 01 00 00 00 00 00",
      "03 11 01 01 01 1b 00 00"]),

    # Detector: Escape plano.
    ("tecla 4 = Esc (detector: debe salir SIN modificador)",
     ["04 11 01 00 00 00 00 00",
      "04 11 01 01 00 29 00 00"]),

    # Ratón: se dedujo [2]=rueda, [3]=x, [4]=y, [5]=botones -> probamos [5].
    ("tecla 5 = ratón botón 3 (central) en [5]  -> 05 13 00 00 00 04 ...",
     ["05 13 00 00 00 04 00 00"]),
    ("tecla 6 = ratón botón 2 (derecho) en [5]  -> 06 13 00 00 00 02 ...",
     ["06 13 00 00 00 02 00 00"]),

    # Perilla: códigos multimedia distintos y conocidos.
    ("perilla <- (13) = vol+ 0xE9", ["0d 12 e9 00 00 00 00 00"]),
    ("perilla pulsada (14) = play 0xCD", ["0e 12 cd 00 00 00 00 00"]),
    ("perilla -> (15) = vol- 0xEA", ["0f 12 ea 00 00 00 00 00"]),
]


def main(dry_run: bool) -> int:
    args = Namespace(device=None, report_id=3, protocol=0, transport="auto", dry_run=dry_run)
    with mk.Link(args) as link:
        print(f"destino: {link.where}  protocolo {link.proto}\n")
        for label, frames in PLAN:
            print(f"— {label}")
            for f in frames:
                link.send(args.report_id, bytes.fromhex(f), "trama")
            link.commit(args.report_id, mk.CMD_WRITE_FLASH)
            print()
    print("plan aplicado.")
    return 0


if __name__ == "__main__":
    sys.exit(main("--dry-run" in sys.argv))
