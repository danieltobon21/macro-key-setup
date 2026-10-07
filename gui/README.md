# Diseño de la interfaz y del icono

Todo lo de esta carpeta es **diseño**, no la app: la app (Rust + GUI) se
implementa a partir de esto cuando el diseño esté aprobado.

| fichero | qué es |
|---|---|
| `mockup.html` | vista previa de la interfaz, con el aparato dibujado **a escala real** (1 mm = 6 px): 100 × 60 mm, teclas de 18 × 17 mm, perilla ⌀ 20 mm |
| `hacer-icono.py` | genera `icono-macrokey.ico` con Pillow (dos variantes de dibujo: detallada 256/128/64 y simplificada 48/32/16, porque un mismo dibujo no se lee igual a 16 px que a 256) |
| `icono-macrokey.ico` | icono del ejecutable de Windows (6 tamaños: 256, 128, 64, 48, 32, 16) |
| `vistas/` | renders de referencia (`icono-vista-previa.png`, `icono-tamanos.png`, `interfaz-previa.png`) |

Regenerar:

```bash
python3 gui/hacer-icono.py                      # icono (necesita Pillow)
chromium-browser --headless=new --screenshot=gui/vistas/interfaz-previa.png \
  --window-size=1080,780 file://$PWD/gui/mockup-render.html   # render del mockup
```

El `.ico` se ensambla a mano (cabecera ICO + entradas PNG) para poder meter una
imagen distinta por tamaño: 256/128/64 usan el dibujo inclinado con brillos y
48/32/16 un dibujo recto, sólido y de alto contraste. Windows elige el tamaño
que necesita; con un único PNG reescalado el icono de la barra de tareas se ve
como un borrón.

Notas de diseño que afectan a la implementación en Rust+egui:

* **Nada de emojis** en las etiquetas: ni el navegador headless ni egui los
  dibujan igual (salían como cuadros). Los iconos, si hacen falta, se dibujan
  con vectores.
* El aparato se dibuja con las medidas reales del usuario, así que las teclas
  físicas sin leyenda se corresponden 1:1 con lo que se ve en pantalla.
* Colores: cuerpo negro con degradado, línea y tornillos plateados, y un único
  color de acento para la selección (azul `#5aa9ff` por defecto, con ámbar,
  verde y plata como alternativas).
