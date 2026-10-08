//! Textos bilingües, ayuda y preferencias de la interfaz.
//!
//! Todo el texto visible sale de aquí: la app es bilingüe (castellano / inglés)
//! y el idioma se puede cambiar en caliente desde el menú *Ver → Idioma*.
//!
//! Las preferencias se guardan en un fichero de texto **junto al ejecutable**
//! (`macrokey.conf`), estilo aplicación portable: no toca el registro en Windows
//! ni `~/.config` en Linux.

use std::path::PathBuf;

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Idioma {
    Es,
    En,
}

/// Elige el texto según el idioma. Ambas versiones quedan visibles en el sitio
/// donde se usan, que es lo que hace imposible que se desincronicen.
pub fn t<'a>(es: &'a str, en: &'a str, i: Idioma) -> &'a str {
    match i {
        Idioma::Es => es,
        Idioma::En => en,
    }
}

// ------------------------------------------------------------------ preferencias

pub struct Prefs {
    pub idioma: Idioma,
    pub avanzado: bool,
}

impl Default for Prefs {
    fn default() -> Self {
        Self { idioma: Idioma::Es, avanzado: false }
    }
}

fn ruta_conf() -> PathBuf {
    // junto al ejecutable (app portable); si no se puede escribir, no pasa nada
    std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|d| d.join("macrokey.conf")))
        .unwrap_or_else(|| PathBuf::from("macrokey.conf"))
}

impl Prefs {
    pub fn cargar() -> Self {
        let mut p = Self::default();
        let Ok(texto) = std::fs::read_to_string(ruta_conf()) else {
            return p;
        };
        for linea in texto.lines() {
            let Some((clave, valor)) = linea.split_once('=') else {
                continue;
            };
            let valor = valor.trim();
            match clave.trim() {
                "idioma" => {
                    p.idioma = if valor.eq_ignore_ascii_case("en") {
                        Idioma::En
                    } else {
                        Idioma::Es
                    }
                }
                "avanzado" => p.avanzado = valor == "1" || valor.eq_ignore_ascii_case("true"),
                _ => {}
            }
        }
        p
    }

    pub fn guardar(&self) {
        let texto = format!(
            "# preferencias de macrokey\nidioma={}\navanzado={}\n",
            match self.idioma {
                Idioma::Es => "es",
                Idioma::En => "en",
            },
            if self.avanzado { 1 } else { 0 }
        );
        let _ = std::fs::write(ruta_conf(), texto);
    }
}

// ------------------------------------------------------------------ ayuda

/// Sección de la ventana de ayuda.
pub struct Seccion {
    pub titulo: &'static str,
    pub cuerpo: &'static str,
}

const AYUDA_ES: &[Seccion] = &[
    Seccion {
        titulo: "Primeros pasos",
        cuerpo: "\
1. Conecta el teclado macro por USB (no hace falta ningún instalador ni el
   software del fabricante: es un teclado HID estándar).

2. Pincha una tecla del dibujo de la izquierda para seleccionarla. El texto del
   centro de cada tecla es lo que hace ahora mismo.

3. En el panel derecho elige el TIPO de acción y complétala:
      - Teclado: el código (C, F5, ENTER, KP1…) y los modificadores (Ctrl, Shift…).
      - Ratón: un botón o la rueda (con Ctrl/Shift/Alt si quieres).
      - Multimedia: play/pausa, siguiente, anterior, silencio, volumen.
      - Secuencia: varias teclas seguidas, con retardo entre ellas.

4. «Aplicar a esta tecla» escribe sólo esa tecla; «Aplicar al teclado» escribe
   toda la configuración de una vez.

5. La configuración se guarda DENTRO del teclado: puedes desenchufarlo y usarlo
   en otro ordenador (Windows, Linux, Mac) sin volver a configurarlo.",
    },
    Seccion {
        titulo: "Acciones de ratón (Tinkercad y demás)",
        cuerpo: "\
El botón se mantiene pulsado mientras mantienes la tecla física, así que sirve
para ARRASTRAR, no sólo para hacer clic:

    botón central  ->  pan (mover la vista)
    botón derecho  ->  rotar / orbitar
    rueda          ->  zoom

En Tinkercad: el botón central te deja desplazarte y el derecho girar la pieza.
Para eso, mantén la tecla del teclado macro mientras mueves el ratón.

Si quieres «Ctrl + rueda» (zoom fino en muchas aplicaciones), pon el
modificador Ctrl en la acción de rueda.",
    },
    Seccion {
        titulo: "Cómo funciona (sin magia)",
        cuerpo: "\
El teclado se configura escribiendo unas tramas de 8 bytes en su memoria flash
por un canal de configuración propio (la interfaz HID 1, informe de 64 bytes con
el identificador 3). En Linux se escribe por /dev/hidraw o por USB directo; en
Windows por la API HID del sistema.

El formato se reconstruyó descompilando el software del fabricante y se verificó
tecla por tecla leyendo lo que el aparato emite de verdad. Todo está documentado
en el repositorio (docs/PROTOCOL.md) y hay pruebas que comparan las tramas del
programa de configuración con las del prototipo, byte a byte.

Lo que NO se puede hacer: leer la configuración guardada. El canal de
configuración no tiene endpoint de entrada y su lectura por el pipe de control
devuelve un byte fijo (0xAA). Por eso hay que llevar los perfiles en el PC.

Aviso técnico: un elemento con modificador y código 0 dejaría ese modificador
pulsado para siempre (es una función del firmware, no un fallo nuestro). Este
programa nunca genera algo así.",
    },
    Seccion {
        titulo: "Problemas frecuentes",
        cuerpo: "\
- «Sin teclado detectado»: comprueba el cable y que sea el teclado macro
  (VID 0x1189). Pulsa «Buscar teclado».

- Escribir no hace nada en Linux: el aparato necesita permisos. Instala la regla
  udev del repositorio (udev/99-macrokey.rules) o ejecuta con sudo.

- Una tecla salía «con Ctrl» o rara: el firmware puede quedarse con un
  modificador pulsado si se le escribió una trama mal formada. Se arregla
  desenchufando y volviendo a enchufar el teclado: el estado es de ejecución, no
  se graba en la flash.

- Con la perilla el volumen salta mucho: cada muesca emite varios eventos; es
  del firmware.

- ¿Y el LED? El protocolo lo soporta y el CLI ya lo escribe
  (macrokey led --color blue --mode 2); en la ventana llegará en una próxima
  versión.",
    },
    Seccion {
        titulo: "Sobre este programa",
        cuerpo: "\
Es software libre (MIT) y no oficial: no tiene nada que ver con el fabricante
del teclado. Nació de auditar el programa original (cerrado, sin firma y que
escribe la flash sin verificar nada) y reescribirlo desde cero, con el formato
documentado y probado contra el aparato.

Funciona con los teclados macro de la familia VID 0x1189 cuya interfaz de
configuración es la 1 (por ejemplo 1189:8890). Se puede ampliar a otros modelos:
el protocolo y las tablas de códigos están en el repositorio.

Código, protocolo y cómo medir tu propio teclado:
https://github.com/danieltobon21/macro-key-setup",
    },
];

