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
| (capturas) | las capturas de la aplicación viven en `docs/img/`, las usa el README |

Regenerar el icono:

```bash
python3 gui/hacer-icono.py --variante V2      # necesita Pillow
```

Y las capturas de la app, sin pantalla (útil en un servidor):

```bash
LIBGL_ALWAYS_SOFTWARE=1 xvfb-run -a --server-args="-screen 0 1400x900x24" \
  bash -c './rust/target/release/macrokey gui & APP=$!; sleep 13; \
           import -window root docs/img/app-es.png; kill $APP'
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
