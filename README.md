# macrokey — reimplementación libre del software del teclado macro (VID 0x1189)

Proyecto propio para configurar el teclado macro de 6 teclas + perilla (atrás /
adelante / pulsar) **sin depender del software del fabricante** (`MINI KeyBoard.exe`,
namespace `HIDTester`), del que no se conoce autor ni se puede auditar.

Todo el formato de comunicación está reconstruido por ingeniería inversa del
binario del fabricante, que venía **con sus PDB** (por eso el código fuente
recuperado es prácticamente el original).

## Contenido

| ruta | qué es |
|---|---|
| `docs/AUDITORIA-vendor.md` | auditoría de seguridad de la app del fabricante (¿hace algo raro?) |
| `docs/PROTOCOL.md` | **especificación completa del protocolo HID**: tramas, tipos, tablas de códigos |
| `re/decompiled/` | código C# recuperado con `ilspycmd` (fuente de verdad de la RE) |
| `re/hidlibrary/` | decompilado de `HidLibrary.dll` (MIT de Mike O'Brien, la que usa el original) |
| `re/tables/` | tablas de códigos extraídas automáticamente (`keytables.json` / `.md`) |
| `re/tools/extract_tables.py` | el extractor (regenera las tablas desde el C#) |
| `proto/macrokey.py` | prototipo funcional en Python (sin dependencias, `/dev/hidraw` directo) |
| `tools/comparar-tramas.py` | comparación byte a byte de las tramas Python vs Rust (regresión del protocolo) |
| `profiles/` | perfiles TOML (`tinkercad.toml` = el del taller) |
| `udev/99-macrokey.rules` | regla udev para usar el aparato sin `sudo` |
| `rust/` | aplicación final en Rust (binario único, sin dependencias C) |

## Estado

- [x] Identificación del aparato, del software y auditoría de seguridad.
- [x] Decompilación completa y documentación del protocolo (tramas, tipos, códigos).
- [x] Prototipo Python (`proto/macrokey.py`) con transporte **hidraw y usbfs**.
- [x] **App en Rust** (`rust/`): compila sin avisos, `list`, `info`, `probe`,
      `key`, `led`, `commit`, `apply <perfil.toml>`, `raw`, `--dry-run` y
      `--transport auto|hidraw|usbfs`. Tramas idénticas byte a byte al prototipo.
- [x] **Validado en hardware**: el teclado del taller (VID:PID `1189:8890`) se
      configura desde Linux por USB directo (su canal de configuración no tiene
      nodo `/dev/hidraw`). Ver §1.1 de `docs/PROTOCOL.md`.
- [x] **Configuración final funcionando en el teclado** (medido, §9 de
      `docs/PROTOCOL.md`): teclas 1-4 = Ctrl+C / Ctrl+V / Ctrl+X / Esc (sin
      modificadores pegados), teclas 5-6 = botón central y derecho del ratón
      **manteniéndose mientras se mantiene la tecla** (pan/rotate), perilla =
      volumen −, play/pausa, volumen +. Es portátil: al ser HID estándar
      funciona igual en Windows, sin software del fabricante.
- [x] **Herramientas de medida**: `monitor` (informes de entrada decodificados,
      con marca de tiempo y re-escaneo) y `tools/comparar-tramas.py`
      (20/20 tramas idénticas entre el prototipo Python y la app Rust).
- [x] **GUI en Rust+egui** (`rust/src/gui.rs`): dibuja el aparato a escala real
      (100 × 60 mm, 1 mm = 6 px) con cada tecla etiquetada con su función, la
      perilla con sus tres zonas y el editor por tecla; muestra las tramas
      exactas antes de escribir y aplica por el mismo camino que el CLI. Sin
      argumentos abre la ventana (así funciona el doble clic en Windows). Ver
      `gui/README.md` y `gui/vistas/interfaz-previa.png`.
- [x] **Windows**: transporte por la API HID nativa (`rust/src/winhid.rs`:
      SetupAPI para enumerar + `CreateFileW`/`WriteFile` del informe de 65 B) e
      icono incrustado en el `.exe` (`rust/build.rs`).
- [ ] `dump`/backup de la config actual del teclado (si el firmware lo permite).
- [ ] Verificar en Windows la escritura en la flash (el transporte está escrito
      pero no probado contra el aparato desde ese sistema).

### App en Rust

```bash
cd rust
cargo build --release                 # binario único, sin dependencias C
./target/release/macrokey list
./target/release/macrokey info        # sin root: no abre el aparato
sudo ./target/release/macrokey apply --profile ../profiles/tinkercad.toml
sudo ./target/release/macrokey key --key 1 --codes C --mods ctrl
./target/release/macrokey apply --dry-run --profile ../profiles/tinkercad.toml
./target/release/macrokey             # abre la GUI
```

`--dry-run` imprime las tramas en hex, así que se puede revisar todo antes de
escribir en la flash del teclado. `--transport auto` elige hidraw o USB directo
según el modelo; solo hace falta forzarlo si hay rarezas.

### Compilar en Windows

En el PC de trabajo (Windows 11, toolchain `x86_64-pc-windows-msvc`):

```powershell
git clone https://github.com/danieltobon21/macro-key-setup.git C:\working-files\macrokey
cd C:\working-files\macrokey\rust
# las herramientas de VS no están en el PATH de una sesión normal: hay que llamar a vcvars64
cmd /c '"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" && cargo build --release'
```

Queda `rust\target\release\macrokey.exe`: doble clic abre la ventana (no lleva
consola ni instalador) y lleva el icono incrustado. En Windows el canal de
configuración se escribe por la **API HID** (no hay `/dev/hidraw`): no hace
falta el software del fabricante, ni permisos de administrador.


### Perfiles

En `profiles/` están las configuraciones en TOML (`tinkercad.toml` es la del
taller: copiar/pegar/cortar, escape, pan/rotar de Tinkercad y la perilla para
volumen y play/pausa).

## Uso del prototipo

```bash
sudo python3 proto/macrokey.py list            # ¿está conectado? ¿qué PID?
sudo python3 proto/macrokey.py info hidraw3    # descriptor, report IDs y tamaños
sudo python3 proto/macrokey.py probe hidraw3   # qué 'report id' (versión FW) acepta
sudo python3 proto/macrokey.py key  hidraw3 --key 1 --codes A --mods ctrl
sudo python3 proto/macrokey.py key  hidraw3 --key 4 --media play
sudo python3 proto/macrokey.py key  hidraw3 --key 5 --mouse wheelup
sudo python3 proto/macrokey.py led  hidraw3 --mode 2 --color blue
```

Sin `sudo` (recomendado), instala primero la regla udev:

```bash
sudo cp udev/99-macrokey.rules /etc/udev/rules.d/
sudo udevadm control --reload && sudo udevadm trigger
```

## Aviso

Escribimos en la **memoria flash del teclado**. Antes de cambiar nada: `probe`,
luego una tecla de prueba, y comprobar el resultado. La app del fabricante
sigue siendo el «plan B» válido para dejar el aparato como estaba.
