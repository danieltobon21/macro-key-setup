//! macrokey — configurador libre para el teclado macro HID VID 0x1189
//! (el que la app del fabricante llama "MINI KeyBoard").
//!
//! Protocolo reconstruido por ingeniería inversa: ver `docs/PROTOCOL.md`.
//! Sin dependencias C: habla con /dev/hidraw y lee el descriptor por sysfs.

mod gui;
mod hidraw;
mod protocol;
#[cfg(unix)]
mod usbfs;
#[cfg(windows)]
mod winhid;

use clap::{Args, Parser, Subcommand};
use hidraw::{Device, ReportKind, VID_OEM};
use protocol::*;
use std::process::ExitCode;
#[cfg(unix)]
use usbfs::UsbfsConfig;

#[derive(Parser, Debug)]
#[command(
    name = "macrokey",
    version,
    about = "Configura el teclado macro (VID 0x1189) sin el software del fabricante",
    long_about = None,
)]
struct Cli {
    /// sin argumentos abre la interfaz gráfica (así funciona el doble clic en Windows)
    #[command(subcommand)]
    cmd: Option<Cmd>,
}

#[derive(Args, Debug)]
struct GuiArgsCli {
    /// perfil TOML que se carga al abrir la ventana
    #[arg(long)]
    profile: Option<String>,
    #[command(flatten)]
    dev: DeviceArgs,
}

#[derive(Args, Debug, Clone)]
struct DeviceArgs {
    /// ruta o nombre del dispositivo: /dev/hidraw3 o hidraw3 (omite para autodetectar)
    device: Option<String>,
    /// report id ("canal") forzado; por defecto se detecta sondeando el aparato
    #[arg(long, global = true)]
    report_id: Option<u8>,
    /// forzar el protocolo (0 = trama corta, 1 = trama larga)
    #[arg(long, global = true, value_parser = clap::value_parser!(u8).range(0..=1))]
    protocol: Option<u8>,
    /// transporte: auto (por defecto), hidraw (/dev/hidrawN) o usbfs (USB directo)
    #[arg(long, global = true, value_parser = ["auto", "hidraw", "usbfs"], default_value = "auto")]
    transport: String,
    /// no escribir nada: solo mostrar las tramas que se enviarían
    #[arg(long, global = true)]
    dry_run: bool,
}

#[derive(Subcommand, Debug)]
enum Cmd {
    /// Enumera los teclados macro conectados (VID 0x1189)
    List,
    /// Muestra VID/PID, interfaz, descriptor y tamaños de los informes
    Info(DeviceArgs),
    /// Sondea el aparato para saber qué report id acepta (versión del firmware)
    Probe(DeviceArgs),
    /// Asigna una tecla: teclado, multimedia, ratón o borrar
    Key(KeyArgs),
    /// Configura el LED (modo + color)
    Led(LedArgs),
    /// Envía el comando de grabado AA AA (solo protocolo 0)
    Commit(DeviceArgs),
    /// Aplica un perfil TOML completo
    Apply(ApplyArgs),
    /// Envía bytes crudos al aparato (depuración)
    Raw(RawArgs),
    /// Abre la interfaz gráfica (por defecto si no se indica nada)
    Gui(GuiArgsCli),
}

#[derive(Args, Debug)]
struct KeyArgs {
    #[command(flatten)]
    dev: DeviceArgs,
    /// tecla: 1..24 (índice del firmware) o knob-left/knob-push/knob-right
    #[arg(long)]
    key: String,
    #[arg(long, default_value_t = 1, value_parser = clap::value_parser!(u8).range(1..=3))]
    layer: u8,
    /// códigos HID separados por coma (A,B,F5,ENTER,KP1…)
    #[arg(long, default_value = "")]
    codes: String,
    /// modificadores unidos por '+' (ctrl+shift+alt+win)
    #[arg(long, default_value = "")]
    mods: String,
    /// acción multimedia
    #[arg(long, value_parser = ["play", "next", "prev", "mute", "volup", "voldown"])]
    media: Option<String>,
    /// acción de ratón
    #[arg(long, value_parser = ["left", "right", "middle", "wheelup", "wheeldown"])]
    mouse: Option<String>,
    /// retardo entre elementos (ms)
    #[arg(long, default_value_t = 0)]
    delay: u16,
    /// borrar la tecla (tipo 0)
    #[arg(long)]
    clear: bool,
}

