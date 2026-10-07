#!/usr/bin/env python3
"""Genera el icono del configurador del teclado macro con el lenguaje visual de la
familia Tobon (TobonFrames / TobonMouse / TobonVNC):

  * squircle plano (sin degradados ni sombras), radio ~23.5 % del ancho,
  * contorno claro grueso y uniforme (~5.5-7 % del ancho),
  * un único acento sólido naranja,
  * esquinas redondeadas, espacio negativo generoso,
  * arte simplificado para 16/24/32 px.

Paleta idéntica a `tobonframes.ico` / `tobonmouse.ico` (constantes de
`tightvnc/tools/make-appicon.py`):
    fondo #181A1F · trazo claro #ECEEF2 · acento naranja #FF5A1F

Motivo: el pad (contorno claro) con sus 6 teclas y **la perilla en naranja**,
que es lo que lo distingue de un teclado normal. Se dibuja en 4x y se reduce.

El .ico se ensambla a mano (cabecera ICO + una entrada PNG por tamaño) para que
16/24/32 lleven su propio dibujo simplificado: con el `save(sizes=...)` de
Pillow, todos los tamaños salen reescalando la imagen grande y el arte `micro()`
no llega nunca al fichero.

Uso:
    python3 gui/hacer-icono.py
    python3 gui/hacer-icono.py --preview-big /tmp/variantes.png
"""
import argparse
import struct
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

BASE = (24, 26, 31)        # #181A1F
LIGHT = (236, 238, 242)    # #ECEEF2
ACCENT = (255, 90, 31)     # #FF5A1F

SIZES = [256, 128, 64, 48, 32, 24, 16]
VARIANTE_TIRA = "V2"
SS = 4                     # supersampling
AQUI = Path(__file__).resolve().parent


def squircle(size, radius_ratio=0.235, color=BASE):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle((0, 0, size - 1, size - 1),
                                          radius=int(size * radius_ratio), fill=color)
    return img


def pad(d, size, *, small, teclas_macizas=False, perilla_dentro=True):
    """Cuerpo del pad con 6 teclas y la perilla. Devuelve la caja del cuerpo.

    El cuerpo es apaisado (el aparato real es 100 × 60 mm), así que el icono
    mantiene margen arriba y abajo: respira como los de la familia.
    """
    s = size
    bw = int(s * (0.76 if not small else 0.82))
    bh = int(bw * 0.60)
    x0, y0 = (s - bw) // 2, (s - bh) // 2
    stroke = max(2, int(s * (0.050 if not small else 0.070)))
    d.rounded_rectangle((x0, y0, x0 + bw, y0 + bh), radius=int(bh * 0.30),
                        outline=LIGHT, width=stroke)

    # 6 teclas en 2 filas × 3 columnas
    kw = int(bw * 0.175)
    kh = int(kw * 1.02)
    gx = int(kw * 0.16)
    gy = int(kh * 0.20)
    kx = x0 + int(bw * 0.075)
    ky = y0 + (bh - (2 * kh + gy)) // 2
    for fila in range(2):
        for col in range(3):
            a = kx + col * (kw + gx)
            b = ky + fila * (kh + gy)
            if teclas_macizas or small:
                d.rounded_rectangle((a, b, a + kw, b + kh), radius=int(kw * 0.24),
                                    fill=LIGHT)
            else:
                d.rounded_rectangle((a, b, a + kw, b + kh), radius=int(kw * 0.24),
                                    outline=LIGHT, width=max(2, int(stroke * 0.55)))

    # la perilla: el único elemento en acento
    r = int(bh * 0.40)
    cx = x0 + bw - int(bw * 0.125)
    cy = (y0 + bh // 2) if perilla_dentro else (y0 + bh + int(bh * 0.12))
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=ACCENT)
    if not small and perilla_dentro:                 # muesca indicadora
        rr = int(r * 0.32)
        d.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=BASE)
    return (x0, y0, x0 + bw, y0 + bh)


def micro(size):
    """16 px: solo el cuerpo y la perilla, trazo grueso y sin detalles."""
    img = squircle(size)
    d = ImageDraw.Draw(img)
    stroke = max(2, int(size * 0.115))
    bw = int(size * 0.84)
    bh = int(bw * 0.58)
    x0, y0 = (size - bw) // 2, (size - bh) // 2
    d.rounded_rectangle((x0, y0, x0 + bw, y0 + bh), radius=int(bh * 0.26),
                        outline=LIGHT, width=stroke)
    r = int(bh * 0.44)
    cx, cy = x0 + bw - int(bw * 0.15), y0 + bh // 2
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=ACCENT)
    return img


