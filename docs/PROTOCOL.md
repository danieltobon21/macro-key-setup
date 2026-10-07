# Protocolo HID — teclados macro "MINI KeyBoard" (VID 0x1189)

Reconstruido por ingeniería inversa de la app del fabricante
(`MINI KeyBoard.exe`, v1.0.0.2, WinForms/.NET4, namespace `HIDTester`),
decompilada con `ilspycmd` **con sus PDB originales**, por lo que el código es
casi idéntico al fuente del autor. Fuente decompilada: `../re/decompiled/`.

No hay cifrado, no hay ofuscación y no hay protocolo propietario «raro»:
es un HID de escritura directa (output reports). Todo lo que sigue está sacado
del código, no de suposiciones.

---

## 1. Identificación del dispositivo

| dato | valor |
|---|---|
| VID | `0x1189` (4489 dec) — fabricante OEM chino genérico |
| PIDs que reconoce la app | `0x8890`, `0x8830`, `0x8831`, `0x8832`, `0x8833`, `0x8834`, `0x8840`, `0x87D0` |
| Interfaces | el aparato es **compuesto**: la app elige la interfaz cuyo `DevicePath` contiene `mi_01` (solo para `0x8890`) o `mi_00` (todos los demás) |
| `0x8840` | además activa `New_Mul_Mouse = 1` (mapa de índices de tecla distinto) |

En Linux: `mi_00` / `mi_01` es la **interfaz USB** del dispositivo compuesto
(`bInterfaceNumber`), o sea `/dev/hidrawN` correspondiente a esa interfaz
(`/sys/class/hidraw/hidrawN/device/uevent` → `HID_PHYS=.../inputM`, y
`../<usb-iface>/bInterfaceNumber`).

### Dos "protocolos" según el modelo

| `Sd_Protocol_Type` | modelos | tamaño de datos que usa la app | formato de trama para escribir una tecla |
|---|---|---|---|
| `0` | `0x8890` (interfaz `mi_01`) | 8 bytes | trama corta (§4.1) |
| `1` | `0x8830..0x8834`, `0x8840`, `0x87D0` (interfaz `mi_00`) | 46 bytes | trama `0xFE` (§4.2) |

El buffer de la app siempre es de **65 bytes** (`byte[65]`), pero solo copia al
reporte los 8 o los 46 primeros bytes de datos. El tamaño real del output report
sale del descriptor HID (`OutputReportByteLength`), y **hay que leerlo** antes de
escribir: en Windows la app confía en él, nosotros también debemos.

---

## 2. Report ID = "canal"/versión del firmware

Antes de cualquier escritura, la app ejecuta `KeyBoardVersion_Check()`
(FormMain.cs:465): envía una trama de ceros probando distintos report IDs y se
queda con el que acepta el dispositivo.

```
para id en [3, 0, 2]:
    escribir(report_id = id, datos = [0x00, 0x00, 0x00 ... 0x00])
    si la escritura no falla -> ReportID = id ; parar
```

