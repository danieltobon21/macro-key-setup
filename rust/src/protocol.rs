//! Protocolo del teclado macro, reconstruido del binario del fabricante.
//! Especificación completa (con el porqué de cada byte): `docs/PROTOCOL.md`.

// ---------------------------------------------------------------- constantes

pub const TYPE_NONE: u8 = 0x00;
pub const TYPE_KEY: u8 = 0x01;
pub const TYPE_MEDIA: u8 = 0x02;
pub const TYPE_MOUSE: u8 = 0x03;
pub const TYPE_LED: u8 = 0x08;

pub const CMD_WRITE_FLASH: [u8; 2] = [0xAA, 0xAA]; // Send_WriteFlash_Cmd
pub const CMD_WRITE_LED: [u8; 2] = [0xAA, 0xA1]; // Send_WriteFlashLED_Cmd
pub const CMD_SW_LAYER: u8 = 0xA1; // Send_SwLayer
pub const KEY_LED_INDEX: u8 = 0xB0; // índice pseudo-tecla para el LED

/// Longitud de datos de la trama larga (protocolo 1) tal como la escribe la app.
pub const LONG_FRAME_LEN: usize = 46;
/// Longitud de datos de la trama corta (protocolo 0).
pub const SHORT_FRAME_LEN: usize = 8;

// ------------------------------------------------------------------- tablas

/// Máscara de modificadores (byte de máscara de cada elemento).
pub fn modifier_mask(name: &str) -> Option<u8> {
    Some(match name.to_ascii_lowercase().as_str() {
        "ctrl" | "lctrl" | "control" => 0x01,
        "shift" | "lshift" => 0x02,
        "alt" | "lalt" => 0x04,
        "altgr" | "ralt" => 0x40,
        "win" | "super" | "lwin" => 0x08,
        "rctrl" => 0x10,
        "rshift" => 0x20,
        "rwin" => 0x80,
        _ => return None,
    })
}

/// Usage IDs de la página Keyboard/Keypad (0x07) — la tabla que usa el firmware,
/// verificada contra `re/tables/keytables.json` extraído del binario original.
pub fn key_code(name: &str) -> Option<u8> {
    let n = name.trim();
    let up = n.to_ascii_uppercase();
    let single = up.as_bytes();
    if single.len() == 1 {
        let c = single[0];
        if c.is_ascii_uppercase() {
            return Some(c - b'A' + 0x04); // A..Z
        }
        if c.is_ascii_digit() {
            return Some(match c {
                b'1' => 0x1E,
                b'2' => 0x1F,
                b'3' => 0x20,
                b'4' => 0x21,
                b'5' => 0x22,
                b'6' => 0x23,
                b'7' => 0x24,
                b'8' => 0x25,
                b'9' => 0x26,
                _ => 0x27, // 0
            });
        }
    }
    // teclas del teclado numérico: KP1..KP9, KP0
    if let Some(rest) = up.strip_prefix("KP") {
        return match rest {
            "1" => Some(0x59),
            "2" => Some(0x5A),
            "3" => Some(0x5B),
            "4" => Some(0x5C),
            "5" => Some(0x5D),
            "6" => Some(0x5E),
            "7" => Some(0x5F),
            "8" => Some(0x60),
            "9" => Some(0x61),
            "0" => Some(0x62),
            "DOT" | "." => Some(0x63),
            "ENTER" => Some(0x58),
            "MINUS" | "-" => Some(0x56),
            "PLUS" | "+" => Some(0x57),
            _ => None,
        };
    }
    if let Some(rest) = up.strip_prefix('F') {
        if let Ok(n) = rest.parse::<u8>() {
            if (1..=12).contains(&n) {
                return Some(0x3A + n - 1);
            }
        }
    }
    Some(match up.as_str() {
        "ENTER" | "RETURN" => 0x28,
        "ESC" | "ESCAPE" => 0x29,
        "BACKSPACE" | "BKSP" => 0x2A,
        "TAB" => 0x2B,
        "SPACE" | "SPACEBAR" => 0x2C,
        "MINUS" | "-" => 0x2D,
        "EQUAL" | "=" => 0x2E,
        "LBRACKET" | "[" => 0x2F,
        "RBRACKET" | "]" => 0x30,
        "BACKSLASH" | "\\" => 0x31,
        "SEMICOLON" | ";" => 0x33,
        "QUOTE" | "'" => 0x34,
        "GRAVE" | "`" => 0x35,
        "COMMA" | "," => 0x36,
        "PERIOD" | "." => 0x37,
        "SLASH" | "/" => 0x38,
        "CAPSLOCK" => 0x39,
        "PRINTSCREEN" | "PRTSC" => 0x46,
        "SCROLLLOCK" => 0x47,
        "PAUSE" | "BREAK" => 0x48,
        "INSERT" | "INS" => 0x49,
        "HOME" => 0x4A,
        "PAGEUP" | "PGUP" => 0x4B,
        "DELETE" | "DEL" => 0x4C,
        "END" => 0x4D,
        "PAGEDOWN" | "PGDN" => 0x4E,
        "RIGHT" => 0x4F,
        "LEFT" => 0x50,
        "DOWN" => 0x51,
        "UP" => 0x52,
        "NUMLOCK" => 0x53,
        "MENU" => 0x65,
        _ => return None,
    })
}

