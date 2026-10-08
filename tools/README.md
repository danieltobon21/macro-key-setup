# Herramientas

| fichero | para qué |
|---|---|
| `comparar-tramas.py` | compara **byte a byte** las tramas que construye el prototipo Python (`frames`) y las que construye la app Rust (`key --dry-run`). No abre el aparato: es la prueba de regresión del protocolo. `python3 tools/comparar-tramas.py` |

Para ver qué emite realmente el aparato, el monitor del prototipo:

```bash
sudo python3 proto/macrokey.py monitor --all --seconds 600   # con marca de tiempo
```

Las **sondas** que se usaron para descifrar el protocolo (experimentos de escritura
y las pruebas de lectura por el pipe de control) están en `re/tools/`, junto al
resto del material de ingeniería inversa.