#[derive(Args, Debug)]
struct LedArgs {
    #[command(flatten)]
    dev: DeviceArgs,
    #[arg(long, default_value_t = 1, value_parser = clap::value_parser!(u8).range(1..=3))]
    layer: u8,
    /// modo 0..5
    #[arg(long, default_value_t = 0, value_parser = clap::value_parser!(u8).range(0..=5))]
    mode: u8,
    /// color
    #[arg(long, default_value = "green",
          value_parser = ["red", "orange", "yellow", "green", "cyan", "blue", "purple"])]
    color: String,
}

#[derive(Args, Debug)]
struct ApplyArgs {
    #[command(flatten)]
    dev: DeviceArgs,
    /// fichero de perfil TOML
    #[arg(long)]
    profile: String,
}

#[derive(Args, Debug)]
struct RawArgs {
    #[command(flatten)]
    dev: DeviceArgs,
    /// bytes en hexadecimal, p.ej. "aa aa 00 00"
    #[arg(long)]
    bytes: String,
}

// ------------------------------------------------------------------ helpers

struct Target {
    transport: Transport,
    pid: u16,
    protocol: u8,
    new_mul_mouse: bool,
    report_id: u8,
    numbered: bool,
    out_len: usize,
}

enum Transport {
    Hidraw(Device),
    #[cfg(unix)]
    Usbfs(UsbfsConfig),
    /// Windows: API HID nativa. `None` = sólo dry-run (no hay aparato abierto).
    #[cfg(windows)]
    WinHid(Option<winhid::Salida>),
}

impl Target {
    fn where_(&self) -> String {
        match &self.transport {
            Transport::Hidraw(d) => d.path.display().to_string(),
            #[cfg(windows)]
            Transport::WinHid(Some(d)) => format!("{} (colección HID)", d.path().display()),
            #[cfg(windows)]
            Transport::WinHid(None) => "(sin aparato: dry-run)".to_string(),
            #[cfg(unix)]
            Transport::Usbfs(c) => format!(
                "{} (interfaz {}, EP 0x{:02x}, transferencias de {} B)",
                c.path.display(),
                c.interface,
                c.endpoint,
                c.transfer_len
            ),
        }
    }

    fn kind(&self) -> &'static str {
        match self.transport {
            Transport::Hidraw(_) => "hidraw",
            #[cfg(unix)]
            Transport::Usbfs(_) => "usbfs",
            #[cfg(windows)]
            Transport::WinHid(_) => "hidapi",
        }
    }
}