/// MULKey.cs — el código multimedia depende del "report id" (versión del firmware).
/// report id 3 = códigos HID Consumer estándar (los que usamos).
pub fn media_code(name: &str, report_id: u8) -> Option<u8> {
    let table: &[(&str, [u8; 3])] = &[
        //            id3     id2   id0
        ("play",    [0xCD, 0x04, 0x40]),
        ("next",    [0xB5, 0x0A, 0x01]),
        ("prev",    [0xB6, 0x0B, 0x80]),
        ("mute",    [0xE2, 0x01, 0x04]),
        ("volup",   [0xE9, 0x40, 0x02]),
        ("voldown", [0xEA, 0x80, 0x01]),
    ];
    let idx = match report_id {
        3 => 0,
        2 => 1,
        _ => 2,
    };
    table
        .iter()
        .find(|(n, _)| n.eq_ignore_ascii_case(name))
        .map(|(_, v)| v[idx])
}

pub fn mouse_button(name: &str) -> Option<u8> {
    Some(match name.to_ascii_lowercase().as_str() {
        "left" => 0x01,
        "right" => 0x02,
        "middle" | "centre" | "center" => 0x04,
        _ => return None,
    })
}

pub fn led_color(name: &str) -> Option<u8> {
    Some(match name.to_ascii_lowercase().as_str() {
        "red" => 1,
        "orange" => 2,
        "yellow" => 3,
        "green" => 4,
        "cyan" => 5,
        "blue" => 6,
        "purple" => 7,
        _ => return None,
    })
}

/// Índices de tecla del firmware. Devuelve None si el índice no es válido
/// para ese modelo.
pub fn key_index(name: &str, new_mul_mouse: bool) -> Option<u8> {
    let n = name.trim().to_ascii_lowercase();
    if let Ok(v) = n.parse::<u8>() {
        return Some(v);
    }
    let (k1, k1_push, k1_other) = if new_mul_mouse { (16, 17, 18) } else { (13, 14, 15) };
    Some(match n.as_str() {
        "knob-left" | "knob-back" | "knob-anti" => k1,
        "knob-push" | "knob-press" | "knob-click" => k1_push,
        "knob-right" | "knob-fwd" | "knob-forward" => k1_other,
        _ => return None,
    })
}

// --------------------------------------------------------------- tramas

/// Elemento de una secuencia dentro de una tecla.
#[derive(Debug, Clone, Copy)]
pub enum Step {
    /// combinación de teclado: código HID + máscara de modificadores
    Key { code: u8, mods: u8 },
    /// acción de ratón: botones, dx, dy, rueda y máscara de modificador
    Mouse {
        buttons: u8,
        dx: i8,
        dy: i8,
        wheel: i8,
        mods: u8,
    },
    /// código multimedia
    Media { code: u8 },
}