const AYUDA_EN: &[Seccion] = &[
    Seccion {
        titulo: "Getting started",
        cuerpo: "\
1. Plug the macro keyboard in (no installer and no vendor software needed: it is
   a standard HID keyboard).

2. Click a key in the drawing on the left to select it. The text in the middle of
   each key is what it does right now.

3. In the right-hand panel pick the ACTION TYPE and fill it in:
      - Keyboard: the key (C, F5, ENTER, KP1…) and the modifiers (Ctrl, Shift…).
      - Mouse: a button or the wheel (with Ctrl/Shift/Alt if you want).
      - Media: play/pause, next, previous, mute, volume.
      - Sequence: several keys in a row, with a delay between them.

4. “Apply to this key” writes just that key; “Apply to keyboard” writes the whole
   configuration at once.

5. The configuration lives INSIDE the keyboard: unplug it and use it on another
   computer (Windows, Linux, Mac) without setting it up again.",
    },
    Seccion {
        titulo: "Mouse actions (Tinkercad and friends)",
        cuerpo: "\
The button stays pressed for as long as you hold the physical key, so it works
for DRAGGING, not just for a single click:

    middle button  ->  pan (move the view)
    right button   ->  rotate / orbit
    wheel          ->  zoom

In Tinkercad: the middle button pans and the right button orbits. Hold the macro
key down while you move the mouse.

If you want “Ctrl + wheel” (fine zoom in many apps), tick the Ctrl modifier on
the wheel action.

Note: the stickiness of the button is per key press, never written to flash.",
    },
    Seccion {
        titulo: "How it works (no magic)",
        cuerpo: "\
The keyboard is configured by writing 8-byte frames into its flash memory through
a private configuration channel (HID interface 1, 64-byte report with report id
3). On Linux it is written through /dev/hidraw or raw USB; on Windows through the
system HID API.

The format was reverse engineered from the vendor software and verified key by
key by reading what the device really emits. Everything is documented in the
repository (docs/PROTOCOL.md) and there are tests comparing the frames built by
this program with the prototype, byte for byte.

What you CANNOT do: read back the stored configuration. The configuration channel
has no interrupt IN endpoint and reading it through the control pipe returns a
constant byte (0xAA). That is why profiles live on your computer.

Technical warning: an element with a modifier and key code 0 would leave that
modifier held forever (a firmware feature, not our bug). This program never
generates one.",
    },
    Seccion {
        titulo: "Troubleshooting",
        cuerpo: "\
- “No keyboard detected”: check the cable and that it is the macro keyboard
  (VID 0x1189). Hit “Find keyboard”.

- Writing does nothing on Linux: the device needs permissions. Install the udev
  rule from the repository (udev/99-macrokey.rules) or run with sudo.

- A key typed “with Ctrl” or behaved oddly: the firmware can latch a modifier if
  it was written a malformed frame. Fix it by unplugging and replugging the
  keyboard: that state is runtime, it is not stored in flash.

- The knob jumps several volume steps per click: each detent emits several
  events; that is the firmware.

- What about the LED? The protocol supports it and the CLI already writes it
  (macrokey led --color blue --mode 2); it will reach the window in a later
  version.",
    },
    Seccion {
        titulo: "About this program",
        cuerpo: "\
Free software (MIT) and unofficial: it has nothing to do with the keyboard
vendor. It was born from auditing the original program (closed source, unsigned,
writing flash without verifying anything) and rewriting it from scratch, with the
format documented and tested against the device.

It works with the macro keyboards of the VID 0x1189 family whose configuration
interface is number 1 (for example 1189:8890). It can be extended to other
models: the protocol and key tables are in the repository.

Code, protocol and how to measure your own keyboard:
https://github.com/danieltobon21/macro-key-setup",
    },
];

pub fn ayuda(i: Idioma) -> &'static [Seccion] {
    match i {
        Idioma::Es => AYUDA_ES,
        Idioma::En => AYUDA_EN,
    }
}

pub const REPO: &str = "https://github.com/danieltobon21/macro-key-setup";
