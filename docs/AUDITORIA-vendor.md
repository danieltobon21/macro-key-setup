# Auditoría de la app del fabricante — "MINI KeyBoard"

Fecha del análisis: 2026-10-07 · Analista: Hermes (perfil `default`, host VPS + laptop Fedora)

## Veredicto corto

**No es malware.** Es una herramienta OEM china, cutre pero inocua: una GUI
WinForms de 2013 (compilada en 2023) que habla HID con el teclado y nada más.
No hay red, ni persistencia, ni escalada de privilegios, ni ofuscación.
El riesgo real no es que te espíe: es que es **software cerrado, sin firma, de
autor desconocido, que escribe en la flash de tu hardware y no verifica nada de
lo que escribe**. Motivo más que suficiente para reescribirlo — que es lo que
estamos haciendo.

## Qué es exactamente

| | |
|---|---|
| Fichero | `MINI KeyBoard.exe` (253 440 bytes) |
| SHA-256 | `f7bedb3cc7c87a671cc6c579b4158e914269b14fb9392205fa40283064785d28` |
| SHA-256 copia ClickOnce (`app.publish/`) | idéntica |
| Tipo | PE32 GUI, ensamblado .NET Framework 4.0 (CLR v4.0.30319), x86 (`processorArchitecture="x86"`), WinForms |
| Namespace / ensamblado | `HIDTester` / `MINI KeyBoard` v1.0.0.2 (v1.0.0.0 interno) |
| Compilado | **2023-07-13 17:11 UTC** |
| Empaquetado | ClickOnce (`MINI KeyBoard.application`), instalación local |
| Firma digital | **NINGUNA** (sin tabla de certificados Authenticode; `publicKeyToken=0000000000000000`) |
| Distribución | sin `deploymentProvider` → **no** tiene URL de auto-actualización |
| Privilegios pedidos | `requestedExecutionLevel level="asInvoker"` → **no pide administrador** |
| Autoría | rutas de compilación `C:\Users\Administrator\Desktop\C#上位机统一协议\` ("protocolo unificado de PC de control, C#") |
| Idiomas empaquetados | `en-US`, `zh-CN`, `zh-Hans` |
| Fecha del `errorLog.txt` incluido | 2023-07-14 (un crash `InvalidOperationException` al cerrar: bug cosmético del autor) |

## Dependencias (las tres son legítimas y de código abierto)

| DLL | SHA-256 | Origen |
|---|---|---|
| `HidLibrary.dll` (45 056 B) | `8bafd3e1c6f88822dbf738c929f7d3162d08243067c69c4a85e52ed13a78d12b` | **HidLibrary** de Mike O'Brien — MIT. La PDB embebida delata la ruta: `C:\Users\Administrator\Desktop\HidLibrary-master\...\HidLibrary.pdb` → el autor **compiló la librería tal cual desde GitHub**, sin tocarla |
| `Theraot.Core.dll` (787 968 B) | `4406b6affde4fbec5c47aed24d0050c0148d94772d3f2c11e6c96ce2ad527799` | **Theraot.Core** ([github.com/theraot/Theraot](https://github.com/theraot/theraot)) — MIT, librería de *polyfills* de .NET. Compilada en 2017, es la versión de NuGet sin modificar |
| `*resources.dll` | — | solo traducciones de la UI (en-US / zh-CN / zh-Hans) |

Referencias del propio `.exe` (metadata del ensamblado): `mscorlib`, `System`,
`System.Core`, `System.Drawing`, `System.Windows.Forms`, `System.Configuration`,
`HidLibrary`, `Theraot.Core`.

## Comprobaciones de seguridad una a una

| comprobación | resultado |
|---|---|
| ¿Llamadas de red? (`HttpClient`, `WebClient`, `Socket`, `WebRequest`, `DownloadFile`, `Dns`) | **NINGUNA**. El único `http` de todo el binario es un enlace de ayuda (`Process.Start("http://www.cnblogs.com/hebaichuanyeah/p/4504855.html")`, un blog chino sobre HID, en el menú *About*) |
| ¿Escrituras en disco? | Solo `File.WriteAllText(Application.StartupPath + "\errorLog.txt", ...)` en el manejador de excepciones (Program.cs:30/45/56) |
| ¿Registro de Windows? | **NINGUNA** llamada (`Microsoft.Win32.Registry` no aparece; el único `Registry` es un `SetupDiGetDeviceRegistryProperty` de setupapi, que es enumeración de HID) |
| ¿Persistencia? (Run keys, servicios, tareas programadas, WMI, startup) | **NINGUNA** |
| ¿Inyección / ejecución de comandos? (`cmd`, `powershell`, `ShellExecute`, `Assembly.Load`) | **NINGUNA** |
| ¿Criptografía, empaquetado, `base64`, ofuscación? | **NINGUNA**. Los nombres de tipos/métodos están intactos y hay PDBs con números de línea → código original recuperado |
| ¿P/Invoke sospechoso? | Solo lo esperable en HID: `hid.dll` (HidD_GetAttributes, HidD_GetPreparsedData, HidD_GetSerialNumberString…), `setupapi.dll` (enumeración de dispositivos), `kernel32.dll` (CreateFile/ReadFile/WriteFile/CloseHandle), `user32.dll` (`SetProcessDPIAware`) |
| ¿Pide administrador? | No (`asInvoker`) |
| ¿Autoupdate? | No (no hay `deploymentProvider` en el manifiesto ClickOnce) |
| ¿Firma del autor? | No hay ninguna (ni Authenticode ni clave de ensamblado: `publicKeyToken=0`) |

## Superficie de ataque real que sí existe

1. **No está firmada y no se puede auditar desde el fichero**: si el autor
   publica otra compilación, nadie verifica nada. ClickOnce desde un sitio
   HTTP permitiría sustituir el binario.
2. **Escribe en la flash del dispositivo a ciegas**: no hay lectura de vuelta
   ni verificación (`myhid_DataReceived` recibe datos y **nunca los interpreta**).
   Una trama mal formada puede dejar el teclado con teclas "pegadas" (por eso
   reimplementamos el formato byte a byte, no "a ojo").
3. **Bug de cierre**: el `errorLog.txt` incluido muestra una excepción al cerrar
   (`Dispose()` durante `CreateHandle()`), corregida por nosotros de raíz al no
   usar WinForms.
4. **Riesgo de cadena de suministro**: el instalador se descarga de un sitio sin
   HTTPS ni firma. Nuestra versión compila desde fuente y no depende de terceros.

## Conclusión

Puedes seguir usando la app del fabricante mientras desarrollamos la nuestra:
lo que hace es exactamente lo que dice el protocolo documentado en
[`PROTOCOL.md`](PROTOCOL.md), sin sorpresas. Pero no hay ningún motivo para
depender de ella: el formato ya está reconstruido íntegro y una herramienta
propia elimina los puntos 1–4 de arriba.
