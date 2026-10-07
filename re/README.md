# Carpeta `re/` — ingeniería inversa

Aquí está **lo que sí se publica**: las herramientas y las tablas de datos que
extraje del software del fabricante (`MINI KeyBoard.exe`, namespace `HIDTester`).

| ruta | qué es |
|---|---|
| `tools/extract_tables.py` | extractor que lee el C# decompilado y genera las tablas de códigos |
| `tables/keytables.json` | las tablas en formato máquina (100 teclas + modificadores + multimedia + ratón) |
| `tables/keytables.md` | las mismas tablas legibles |

## Lo que deliberadamente NO se publica

- **Los binarios del fabricante** (`MINI KeyBoard.exe`, `HidLibrary.dll`,
  `Theraot.Core.dll`, `*.pdb`): no son míos y no tienen licencia que permita
  redistribuirlos.
- **El código C# decompilado** (`re/decompiled/`, `re/hidlibrary/`): es obra
  derivada de ese binario. Se queda en local como referencia para la ingeniería
  inversa; el repositorio publica solo la **especificación** del protocolo
  (`docs/PROTOCOL.md`), que es lo que hace posible nuestra implementación.

Si algún día hace falta justificar el formato del protocolo byte a byte, el
código decompilado se puede regenerar en minutos con las instrucciones de abajo.

## Cómo reproducir la decompilación (local)

```bash
# 1) herramienta (una sola vez)
sudo dnf install -y dotnet-sdk-9.0
DOTNET_CLI_TELEMETRY_OPTOUT=1 dotnet tool install -g ilspycmd --version 9.1.0.7988
export DOTNET_ROLL_FORWARD=LatestMajor     # el tool pide net8; con el runtime 9 basta

# 2) decompilar (la carpeta del fabricante, en el escritorio/compartida)
~/.dotnet/tools/ilspycmd -p -o re/decompiled "MINI KeyBoard.exe"
~/.dotnet/tools/ilspycmd -p -o re/hidlibrary HidLibrary.dll

# 3) regenerar las tablas
python3 re/tools/extract_tables.py re/decompiled/HIDTester re/tables
```

Notas por si vuelve a hacer falta:

- `ilspycmd` **sin `--version`** falla: la última versión exige .NET 10 y casca con
  *"DotnetToolSettings.xml no encontrado"*. Fijar `9.1.0.7988`.
- Los avisos `//IL_...: Unknown result type` que salen en el código con WinForms son
  cosméticos.
- El binario traía **sus PDB**, así que el C# recuperado es prácticamente el fuente
  original (sin ofuscación). De ahí salió `docs/PROTOCOL.md`.