fn target(da: &DeviceArgs, need_device: bool) -> Result<Target, String> {
    let devs = Device::discover(VID_OEM).map_err(|e| e.to_string())?;
    let pid = devs.first().map(|d| d.pid);
    let (proto_known, nmm) = pid.and_then(hidraw::known_pid).unwrap_or((1, false));
    let protocol = da.protocol.unwrap_or(proto_known);
    // La interfaz de configuración es mi_01 en los modelos de protocolo 0 (0x8890)
    // y mi_00 en el resto.
    let cfg_iface: u8 = if proto_known == 0 { 1 } else { 0 };

    #[cfg(unix)]
    let find_usbfs = || -> Option<UsbfsConfig> {
        if let Some(p) = pid {
            if let Some(c) = UsbfsConfig::find(VID_OEM, p, cfg_iface) {
                return Some(c);
            }
        }
        for k in hidraw::KNOWN_PIDS {
            let iface = if k.1 == 0 { 1 } else { 0 };
            if let Some(c) = UsbfsConfig::find(VID_OEM, k.0, iface) {
                return Some(c);
            }
        }
        None
    };

    // --- Windows: la API HID es la única vía (no hay /dev/hidraw ni usbfs) ---
    #[cfg(windows)]
    let transport = {
        let elegido = devs.iter().find(|d| d.interface == Some(cfg_iface));
        match elegido {
            Some(d) => Transport::WinHid(Some(winhid::Salida::abrir(&d.path.to_string_lossy())?)),
            None if da.dry_run => Transport::WinHid(None),
            None => {
                return Err(format!(
                    "no encuentro la interfaz de configuración HID (VID 0x{VID_OEM:04x}, mi_{cfg_iface:02x}). \
                     Conecta el teclado y comprueba en el Administrador de dispositivos."
                ))
            }
        }
    };

    // 1) nodo hidraw indicado a mano
    #[cfg(not(windows))]
    let transport = if let Some(p) = &da.device {
        Transport::Hidraw(Device::by_path(VID_OEM, p).map_err(|e| e.to_string())?)
    } else if da.transport != "usbfs" {
        match devs.iter().find(|d| d.interface == Some(cfg_iface)) {
            Some(d) => Transport::Hidraw(d.clone()),
            None => {
                if da.transport == "hidraw" {
                    return Err(
                        "este modelo no expone el canal de configuración como /dev/hidraw; \
                         usa --transport usbfs (USB directo)"
                            .into(),
                    );
                }
                match find_usbfs() {
                    Some(c) => Transport::Usbfs(c),
                    None if da.dry_run => Transport::Hidraw(Device {
                        node: "dryrun".into(),
                        path: std::path::PathBuf::from("/dev/null"),
                        vid: VID_OEM,
                        pid: 0x8830,
                        interface: Some(0),
                        product: "(dry-run)".into(),
                        serial: String::new(),
                        manufacturer: String::new(),
                    }),
                    None => {
                        return Err(format!(
                            "no encuentro el teclado (VID 0x{VID_OEM:04x}). \
                             Conecta el aparato y comprueba `lsusb | grep -i 1189`."
                        ))
                    }
                }
            }
        }
    } else {
        match find_usbfs() {
            Some(c) => Transport::Usbfs(c),
            None if da.dry_run => Transport::Hidraw(Device {
                node: "dryrun".into(),
                path: std::path::PathBuf::from("/dev/null"),
                vid: VID_OEM,
                pid: 0x8830,
                interface: Some(0),
                product: "(dry-run)".into(),
                serial: String::new(),
                manufacturer: String::new(),
            }),
            None => return Err("no encuentro la interfaz de configuración por USB".into()),
        }
    };

    let transport = transport;

    let (numbered, out_len) = match &transport {
        Transport::Hidraw(d) => {
            if need_device && devs.len() > 1 && da.device.is_none() && d.interface != Some(cfg_iface) {
                return Err("hay varias interfaces: indica cuál (/dev/hidrawN)".into());
            }
            let reports = d.reports();
            let len = reports
                .get(&(ReportKind::Output, da.report_id.unwrap_or(3)))
                .or_else(|| reports.get(&(ReportKind::Output, 0)))
                .copied()
                .unwrap_or(if protocol == 1 { LONG_FRAME_LEN } else { SHORT_FRAME_LEN });
            (d.numbered_reports(), len)
        }
        #[cfg(unix)]
        Transport::Usbfs(c) => (false, c.transfer_len),
        #[cfg(windows)]
        Transport::WinHid(Some(d)) => (true, d.out_len),
        #[cfg(windows)]
        Transport::WinHid(None) => (true, SHORT_FRAME_LEN + 1),
    };

    // Igual que el original (KeyBoardVersion_Check): si no nos fuerzan un report id,
    // probamos 3 -> 0 -> 2 (el descriptor de la interfaz de configuración declara el 3).
    let report_id = match da.report_id {
        Some(r) => r,
        None => 3,
    };

    Ok(Target {
        transport,
        pid: pid.unwrap_or(0),
        protocol,
        new_mul_mouse: nmm,
        report_id,
        numbered,
        out_len,
    })
}

impl Target {
    fn send(&mut self, data: &[u8], dry_run: bool, label: &str) -> Result<(), String> {
        let shown: Vec<String> = data.iter().take(24).map(|b| format!("{b:02x}")).collect();
        if dry_run {
            println!(
                "[dry-run] {label}: id={} {} bytes -> {}",
                self.report_id,
                data.len(),
                shown.join(" ")
            );
            return Ok(());
        }
        let res = match &mut self.transport {
            Transport::Hidraw(dev) => {
                dev.write_report(self.numbered, self.report_id, data, self.out_len)
            }
            #[cfg(windows)]
            Transport::WinHid(Some(dev)) => dev
                .escribir(self.report_id, data)
                .map(|_| data.len())
                .map_err(|e| std::io::Error::other(e)),
            #[cfg(windows)]
            Transport::WinHid(None) => Err(std::io::Error::other(
                "no hay aparato abierto (dry-run)",
            )),
            #[cfg(unix)]
            Transport::Usbfs(cfg) => {
                if !cfg.is_open() {
                    cfg.open()
                        .map_err(|e| format!("no puedo abrir/reclamar {}: {e}", cfg.path.display()))?;
                }
                let mut payload = Vec::with_capacity(data.len() + 1);
                payload.push(self.report_id);
                payload.extend_from_slice(data);
                cfg.write(&payload)
            }
        };
        match res {
            Ok(n) => {
                println!("{label}: {n} bytes escritos");
                Ok(())
            }
            Err(e) => Err(format!("{label}: error de escritura: {e}")),
        }
    }

