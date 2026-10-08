# El aparato por dentro (hardware)

Datos del teclado del taller (VID:PID `1189:8890`), leídos de la placa y del USB.

## La placa

| | |
|---|---|
| Serigrafía | `ANXIN-K6-VT1-LED-V01` — **impresa en espejo** (parece un error de fabricación: el mismo texto se lee al revés) |
| MCU | **WCH CH552G** (lote `405845D48`), encapsulado SOP-16 |
| Pasivos | resistencias y condensadores SMD (0603/0805) |
| Conector | USB-C |
| SW2 | **pads presentes y sin soldar** |
| LEDs | **pistas y pads presentes, sin LED soldado** (en la cara inferior) |

Lecturas del USB (sin abrir la caja): USB 1.1 full speed, 100 mA, sin ningún
string (ni fabricante, ni producto, ni número de serie), 4 interfaces HID:
teclado (boot, EP1 IN 64 B), canal de configuración (EP2 OUT 64 B, informe 64 B
con report id 3), teclado/Consumer (EP3 IN 4 B) y ratón (EP2 IN 4 B).
El VID `0x1189` figura a nombre de Acer en la base de datos de USB: el
fabricante usa un VID prestado, como es habitual en estos clones.

## Qué implica el CH552G

* **Núcleo 8051** con USB nativo. El firmware que habla este protocolo es 8051
  (SDCC o Keil), no ARM: útil saberlo si algún día se reescribe el firmware.
* **16 KB de flash de código + 128 B de DataFlash** (la "EEPROM" interna) y
  arranque por ROM con **bootloader USB**.
* La configuración de las teclas **no puede estar en la flash de código** (esa
  se reescribe entera al grabar). Tiene que estar en la **DataFlash de 128 B**:
  de ahí que sobreviva al desenchufe y que el canal HID solo la pueda escribir
  (el firmware no expone lectura por USB en ejecución: las lecturas por el pipe
  de control devuelven siempre un byte fijo `0xAA`).
* La serigrafía dice **`-LED-`**: esta familia de placas tiene una variante con
  LEDs, pero **esta unidad no los trae montados**. El firmware acepta el comando
  de LED (el CLI lo escribe), pero en este teclado no se ve nada. Para esta
  unidad la página de LED de la app no aporta nada.
* **SW2 sin soldar**: en estas placas es el botón de **ISP/bootloader**
  (o de reset). Los pads están ahí pero sin pulsador.

## Entrar en el bootloader (y poder LEER de verdad)

El CH552 trae en ROM un bootloader que **sí permite leer**: al entrar, el chip se
presenta como un dispositivo USB distinto, `4348:55e0` (WinChipHead).

El truco es **P3.6** (que en el CH552 es **UDP = D+ del USB**) a nivel alto en
el momento del arranque: es el pin de ISP de fábrica. Hay dos formas de
conseguirlo:

1. **Puentear los pads del SW2** (con una pinza o un destornillador fino) y
   enchufar el USB con el puente hecho. En placas hermanas de esta misma familia
   el pad a puentear es la resistencia de *pull-up* sin montar (en otra placa de
   3 teclas con CH552G es la **R12** y así lo documenta el proyecto
   [`eccherda/ch552g_mini_keyboard`](https://github.com/eccherda/ch552g_mini_keyboard),
   que hace exactamente esto).
2. **P3.6 a 3V3 con una resistencia de 10 kΩ** (o un hilo al V33) mientras se
   alimenta la placa. El pin está en el CH552G SOP-16 junto a la línea de datos
   del USB; sirve cualquier punto del net de D+.

Si el SW2 resultara ser un botón de *reset* (RST a GND), el camino alternativo es
**P1.5 a GND** (el ISP Tool de WCH permite mover el pin de arranque a P1.5).

Ojo: P3.6 comparte pin con D+, así que puentear "a lo bruto" hay que hacerlo con
el teclado **desenchufado** y soltarlo después; el bootloader ya ha arrancado y
no necesita la señal.

Si sale bien, en Linux aparece `4348:55e0 WinChipHead` en `lsusb`. Para salir,
desenchufar y volver a enchufar sin puentear nada.

## Qué se puede leer y qué no

| zona | tamaño | ¿legible? |
|---|---|---|
| DataFlash (configuración del teclado) | 128 B | **sí**, con las herramientas ISP |
| Flash de código (firmware del fabricante) | 16 KB | depende del **bootloader**: con el 2.31 y anteriores se puede volcar; con el 2.40+ el fabricante capó la lectura del código |

Herramientas: **`wchisp`** (Rust, binario ya compilado en su página de releases;
lo mejor para nosotros porque no hay que instalar nada del sistema más allá de
libusb), `isp55e0` (C, volcado con `--data-dump`) y `ch55xtool` (Python). Todas
hablan con el `4348:55e0` y vuelcan la DataFlash.

El CH552 entra en el soporte de `wchisp` (`CH552`: "works but might be buggy"
según su README) y el volcado de EEPROM que ofrece **es** la DataFlash.

**Aviso**: leer es inofensivo, pero conviene no tocar "erase"/"flash" en estas
herramientas sin haber guardado antes el volcado original. La configuración del
teclado se puede restaurar siempre con este programa.

## Experimento pendiente: dónde y cómo se guarda cada tecla

Con el volcado de la DataFlash se puede **documentar la codificación real**:

1. Volcar la DataFlash (estado actual).
2. Cambiar **una sola tecla** desde este programa (por ejemplo la tecla 1 a
   Ctrl+Z).
3. Volcar otra vez y comparar: los bytes que cambien son esa tecla.

Con eso sabremos el mapa exacto de la memoria interna (y si merece la pena
implementar "leer del teclado" abriendo la caja, o incluso escribir la
configuración completa por el bootloader, que sería más rápido que tecla a
tecla).

## Nota sobre el fabricante

Nada de esto cambia la auditoría del software ([`AUDITORIA-vendor.md`](AUDITORIA-vendor.md)):
la app del fabricante no es malware, simplemente es cerrada, sin firma y escribe
la flash sin verificar. Pero sí explica su cutrerío: una placa de 0,20 € con un
MCU de 8051, serigrafía en espejo y pads sin montar para abaratar costes.
