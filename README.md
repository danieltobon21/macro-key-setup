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
| `udev/99-macrokey.rules` | regla udev para usar el aparato sin `sudo` |
| `rust/` | aplicación final en Rust (en construcción) |

## Estado

- [x] Identificación del aparato, del software y auditoría de seguridad.
- [x] Decompilación completa y documentación del protocolo (tramas, tipos, códigos).
- [x] Prototipo Python (`proto/macrokey.py`) listo para hablar con el aparato.
- [x] **App en Rust** (`rust/`): compila sin avisos, con `list`, `info`, `probe`,
      `key`, `led`, `commit`, `apply <perfil.toml>`, `raw` y `--dry-run`. Las tramas
      que genera son **idénticas byte a byte** a las del prototipo Python.
- [ ] **Validación con el hardware conectado** (pendiente: enchufar el teclado).
- [ ] `dump`/backup de la config actual del teclado (si el firmware lo permite).
- [ ] GUI (solo si el CLI se queda corto).

### App en Rust

```bash
cd rust
cargo build --release                 # binario único, sin dependencias C
./target/release/macrokey list
./target/release/macrokey key /dev/hidraw3 --key 1 --codes C --mods ctrl
./target/release/macrokey apply /dev/hidraw3 --profile profiles/ejemplo.toml
./target/release/macrokey key --dry-run --key 1 --codes A --mods ctrl   # sin hardware
```

`--dry-run` imprime las tramas en hex, así que se puede revisar todo antes de
escribir en la flash del teclado.

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
