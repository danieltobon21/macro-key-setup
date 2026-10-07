# Diseño de la interfaz y del icono

Todo lo de esta carpeta es **diseño**, no la app: la app (Rust + GUI) se implementa a
partir de esto cuando el diseño esté aprobado.

**Paleta: la de la casa para programas abiertos** (skill `tobon-app-identity`):

| papel | valor |
|---|---|
| fondo / grafito | `#181A1F` |
| trazo y texto claro | `#ECEEF2` |
| acento (único) | `#FF5A1F` |
| superficies derivadas | panel `#1C1F26`, línea `#2C313B`, gris de texto `#9AA2B1` |

Los programas bajo la marca TobonDigital o para DPI LAB / Catalyst van con *sus* colores
de marca, no con estos.

| fichero | qué es |
|---|---|
| `mockup.html` | vista previa de la interfaz, con el aparato dibujado **a escala real** (1 mm = 6 px): 100 × 60 mm, teclas de 18 × 17 mm, perilla ⌀ 20 mm |
| `hacer-icono.py` | genera `icono-macrokey.ico` con el lenguaje visual de la familia Tobon (squircle plano, contorno claro grueso, un único acento naranja), partiendo de `tightvnc/tools/make-appicon.py` |
| `icono-macrokey.ico` | icono del ejecutable: 7 tamaños (256, 128, 64, 48, 32, 24, 16) |
| `vistas/` | renders de referencia: variantes del icono, tira de tamaños con los píxeles a la vista, el icono sobre fondo claro y oscuro, y la interfaz |

Regenerar:

```bash
python3 gui/hacer-icono.py --variante V2      # icono (necesita Pillow)
# render del mockup, para revisarlo antes de enseñarlo
chromium-browser --headless=new --disable-gpu --no-sandbox --hide-scrollbars \
  --screenshot=gui/vistas/interfaz-previa.png --window-size=1080,800 \
  file://$PWD/gui/mockup-render.html
```

Detalles que costaron:

* **Motivo del icono (variante V2)**: las 6 teclas macizas en claro y **la perilla en
  naranja**. Con las teclas solo perfiladas (V1) el icono es más débil a tamaño pequeño, y
  con la perilla como insignia fuera del cuerpo (V3) deja de leerse como perilla.
* **El `.ico` se ensambla a mano** (cabecera + una entrada PNG por tamaño): con el
  `save(sizes=[...])` de Pillow todos los tamaños salen reescalando la imagen grande, así
  que el dibujo `micro()` de 16 px nunca llega al fichero.
* **Nada de emojis** en las etiquetas: ni el navegador headless ni egui los dibujan igual
  (salían como cuadros). Los iconos de la interfaz, si hacen falta, se dibujan con vectores.
* El aparato se dibuja con las medidas reales que dio el usuario, para que las teclas
  físicas (que vienen en negro, sin leyenda) se correspondan 1:1 con la pantalla.