/// Construye el `Data_Send_Buff` de 65 bytes replicando **exactamente** lo que
/// hace la app del fabricante (cursor `KEY_Char_Num` empezando en 5):
///
/// * un elemento de teclado ocupa `buf[cursor]` = código y `buf[cursor+1]` = máscara
///   (la máscara se escribe con `|=`, por eso el tabulador del original), y el
///   cursor avanza de 2 en 2;
/// * ratón y multimedia escriben en `buf[cursor..]` y no avanzan el cursor
///   (son acciones finales);
/// * el contador (`buf[2]`) es el que calcula el original: recorre pares desde
///   `buf[4]` y se queda con el último par no nulo.
///
/// Estas posiciones se copian luego literales a la trama (ver `long_frame`).
fn build_buffer(key_type: u8, steps: &[Step], nmm: bool, report_id: u8) -> Vec<u8> {
    let mut b = vec![0u8; 64];
    b[1] = key_type;
    let mut cursor = 5usize;
    for s in steps.iter().take(18) {
        match *s {
            Step::Key { code, mods } => {
                b[cursor] = code;
                b[cursor + 1] |= mods;
                cursor += 2;
            }
            Step::Mouse {
                buttons,
                dx,
                dy,
                wheel,
                mods,
            } => {
                b[5] = buttons;
                b[6] = dx as u8;
                b[7] = dy as u8;
                b[8] = wheel as u8;
                if mods != 0 {
                    if nmm {
                        b[4] |= mods;
                    } else {
                        b[9] |= mods;
                    }
                }
            }
            Step::Media { code } => {
                // `Key_Fun_Num` (4) si el modelo usa el mapa nuevo, si no
                // `KEY_Char_Num` (5); con report id 2 el original escribe un byte
                // más allá.
                let mut pos = if nmm && report_id != 2 { 4 } else { 5 };
                if report_id == 2 {
                    pos += 1;
                }
                b[pos] = code;
            }
        }
    }
    // Contador de pares, tal cual lo calcula el original.
    let mut count = 0u8;
    for i in 0..18 {
        if b[4 + 2 * i] != 0 || b[5 + 2 * i] != 0 {
            count = (i + 1) as u8;
        }
    }
    b[2] = count;
    b
}

/// Trama larga (protocolo 1): 46 bytes de datos. El original copia *literalmente*
/// `Data_Send_Buff[4..39]` a los bytes 10..45 del reporte, por eso el primer
/// código de tecla acaba en el byte **11** (y el 10 queda como relleno).
pub fn long_frame(
    index: u8,
    layer: u8,
    key_type: u8,
    steps: &[Step],
    delay_ms: u16,
    nmm: bool,
    report_id: u8,
) -> Vec<u8> {
    let buf = build_buffer(key_type, steps, nmm, report_id);
    let mut d = vec![0u8; LONG_FRAME_LEN];
    d[0] = 0xFE;
    d[1] = index;
    d[2] = layer;
    d[3] = key_type;
    // El retardo está en `Protocol2_Sd_Buff` (otro array del original): va a los
    // bytes 4/5 del reporte, no al bloque de datos.
    d[4] = (delay_ms & 0xFF) as u8;
    d[5] = (delay_ms >> 8) as u8;
    d[9] = buf[2]; // contador de pares (Data_Send_Buff[2] -> reporte byte 9)
    for i in 0..(LONG_FRAME_LEN - 10) {
        d[10 + i] = buf[4 + i];
    }
    d
}

/// Tramas cortas (protocolo 0): una escritura por elemento, 8 bytes cada una.
/// Reproduce el `switch (b)` del original (los índices 0 y 1 comparten `buf[4]`).
pub fn short_frames(
    index: u8,
    layer: u8,
    key_type: u8,
    steps: &[Step],
    report_id: u8,
    nmm: bool,
) -> Vec<Vec<u8>> {
    let buf = build_buffer(key_type, steps, nmm, report_id);
    let count = buf[2].max(1);
    let mut out = Vec::new();
    for b in 0..=count as usize {
        let mut d = vec![0u8; SHORT_FRAME_LEN];
        d[0] = index;
        d[1] = if report_id == 0 {
            key_type & 0x0F
        } else {
            (layer << 4) | (key_type & 0x0F)
        };
        d[2] = count;
        d[3] = b as u8;
        match b {
            0 => {
                d[4] = buf[4];
                d[5] = 0;
            }
            // caso n>=1: buf[2n+2], buf[2n+3]
            n => {
                d[4] = buf[2 * n + 2];
                d[5] = buf[2 * n + 3];
            }
        }
        out.push(d);
    }
    out
}

/// Trama de LED (protocolo 1): `buf[4]` = capa, `buf[5]` = (color<<4 | modo).
pub fn led_long_frame(layer: u8, color: u8, mode: u8) -> Vec<u8> {
    let mut d = vec![0u8; LONG_FRAME_LEN];
    d[0] = 0xFE;
    d[1] = KEY_LED_INDEX;
    d[2] = layer;
    d[3] = TYPE_LED;
    d[9] = 1; // contador: el par (buf[4], buf[5]) es no nulo
    d[10] = layer; // buf[4] -> reporte byte 10
    d[11] = (color << 4) | (mode & 0x0F); // buf[5] -> reporte byte 11
    d
}