    fn commit_keys(&mut self, dry_run: bool) -> Result<(), String> {
        self.send(&CMD_WRITE_FLASH, dry_run, "grabar (AA AA)")
    }

    fn commit_led(&mut self, dry_run: bool) -> Result<(), String> {
        self.send(&CMD_WRITE_LED, dry_run, "grabar LED (AA A1)")
    }

    /// Escribe una tecla y, si el protocolo lo requiere, confirma la grabación.
    fn set_key(
        &mut self,
        index: u8,
        layer: u8,
        key_type: u8,
        steps: &[Step],
        delay_ms: u16,
        dry_run: bool,
    ) -> Result<(), String> {
        println!(
            "tecla {index} ({}), capa {layer}, tipo {key_type}, protocolo {}",
            self.where_(),
            self.protocol
        );
        if self.protocol == 1 {
            let f = long_frame(
                index,
                layer,
                key_type,
                steps,
                delay_ms,
                self.new_mul_mouse,
                self.report_id,
            );
            self.send(&f, dry_run, "trama larga")?;
            // El original NO manda AA AA en el protocolo 1: la propia trama 0xFE
            // deja la tecla grabada.
        } else {
            // El original cambia de capa antes de escribir en el protocolo corto.
            self.send(&sw_layer_frame(layer), dry_run, "cambiar capa")?;
            for f in short_frames(
                index,
                layer,
                key_type,
                steps,
                self.report_id,
                self.new_mul_mouse,
            ) {
                self.send(&f, dry_run, "trama corta")?;
            }
            self.commit_keys(dry_run)?;
        }
        Ok(())
    }
}

// ----------------------------------------------------------------- comandos

fn cmd_list() -> Result<(), String> {
    let devs = Device::discover(VID_OEM).map_err(|e| e.to_string())?;
    let mut found = !devs.is_empty();
    for d in devs {
        let kp = hidraw::known_pid(d.pid);
        println!(
            "{}  {:04x}:{:04x}  interfaz={:?}  protocolo={:?}  {}",
            d.path.display(),
            d.vid,
            d.pid,
            d.interface,
            kp.map(|k| k.0),
            if d.product.is_empty() {
                "-".to_string()
            } else {
                d.product.clone()
            }
        );
        if !d.serial.is_empty() || !d.manufacturer.is_empty() {
            println!("    fabricante={:?} serial={:?}", d.manufacturer, d.serial);
        }
    }
    // Interfaz de configuración por USB directo (no aparece como /dev/hidraw).
    #[cfg(unix)]
    for k in hidraw::KNOWN_PIDS {
        let iface = if k.1 == 0 { 1 } else { 0 };
        if let Some(c) = UsbfsConfig::find(VID_OEM, k.0, iface) {
            found = true;
            println!(
                "{}  {:04x}:{:04x}  interfaz de configuración={} (EP 0x{:02x}, \
                 transferencias de {} B)  protocolo={}  [transporte usbfs]",
                c.path.display(),
                VID_OEM,
                k.0,
                c.interface,
                c.endpoint,
                c.transfer_len,
                k.1
            );
        }
    }
    if !found {
        println!("Sin dispositivos VID 0x{VID_OEM:04x} conectados.");
        println!("Conecta el teclado macro (y comprueba `lsusb | grep -i 1189`).");
    }
    Ok(())
}