def icon(variant, size, *, small):
    img = squircle(size)
    d = ImageDraw.Draw(img)
    if variant == "V1":            # teclas huecas + perilla naranja dentro
        pad(d, size, small=small)
    elif variant == "V2":          # teclas claras macizas + perilla dentro
        pad(d, size, small=small, teclas_macizas=True)
    elif variant == "V3":          # perilla como insignia en la esquina
        caja = pad(d, size, small=small, perilla_dentro=False)
        # el pad se desplaza arriba y la perilla se separa abajo a la derecha
        r = int((caja[2] - caja[0]) * 0.19)
        cx, cy = caja[2] - int(size * 0.02), caja[3] + int(size * 0.10)
        halo = max(2, int(r * 0.30))
        d.ellipse((cx - r - halo, cy - r - halo, cx + r + halo, cy + r + halo), fill=BASE)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=ACCENT)
    else:
        raise ValueError(variant)
    return img


def sizes_for(variant):
    """Cada tamaño, dibujado en 4x y reducido. Arte simplificado por debajo de 48."""
    out = {}
    for s in SIZES:
        if s <= 16:
            out[s] = micro(s * SS).resize((s, s), Image.LANCZOS)
        else:
            out[s] = icon(variant, s * SS, small=(s <= 32)).resize((s, s), Image.LANCZOS)
    return out


def ico_multitamano(por_tamano, path):
    """Ensambla el .ico con una entrada PNG distinta por tamaño."""
    entradas, payloads, offset = [], [], 6 + 16 * len(por_tamano)
    for tam in SIZES:
        buf = BytesIO()
        por_tamano[tam].convert("RGBA").save(buf, format="PNG", optimize=True)
        datos = buf.getvalue()
        ancho = 0 if tam >= 256 else tam
        entradas.append(struct.pack("<BBBBHHII", ancho, ancho, 0, 0, 1, 32,
                                    len(datos), offset))
        payloads.append(datos)
        offset += len(datos)
    Path(path).write_bytes(struct.pack("<HHH", 0, 1, len(entradas))
                           + b"".join(entradas) + b"".join(payloads))


def tira(tamanos, zoom=6, bg=(228, 231, 236)):
    """Tira de tamaños al zoom indicado, con los píxeles a la vista (NEAREST)."""
    ic = sizes_for(VARIANTE_TIRA)
    h = max(t * zoom for t in tamanos)
    img = Image.new("RGB", (sum(t * zoom + 16 for t in tamanos) + 16, h + 32), bg)
    x = 16
    for t in tamanos:
        z = ic[t].resize((t * zoom, t * zoom), Image.NEAREST).convert("RGB")
        img.paste(z, (x, 16 + (h - z.size[1])))
        x += t * zoom + 16
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(AQUI / "icono-macrokey.ico"))
    ap.add_argument("--variante", default="V2")
    ap.add_argument("--preview-big", default=str(AQUI / "vistas" / "icono-variantes.png"))
    ap.add_argument("--preview-small", default=str(AQUI / "vistas" / "icono-tamanos.png"))
    ap.add_argument("--preview", default=str(AQUI / "vistas" / "icono-vista-previa.png"))
    args = ap.parse_args()

    for p in (args.out, args.preview_big, args.preview_small, args.preview):
        Path(p).parent.mkdir(parents=True, exist_ok=True)

    ico_multitamano(sizes_for(args.variante), args.out)
    print(f"escrito {args.out} (variante {args.variante}) tamaños {SIZES}")

    hoja = Image.new("RGB", (3 * 276 + 20, 296), (228, 231, 236))
    for i, v in enumerate(("V1", "V2", "V3")):
        hoja.paste(icon(v, 1024, small=False).resize((256, 256), Image.LANCZOS).convert("RGB"),
                   (20 + i * 276, 20))
    hoja.save(args.preview_big)
    tira((32, 24, 16), zoom=6).save(args.preview_small)
    sizes_for(args.variante)[256].convert("RGB").save(args.preview)
    print("vistas:", args.preview_big, "|", args.preview_small, "|", args.preview)


if __name__ == "__main__":
    main()
