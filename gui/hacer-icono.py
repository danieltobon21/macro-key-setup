#!/usr/bin/env python3
"""Genera el icono del configurador del teclado macro (.ico multi-tamaño + PNG).

Dos variantes, porque un icono no se lee igual a 256 px que a 16:

* `detallado()` — con inclinación, brillos y sombra: tamaños 256/128/64.
* `simple()`    — recto, sólido y de alto contraste, sin degradados ni sombra,
                  teclas y perilla más gruesas: tamaños 48/32/16.

El .ico se ensambla a mano (formato ICO con entradas PNG) para poder meter una
imagen distinta por tamaño, que es lo que hace legible el icono en la barra de
tareas.
"""
import math
import struct

from PIL import Image, ImageDraw, ImageFilter

L = 1024
CUERPO = (9, 9, 11, 255)
CUERPO_B = (176, 182, 194, 255)
PLACA = (20, 21, 25, 255)
TECLA = (78, 78, 90, 255)
TECLA_A = (110, 110, 126, 255)
ANILLO = (150, 156, 168, 255)
PERILLA = (24, 24, 29, 255)
BLANCO = (246, 248, 251, 255)


def _cuerpo(d, x0, y0, x1, y1, radio, borde, placa):
    d.rounded_rectangle([x0, y0, x1, y1], radius=radio, fill=CUERPO, outline=borde, width=13)
    d.rounded_rectangle([x0 + 34, y0 + 34, x1 - 34, y1 - 34], radius=radio - 20,
                        fill=PLACA, outline=(90, 94, 106, 255), width=6)


def _teclas(d, kx, ky, kw, kh, gx, gy, radio, brillo):
    for fila in range(2):
        for col in range(3):
            a = kx + col * (kw + gx)
            b = ky + fila * (kh + gy)
            d.rounded_rectangle([a, b, a + kw, b + kh], radius=radio, fill=TECLA,
                                outline=(16, 16, 20, 255), width=8)
            if brillo:
                d.rounded_rectangle([a + 24, b + 18, a + kw - 24, b + 66], radius=20,
                                    fill=TECLA_A)


def _perilla(d, cx, cy, r, dientes, ancho_diente, ancho_indicador):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=ANILLO)
    d.ellipse([cx - r + 26, cy - r + 26, cx + r - 26, cy + r - 26], fill=PERILLA)
    for i in range(dientes):
        a = i * (2 * math.pi / dientes) + math.pi / dientes
        d.line([cx + math.cos(a) * (r - 34), cy + math.sin(a) * (r - 34),
                cx + math.cos(a) * (r - 82), cy + math.sin(a) * (r - 82)],
               fill=(104, 108, 120, 255), width=ancho_diente)
    d.ellipse([cx - r + 90, cy - r + 90, cx + r - 90, cy + r - 90],
              fill=(32, 32, 38, 255), outline=(74, 78, 90, 255), width=6)
    d.line([cx, cy - r + 44, cx, cy - 62], fill=BLANCO, width=ancho_indicador)


def detallado():
    img = Image.new("RGBA", (L, L), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = 60, 270, 964, 760
    _cuerpo(d, x0, y0, x1, y1, 76, CUERPO_B, PLACA)
    _teclas(d, x0 + 76, y0 + 60, 200, 180, 32, 38, 30, True)
    _perilla(d, x0 + 76 + 3 * 200 + 2 * 32 + 180, (y0 + y1) // 2, 158, 12, 13, 26)
    img = img.rotate(-8, resample=Image.BICUBIC)
    sombra = Image.new("RGBA", (L, L), (0, 0, 0, 0))
    sombra.paste((0, 0, 0, 120), (0, 0), img.split()[3])
    return Image.alpha_composite(sombra.filter(ImageFilter.GaussianBlur(24)), img)


def simple():
    """Sin inclinación, sin brillos ni sombra: sólido y con contrastes fuertes.

    Las teclas van mucho más claras que el cuerpo y con separaciones anchas, que
    es lo único que sobrevive a 16 px.
    """
    img = Image.new("RGBA", (L, L), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = 24, 214, 1000, 810
    d.rounded_rectangle([x0, y0, x1, y1], radius=90, fill=CUERPO, outline=CUERPO_B, width=20)
    _teclas(d, x0 + 74, y0 + 62, 226, 216, 44, 48, 34, False)
    _perilla(d, x0 + 74 + 3 * 226 + 2 * 44 + 214, (y0 + y1) // 2, 190, 8, 22, 34)
    return img


def ico_bytes(imagenes_por_tamano):
    """Ensambla un .ico con una imagen PNG distinta por tamaño."""
    entradas, payloads, offset = [], [], 6 + 16 * len(imagenes_por_tamano)
    for tam, im in imagenes_por_tamano:
        from io import BytesIO
        buf = BytesIO()
        im.convert("RGBA").resize((tam, tam), Image.LANCZOS).save(buf, format="PNG",
                                                                  optimize=True)
        datos = buf.getvalue()
        ancho = 0 if tam >= 256 else tam
        entradas.append(struct.pack("<BBBBHHII", ancho, ancho, 0, 0, 1, 32,
                                    len(datos), offset))
        payloads.append(datos)
        offset += len(datos)
    cabecera = struct.pack("<HHH", 0, 1, len(entradas))
    return cabecera + b"".join(entradas) + b"".join(payloads)


def mini():
    """16 px: aún más grueso y plano (teclas claras, perilla con muesca oscura)."""
    img = Image.new("RGBA", (L, L), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    x0, y0, x1, y1 = 20, 230, 1004, 794
    d.rounded_rectangle([x0, y0, x1, y1], radius=110, fill=(16, 16, 20, 255),
                        outline=(210, 216, 228, 255), width=26)
    kw, kh, gx, gy = 240, 200, 56, 56
    for fila in range(2):
        for col in range(3):
            a = x0 + 62 + col * (kw + gx)
            b = y0 + 62 + fila * (kh + gy)
            d.rounded_rectangle([a, b, a + kw, b + kh], radius=40, fill=(226, 230, 238, 255))
    cx, cy, r = x0 + 62 + 3 * kw + 2 * gx + 190, (y0 + y1) // 2, 196
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(226, 230, 238, 255))
    d.ellipse([cx - 96, cy - 96, cx + 96, cy + 96], fill=(20, 20, 25, 255))
    d.line([cx, cy - r + 30, cx, cy - 70], fill=(226, 230, 238, 255), width=46)
    return img


def main():
    g = "/home/jarvis/.hermes/cache/scratch/macrokey/gui/"
    gv = g + "vistas/"
    det, sim, miniatura = detallado(), simple(), mini()
    tabla = [(256, det), (128, det), (64, det), (48, sim), (32, sim), (16, miniatura)]
    with open(g + "icono-macrokey.ico", "wb") as fh:
        fh.write(ico_bytes(tabla))

    det.resize((256, 256), Image.LANCZOS).save(gv + "icono-vista-previa.png")
    # tira con los tamaños REALES que va a usar Windows
    x, alto = 0, 300
    tira = Image.new("RGBA", (256 + 128 + 64 + 48 + 32 + 16 + 5 * 16, alto), (250, 250, 252, 255))
    for tam, _ in tabla:
        im = {256: det, 128: det, 64: det, 48: sim, 32: sim, 16: miniatura}[tam]
        im = im.resize((tam, tam), Image.LANCZOS)
        tira.paste(im, (x, alto - tam - 20), im)
        x += tam + 16
    tira.save(gv + "icono-tamanos.png")
    print("icono: 256/128/64 detallado + 48/32 simplificado + 16 mini")


if __name__ == "__main__":
    main()