fn cmd_info(da: DeviceArgs) -> Result<(), String> {
    let t = target(&da, false)?;
    println!("transporte: {}   destino: {}", t.kind(), t.where_());
    println!(
        "VID:PID {:04x}:{:04x}  protocolo={}  new_mul_mouse={}  report id={}",
        VID_OEM, t.pid, t.protocol, t.new_mul_mouse, t.report_id
    );
    match &t.transport {
        Transport::Hidraw(d) => {
            println!("interfaz USB {:?}  informes numerados: {}", d.interface, t.numbered);
            for ((kind, id), bytes) in d.reports() {
                println!("  {:?} id={} {} bytes de datos", kind, id, bytes);
            }
            let desc = d.report_descriptor();
            let hex: Vec<String> = desc.iter().take(48).map(|b| format!("{b:02x}")).collect();
            println!("descriptor: {} ... ({} bytes)", hex.join(" "), desc.len());
        }
        #[cfg(windows)]
        Transport::WinHid(d) => match d {
            Some(dev) => println!(
                "colección HID de configuración: {}\n(en Windows se escribe por la API HID: \
                 informe de {} B con el report id delante)",
                dev.path().display(),
                dev.out_len
            ),
            None => println!("(sin aparato: dry-run)"),
        },
        #[cfg(unix)]
        Transport::Usbfs(c) => {
            println!(
                "canal de configuración: interfaz {} (HID vendor-defined, Report ID 3), \
                 EP 0x{:02x} de interrupción, transferencias de {} B = [id]+datos",
                c.interface, c.endpoint, c.transfer_len
            );
            println!("(esta interfaz no tiene endpoint de entrada, así que el núcleo no la \
                      expone como /dev/hidraw: por eso se escribe por USB directo)");
        }
    }
    Ok(())
}

fn cmd_probe(da: DeviceArgs) -> Result<(), String> {
    let mut t = target(&da, false)?;
    println!(
        "{}: {:04x}:{:04x}  transporte={}  protocolo={}",
        t.where_(),
        VID_OEM,
        t.pid,
        t.kind(),
        t.protocol
    );
    if t.kind() == "usbfs" || t.kind() == "hidapi" {
        println!("el descriptor de la interfaz de configuración declara Report ID 3");
        t.send(&[0u8; 8], da.dry_run, "sondeo (trama de ceros)")?;
        return Ok(());
    }
    let mut ok = Vec::new();
    let reps = match &t.transport {
        Transport::Hidraw(d) => d.reports(),
        #[cfg(windows)]
        Transport::WinHid(_) => Default::default(),
        #[cfg(unix)]
        Transport::Usbfs(_) => Default::default(),
    };
    for rid in [3u8, 0, 2] {
        let out_len = reps
            .get(&(ReportKind::Output, rid))
            .or_else(|| reps.get(&(ReportKind::Output, 0)))
            .copied()
            .unwrap_or(8);
        let zeros = [0u8; 8];
        match &mut t.transport {
            Transport::Hidraw(dev) => {
                if da.dry_run {
                    println!("[dry-run] sondear id={rid} ({out_len} bytes)");
                    continue;
                }
                match dev.write_report(t.numbered, rid, &zeros, out_len) {
                    Ok(n) if n > 0 => {
                        println!("  report id {rid}: ACEPTADO ({n} bytes)");
                        ok.push(rid);
                    }
                    Ok(_) => println!("  report id {rid}: rechazado"),
                    Err(e) => println!("  report id {rid}: error {e}"),
                }
            }
            #[cfg(windows)]
            Transport::WinHid(_) => {
                println!("  report id {rid}: (en Windows se escribe con el id detectado)")
            }
            #[cfg(unix)]
            Transport::Usbfs(_) => {}
        }
    }
    if !ok.is_empty() {
        println!("report id a usar: {}", ok[0]);
    }
    Ok(())
}

fn cmd_key(a: KeyArgs) -> Result<(), String> {
    let mut t = target(&a.dev, true)?;
    let index = key_index(&a.key, t.new_mul_mouse)
        .ok_or_else(|| format!("índice de tecla desconocido: {}", a.key))?;

    let binding = Binding {
        key: a.key.clone(),
        layer: a.layer,
        clear: a.clear,
        codes: if a.codes.is_empty() {
            vec![]
        } else {
            a.codes.split(',').map(|s| s.trim().to_string()).collect()
        },
        mods: if a.mods.is_empty() {
            vec![]
        } else {
            a.mods.split('+').map(|s| s.trim().to_string()).collect()
        },
        media: a.media.clone(),
        mouse: a.mouse.clone(),
        delay_ms: a.delay,
    };
    let (key_type, steps) = steps_for(&binding, t.report_id)?;
    if key_type == TYPE_KEY && steps.is_empty() {
        return Err("indica --codes, --media, --mouse o --clear".into());
    }
    t.set_key(index, a.layer, key_type, &steps, a.delay, a.dev.dry_run)
}