- `ReportID = 3` → modelo moderno: teclas multimedia con **códigos HID Consumer
  estándar** (`0xCD` play, `0xB5` siguiente, `0xB6` anterior, `0xE2` mute,
  `0xE9` vol+, `0xEA` vol−`).
- `ReportID = 0` → tabla interna antigua (`0x80`, `0x01`, `0x40`, `0x02`...).
- `ReportID = 2` → tabla intermedia (`0x0B`, `0x0A`, `0x04`...).

El report ID elegido se reutiliza **en todas** las tramas posteriores y además
determina qué tabla de códigos multimedia usar (§6.3).

> Nota Linux: `hidraw` espera el byte de report ID delante de los datos
> **solo si el descriptor declara informes numerados**. La app lo escribe
> siempre. Hay que decidir esto leyendo el descriptor del aparato concreto.

---

## 3. Comandos sueltos (control)

Todas las tramas van con el `ReportID` detectado; los bytes no usados = `0x00`.

| comando | bytes | efecto | origen |
|---|---|---|---|
| version/keepalive | `00 00 ...` | sondeo de canal (§2) | `KeyBoardVersion_Check` |
| **cambiar capa** | `A1 <capa>` | cambia la capa activa (capa 1..3, 0→1) | `Send_SwLayer` |
| **commit teclas** | `AA AA` | graba en flash lo escrito para teclas/capas | `Send_WriteFlash_Cmd` |
| **commit LED** | `AA A1` | graba en flash la sección LED | `Send_WriteFlashLED_Cmd` |

`<capa>`: 1, 2 o 3 (el firmware tiene 3 capas; 0 se normaliza a 1).
Después de escribir las teclas de una capa **siempre** se manda el commit.

---

## 4. Escribir una tecla

Índice de tecla (`byte 1`) según `New_Mul_Mouse` (FormMain.cs:1075-1399 + HidLib):

| elemento | `New_Mul_Mouse=0` | `New_Mul_Mouse=1` |
|---|---|---|
| teclas 1..16 | 1..12 para KEY1..KEY12 | 1..15 para KEY1..KEY15 |
| perilla 1 | 13 = ←, 14 = pulsar, 15 = → | 16, 17, 18 |
| perilla 2 | 16, 17, 18 | 19, 20, 21 |
| perilla 3 | 19, 20, 21 | 22, 23, 24 |
| **LED** | `0xB0` (176) | `0xB0` |
| (KEY13/14/15 solo existen con `New_Mul_Mouse=1`) | | |

En el modelo del taller (6 teclas + 1 perilla: atrás / adelante / pulsar) los
índices útiles son: **1..6** = teclas y **el grupo de la perilla** (13/14/15 o
16/17/18 según `New_Mul_Mouse`). Se confirmará con el descriptor del aparato.

### 4.1 Trama corta (protocolo 0, 8 bytes)

```
byte 0 : 0x00                      (el report ID va aparte)
byte 1 : (capa << 4) | (tipo & 0x0F)
byte 2 : nº de elementos de la secuencia
byte 3 : índice del elemento (0..n)
byte 4 : valor A
byte 5 : valor B
```
`Send_WriteFlash_Cmd` al terminar.

### 4.2 Trama larga (protocolo 1, 46 bytes) — `Download_Click`

Es la que usan los modelos `mi_00` (la familia de tu teclado). La app construye
`Data_Send_Buff` (un array de 65 B) y **copia literalmente `Data_Send_Buff[4..39]`
a los bytes 10..45 del reporte**; el retardo vive en otro array
(`Protocol2_Sd_Buff`) que va a los bytes 4-5:

```
byte 0  : 0xFE                    ; constante "definir tecla"
byte 1  : índice de tecla         ; (§4, 0xB0 = LED)
byte 2  : capa (1..3)
byte 3  : tipo de tecla           ; §5
byte 4  : retardo (byte bajo)     ; Protocol2_Sd_Buff[4], ms
byte 5  : retardo (byte alto)     ; Protocol2_Sd_Buff[5]
byte 6  : 0
byte 7  : 0
byte 8  : 0
byte 9  : nº de pares ocupados    ; §4.2.1
byte 10 : relleno (lo que quede en Data_Send_Buff[4])
byte 11 : 1er código de tecla     ; Data_Send_Buff[5]
byte 12 : su máscara              ; Data_Send_Buff[6]
byte 13 : 2º código               ; Data_Send_Buff[7]
byte 14 : su máscara
...    : (así hasta el byte 45: 18 pares en total)
```

Ocupación de `Data_Send_Buff` por tipo (posiciones del original, verificadas en el
código decompilado):

| tipo | dónde escribe |
|---|---|
| teclado | `buf[5+2k]` = código, `buf[6+2k]` = máscara (`|=`), cursor +2 por elemento |
| multimedia | `buf[5]`; si el modelo usa `New_Mul_Mouse` → `buf[4]`; y con report id 2, un byte más allá |
| ratón | 4 bytes en `buf[5..9]` (botones, dx, dy, rueda); la máscara va en `buf[4]` si `New_Mul_Mouse`, si no en `buf[9]` |
| LED | `buf[4]` = capa, `buf[5]` = `(color<<4)|modo` |

Después de la trama, en protocolo 1 **no se manda `AA AA`**: la propia trama
`0xFE` deja la tecla grabada (el `Send_WriteFlash_Cmd` solo se usa en el camino
del protocolo corto).

#### 4.2.1 El contador del byte 9

No es "nº de elementos" sino "nº de **pares** ocupados", y el original lo calcula
de forma perezosa: recorre los 18 pares `(buf[4],buf[5]), (buf[6],buf[7])…` y se
queda con el índice del último no nulo. Por eso un `Ctrl+A` da `2` (par 0 =
`(0, 0x04)` = A, par 1 = `(0x01, 0)`) y una tecla con un solo carácter da `1`.

#### 4.2.2 Verificación sin hardware

`proto/macrokey.py frames` construye estas tramas sin necesidad de que el teclado
esté conectado, y la implementación Rust tiene `--dry-run` con la misma salida.
Ejemplos ya comprobados:

```
$ python3 proto/macrokey.py frames --key 1 --codes A --mods ctrl
  fe 01 01 01 00 00 00 00 00 00 00 04 01 00 ...     # A=0x04 en byte 11, Ctrl en 12

$ python3 proto/macrokey.py frames --key 6 --codes H,O,L,A --delay 30
  fe 06 01 01 1e 00 00 00 00 00 00 0b 00 12 00 0f 00 04 ...   # retardo 30 (0x1e) + HOLA

$ python3 proto/macrokey.py frames --led --color blue --mode 2
  fe b0 01 08 00 00 00 00 00 01 01 62 ...            # 0x62 = azul(6)<<4 | modo 2
```

---

## 5. Tipos de tecla (byte 3)

| valor | significado | origen |
|---|---|---|
| `0x00` | nada / NULL (borra la tecla) | `KEY_NILL_Click` |
| `0x01` | teclado: secuencia de teclas + modificadores | `BasicKeys`, `FunKey` |
| `0x02` | multimedia | `MULKey` |
| `0x03` | ratón (4 bytes) | `MouseKey` |
| `0x08` | LED (config de la luz) | `LEDkey` |

(`Data_Send_Buff[1]` se construye con `|=` en estos bits.)

---

## 6. Tablas de códigos

### 6.1 Teclado normal (`BasicKeys`) — usos HID estándar

Códigos = *Usage ID* del HID Usage Table (Keyboard/Keypad, página 0x07):
`4=A … 29=Z`, `30=1 … 39=0`, `40=Enter`, `41=ESC`, `42=Backspace`, `43=Tab`,
`44=Space`, `58..69=F1..F12`, `73=Insert`, `76=Delete`, `74=Home`, `77=End`,
`75=PageUp`, `78=PageDown`, `79..82=flechas`, teclado numérico `84..99`,
`101=Menú`. Tabla completa en `../re/tables/keytables.json` (100 entradas).

### 6.2 Máscara de modificadores (byte de "máscara" del par)

| bit | modificador |
|---|---|
| `0x01` | Ctrl izquierdo |
| `0x02` | Shift izquierdo |
| `0x04` | Alt izquierdo |
| `0x08` | Win izquierdo |
| `0x10` | Ctrl derecho |
| `0x20` | Shift derecho |
| `0x40` | Alt derecho (AltGr) |
| `0x80` | Win derecho |

(`FunKey` tiene además combinaciones predefinidas Ctrl+Shift+Alt… que solo
escriben varios bits.)

### 6.3 Multimedia (`MULKey`) — depende del ReportID

| tecla | ReportID=3 (moderno) | ReportID=2 | ReportID=0 (antiguo) |
|---|---|---|---|
| Play/Pausa | `0xCD` (205) | `0x04` | `0x40` |
| Siguiente | `0xB5` (181) | `0x0A` (10) | `0x01` |
| Anterior | `0xB6` (182) | `0x0B` (11) | `0x80` |
| Mute | `0xE2` (226) | `0x01` | `0x04` |
| Volumen + | `0xE9` (233) | `0x40` | `0x02` |
| Volumen − | `0xEA` (234) | `0x80` | `0x01` |

### 6.4 Ratón (`MouseKey`) — 4 bytes

```
byte 0 : botones  (1 = izquierdo, 2 = derecho, 4 = central)
byte 1 : desplazamiento X (con signo)
byte 2 : desplazamiento Y (con signo)
byte 3 : rueda     (0x01 = arriba, 0xFF = abajo)
```
Con modificador (Ctrl/Shift/Alt + rueda) se escribe además la máscara de §6.2
en el byte de máscara del elemento.

### 6.5 LED (`LEDkey`)

`tipo |= 0x08` y **índice de tecla = `0xB0`**; el color/modo va en un byte
`(color << 4) | modo`:

| protocolo | dónde va la capa | dónde va `(color<<4)|modo` |
|---|---|---|
| 1 (trama larga) | reporte byte **2** y **10** | reporte byte **11** |
| 0 (trama corta) | reporte byte **1** (nibble alto) | reporte byte **2** |

(En la trama corta, `Data_Send_Buff[2]` = modo y `[5]`/`[2]` según la rama; en la
larga, el par `Data_Send_Buff[4]/[5]` se copia a los bytes 10/11 del reporte.)

| color | valor | modo | valor |
|---|---|---|---|
| rojo | 1 | modo 0 | 0 |
| naranja | 2 | modo 1 | 1 |
| amarillo | 3 | modo 2 | 2 |
| verde | 4 | modo 3 | 3 |
| cian | 5 | modo 4 | 4 |
| azul | 6 | modo 5 | 5 |
| morado | 7 | — | — |

Al terminar: `Send_WriteFlashLED_Cmd` (`AA A1`).

---

## 7. Secuencias y retardo

Una tecla puede contener una **secuencia** de hasta 18 elementos
(`KeyGroupCharNum`, máximo visto 18). El retardo entre elementos se escribe en
el par de bytes 4/5 del buffer (little endian, valor en ms, página *Delay* del
GUI; se muestra como "N M S").

---

## 8. Lo que la app del fabricante **no** hace (y nosotros sí podemos)

- **No lee** la configuración del aparato: escribe a ciegas. `myhid_DataReceived`
  guarda lo que llega en `RecDataBuffer` y **nunca lo interpreta** (no hay
  "leer tecla actual", ni backup, ni verificación de lo escrito).
- No hay modo "probar tecla" en vivo, ni perfiles, ni exportar/importar.
- La UI es de 2013: fuentes chinas por defecto, sin escalado, sin atajos.

Mejoras que justifican reescribirlo (además de la seguridad):
1. **Leer/volcar** la configuración actual (si el firmware responde a
   `GetFeature`/lectura de flash — hay que probar).
2. **Perfiles** en fichero (TOML/YAML) + backup/restore + `macro-key apply perfil.toml`.
3. Interfaz moderna (TUI/GUI) y CLI scriptable.
4. Mapa de códigos legible (HID) en vez de números crudos.