pub fn led_short_frame(layer: u8, color: u8, mode: u8) -> Vec<u8> {
    let mut d = vec![0u8; SHORT_FRAME_LEN];
    d[0] = KEY_LED_INDEX;
    d[1] = (layer << 4) | TYPE_LED;
    d[2] = (color << 4) | (mode & 0x0F);
    d
}

pub fn sw_layer_frame(layer: u8) -> Vec<u8> {
    vec![CMD_SW_LAYER, if layer == 0 { 1 } else { layer }]
}

// ------------------------------------------------- perfil de configuración

/// Una asignación de tecla del fichero de perfil.
#[derive(Debug, Clone, serde::Deserialize)]
pub struct Binding {
    /// índice de tecla ("1".."24", "knob-left", "knob-push", "knob-right"…)
    pub key: String,
    #[serde(default = "default_layer")]
    pub layer: u8,
    /// true = borrar la tecla (tipo NONE)
    #[serde(default)]
    pub clear: bool,
    /// secuencia de códigos de tecla (A, B, F5, ENTER…) con modificadores comunes
    #[serde(default)]
    pub codes: Vec<String>,
    #[serde(default)]
    pub mods: Vec<String>,
    /// acción multimedia: play/next/prev/mute/volup/voldown
    #[serde(default)]
    pub media: Option<String>,
    /// acción de ratón: left/right/middle/wheelup/wheeldown
    #[serde(default)]
    pub mouse: Option<String>,
    /// retardo entre elementos de la secuencia (ms)
    #[serde(default)]
    pub delay_ms: u16,
}

fn default_layer() -> u8 {
    1
}

#[derive(Debug, Clone, serde::Deserialize)]
pub struct Profile {
    #[serde(default)]
    pub name: String,
    /// capa del LED (modo + color) si se define
    #[serde(default)]
    pub led: Option<LedBinding>,
    #[serde(default, rename = "binding")]
    pub bindings: Vec<Binding>,
}

#[derive(Debug, Clone, serde::Deserialize)]
pub struct LedBinding {
    #[serde(default = "default_layer")]
    pub layer: u8,
    #[serde(default)]
    pub mode: u8,
    #[serde(default = "default_color")]
    pub color: String,
}

fn default_color() -> String {
    "green".into()
}

/// Convierte un `Binding` en tipo de tecla + secuencia de pasos.
pub fn steps_for(b: &Binding, report_id: u8) -> Result<(u8, Vec<Step>), String> {
    if b.clear {
        return Ok((TYPE_NONE, vec![]));
    }
    let mut mods = 0u8;
    for m in &b.mods {
        mods |= modifier_mask(m).ok_or_else(|| format!("modificador desconocido: {m}"))?;
    }
    if let Some(m) = &b.media {
        let code = media_code(m, report_id).ok_or_else(|| format!("multimedia desconocida: {m}"))?;
        return Ok((TYPE_MEDIA, vec![Step::Media { code }]));
    }
    if let Some(m) = &b.mouse {
        let lower = m.to_ascii_lowercase();
        let (buttons, wheel): (u8, i8) = match lower.as_str() {
            "wheelup" => (0, 1),
            "wheeldown" => (0, -1),
            other => (
                mouse_button(other)
                    .ok_or_else(|| format!("acción de ratón desconocida: {other}"))?,
                0,
            ),
        };
        return Ok((
            TYPE_MOUSE,
            vec![Step::Mouse {
                buttons,
                dx: 0,
                dy: 0,
                wheel,
                mods,
            }],
        ));
    }
    let mut steps = Vec::new();
    for (i, c) in b.codes.iter().enumerate() {
        let code = key_code(c).ok_or_else(|| format!("tecla desconocida: {c}"))?;
        steps.push(Step::Key {
            code,
            // el modificador acompaña solo al primer elemento de la secuencia
            mods: if i == 0 { mods } else { 0 },
        });
    }
    if steps.is_empty() {
        return Err("binding sin 'codes', 'media', 'mouse' ni 'clear'".into());
    }
    Ok((TYPE_KEY, steps))
}

pub fn parse_profile(text: &str) -> Result<Profile, toml::de::Error> {
    toml::from_str(text)
}
