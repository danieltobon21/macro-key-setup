# Herramientas

| fichero | para qué |
|---|---|
| `comparar-tramas.py` | compara **byte a byte** las tramas que construye el prototipo Python (`frames`) y la app Rust (`key --dry-run`). No abre el aparato: es la prueba de regresión del protocolo. `python3 tools/comparar-tramas.py` |
| `experimento-1.py` | escribe en la flash el plan del primer experimento (variantes de combinación, botones de ratón en `[3]`, perilla mute/play/vol+). Documenta cómo se localizaron los campos. |
| `experimento-2.py` | segundo plan: las tres variantes de Ctrl+X, Escape como *detector* de modificador pegado, botones en `[2]`/`[6]` y perilla con códigos distintos. |

Los dos `experimento-*.py` **escriben en la flash** del teclado, así que hay que
ejecutarlos con `sudo` y sabiendo qué configuración queda puesta (el perfil bueno
se reaplica luego con `apply --profile profiles/tinkercad.toml`).

Para ver qué emite realmente el aparato, el monitor del prototipo:

```bash
sudo python3 proto/macrokey.py monitor --all --seconds 600   # con marca de tiempo
```