fn cmd_led(a: LedArgs) -> Result<(), String> {
    let mut t = target(&a.dev, true)?;
    let color = led_color(&a.color).ok_or_else(|| format!("color desconocido: {}", a.color))?;
    if t.protocol == 1 {
        let f = led_long_frame(a.layer, color, a.mode);
        t.send(&f, a.dev.dry_run, "LED (trama larga)")?;
    } else {
        t.send(&sw_layer_frame(a.layer), a.dev.dry_run, "cambiar capa")?;
        t.send(
            &led_short_frame(a.layer, color, a.mode),
            a.dev.dry_run,
            "LED (trama corta)",
        )?;
        t.commit_led(a.dev.dry_run)?;
    }
    println!(
        "LED: capa {}, modo {}, color {} (0x{:02x})",
        a.layer,
        a.mode,
        a.color,
        (color << 4) | (a.mode & 0x0F)
    );
    Ok(())
}

fn cmd_commit(da: DeviceArgs) -> Result<(), String> {
    let mut t = target(&da, true)?;
    t.commit_keys(da.dry_run)
}

fn cmd_apply(a: ApplyArgs) -> Result<(), String> {
    let mut t = target(&a.dev, true)?;
    let text = std::fs::read_to_string(&a.profile)
        .map_err(|e| format!("no puedo leer {}: {e}", a.profile))?;
    let profile = parse_profile(&text).map_err(|e| format!("perfil inválido: {e}"))?;
    if !profile.name.is_empty() {
        println!("perfil: {}", profile.name);
    }
    if let Some(l) = &profile.led {
        let color = led_color(&l.color).ok_or_else(|| format!("color desconocido: {}", l.color))?;
        if t.protocol == 1 {
            let f = led_long_frame(l.layer, color, l.mode);
            t.send(&f, a.dev.dry_run, "LED")?;
        } else {
            t.send(&sw_layer_frame(l.layer), a.dev.dry_run, "cambiar capa")?;
            t.send(&led_short_frame(l.layer, color, l.mode), a.dev.dry_run, "LED")?;
            t.commit_led(a.dev.dry_run)?;
        }
    }
    for b in &profile.bindings {
        let index = key_index(&b.key, t.new_mul_mouse)
            .ok_or_else(|| format!("índice de tecla desconocido: {}", b.key))?;
        let (key_type, steps) = steps_for(b, t.report_id)?;
        t.set_key(index, b.layer, key_type, &steps, b.delay_ms, a.dev.dry_run)?;
    }
    println!("{} asignaciones aplicadas", profile.bindings.len());
    Ok(())
}

fn cmd_raw(a: RawArgs) -> Result<(), String> {
    let mut t = target(&a.dev, true)?;
    let data: Result<Vec<u8>, _> = a
        .bytes
        .split([' ', ','])
        .filter(|s| !s.is_empty())
        .map(|s| u8::from_str_radix(s.trim_start_matches("0x"), 16))
        .collect();
    let data = data.map_err(|e| format!("bytes inválidos: {e}"))?;
    t.send(&data, a.dev.dry_run, "crudo")
}

fn main() -> ExitCode {
    let cli = Cli::parse();
    let res = match cli.cmd {
        None => {
            // doble clic en Windows: fuera la ventana de consola
            #[cfg(windows)]
            winhid::ocultar_consola();
            gui::run(gui::GuiArgs {
            profile: None,
            dev: DeviceArgs {
                device: None,
                report_id: None,
                protocol: None,
                transport: "auto".to_string(),
                dry_run: false,
            })
        }
        Some(Cmd::Gui(a)) => {
            #[cfg(windows)]
            winhid::ocultar_consola();
            gui::run(gui::GuiArgs {
                profile: a.profile,
                dev: a.dev,
            })
        }
        Some(Cmd::List) => cmd_list(),
        Some(Cmd::Info(a)) => cmd_info(a),
        Some(Cmd::Probe(a)) => cmd_probe(a),
        Some(Cmd::Key(a)) => cmd_key(a),
        Some(Cmd::Led(a)) => cmd_led(a),
        Some(Cmd::Commit(a)) => cmd_commit(a),
        Some(Cmd::Apply(a)) => cmd_apply(a),
        Some(Cmd::Raw(a)) => cmd_raw(a),
    };
    match res {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("error: {e}");
            ExitCode::FAILURE
        }
    }
}
