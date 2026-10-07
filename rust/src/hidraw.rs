//! Acceso a HID por /dev/hidraw + sysfs, sin dependencias C (ni libudev ni hidapi).
//!
//! Enumeramos los dispositivos HID cuyo `idVendor` coincide con el del teclado
//! macro y leemos el descriptor de informes desde
//! `/sys/class/hidraw/hidrawN/device/report_descriptor` para saber el tamaño real
//! de cada output report. Es el mismo enfoque que usa el prototipo Python.

use std::collections::BTreeMap;
use std::fs::{self, File, OpenOptions};
use std::io::{self, Write};
use std::path::{Path, PathBuf};

pub const VID_OEM: u16 = 0x1189;
/// PIDs que reconoce la app del fabricante -> (protocolo, new_mul_mouse)
pub const KNOWN_PIDS: &[(u16, u8, bool)] = &[
    (0x8890, 0, false), // interfaz mi_01, trama corta de 8 bytes
    (0x8830, 1, false),
    (0x8831, 1, false),
    (0x8832, 1, false),
    (0x8833, 1, false),
    (0x8834, 1, false),
    (0x8840, 1, true), // "New_Mul_Mouse": mapa de índices distinto
    (0x87D0, 1, false),
];

pub fn known_pid(pid: u16) -> Option<(u8, bool)> {
    KNOWN_PIDS.iter().find(|p| p.0 == pid).map(|p| (p.1, p.2))
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum ReportKind {
    Input,
    Output,
    Feature,
}

#[derive(Debug, Clone)]
pub struct Device {
    pub node: String,       // "hidraw3"
    pub path: PathBuf,      // "/dev/hidraw3"
    pub vid: u16,
    pub pid: u16,
    pub interface: Option<u8>, // bInterfaceNumber (mi_XX)
    pub product: String,
    pub serial: String,
    pub manufacturer: String,
}

impl Device {
    /// Todas las interfaces HID del aparato (puede haber varias).
    /// En Windows no hay sysfs: la enumeración la hace la API HID (SetupAPI).
    #[cfg(windows)]
    pub fn discover(vid: u16) -> io::Result<Vec<Device>> {
        Ok(crate::winhid::enumerar(vid)
            .into_iter()
            .map(|i| Device {
                node: i.path.clone(),
                path: std::path::PathBuf::from(&i.path),
                vid: i.vid,
                pid: i.pid,
                interface: Some(i.interface),
                product: i.product,
                serial: String::new(),
                manufacturer: String::new(),
            })
            .collect())
    }

    #[cfg(not(windows))]
    pub fn discover(vid: u16) -> io::Result<Vec<Device>> {
        let mut out = Vec::new();
        let mut names: Vec<_> = fs::read_dir("/sys/class/hidraw")?
            .filter_map(|e| e.ok())
            .map(|e| e.file_name().to_string_lossy().into_owned())
            .filter(|n| n.starts_with("hidraw"))
            .collect();
        names.sort_by_key(|n| n[6..].parse::<u32>().unwrap_or(0));
        for n in names {
            if let Some(d) = Device::from_sysfs(vid, &n) {
                out.push(d);
            }
        }
        Ok(out)
    }

    /// En Windows la ruta es la de la colección HID; se busca entre las enumeradas.
    #[cfg(windows)]
    pub fn by_path(_vid: u16, path: &str) -> io::Result<Device> {
        let buscado = path.to_ascii_lowercase();
        for i in crate::winhid::enumerar(0) {
            if i.path.to_ascii_lowercase() == buscado || i.path.to_ascii_lowercase().ends_with(&buscado) {
                return Ok(Device {
                    node: i.path.clone(),
                    path: std::path::PathBuf::from(&i.path),
                    vid: i.vid,
                    pid: i.pid,
                    interface: Some(i.interface),
                    product: i.product,
                    serial: String::new(),
                    manufacturer: String::new(),
                });
            }
        }
        Err(io::Error::new(
            io::ErrorKind::NotFound,
            format!("{path}: no encuentro esa colección HID"),
        ))
    }

    #[cfg(not(windows))]
    pub fn by_path(vid: u16, path: &str) -> io::Result<Device> {
        let node = Path::new(path)
            .file_name()
            .map(|s| s.to_string_lossy().into_owned())
            .unwrap_or_else(|| path.to_string());
        Device::from_sysfs(vid, &node).ok_or_else(|| {
            io::Error::new(
                io::ErrorKind::NotFound,
                format!("{path}: no puedo leer la información sysfs de ese hidraw"),
            )
        })
    }

    #[cfg(unix)]
fn from_sysfs(vid: u16, node: &str) -> Option<Device> {
        let sysdir = Path::new("/sys/class/hidraw").join(node);
        // sysdir/device es un enlace simbólico: hay que resolverlo antes de subir
        // por el árbol real del dispositivo USB.
        let base = fs::canonicalize(sysdir.join("device")).ok()?;
        let mut dev = Device {
            node: node.to_string(),
            path: PathBuf::from(format!("/dev/{node}")),
            vid: 0,
            pid: 0,
            interface: None,
            product: String::new(),
            serial: String::new(),
            manufacturer: String::new(),
        };
        for up in base.ancestors() {
            if dev.interface.is_none() {
                // "1-3:1.0" -> bInterfaceNumber = 0
                if let Some(dir) = up.file_name().and_then(|s| s.to_str()) {
                    if let Some(rest) = dir.split(':').nth(1) {
                        if let Some(n) = rest.split('.').nth(1) {
                            dev.interface = n.parse::<u8>().ok();
                        }
                    }
                }
            }
            if let Ok(v) = read_hex(up.join("idVendor")) {
                if v != vid {
                    return None;
                }
                dev.vid = v;
                dev.pid = read_hex(up.join("idProduct")).unwrap_or(0);
                dev.product = read_trim(up.join("product"));
                dev.serial = read_trim(up.join("serial"));
                dev.manufacturer = read_trim(up.join("manufacturer"));
                return Some(dev);
            }
        }
        None
    }

    pub fn open(&self) -> io::Result<File> {
        OpenOptions::new().read(true).write(true).open(&self.path)
    }

    /// Escribe un informe de salida. Si el descriptor declara informes numerados,
    /// el primer byte del buffer es el report id (igual que hace Windows/hidraw).
    pub fn write_report(
        &self,
        numbered: bool,
        report_id: u8,
        data: &[u8],
        out_len: usize,
    ) -> io::Result<usize> {
        let total = out_len + if numbered { 1 } else { 0 };
        let mut buf = vec![0u8; total];
        if numbered {
            buf[0] = report_id;
        }
        let off = if numbered { 1 } else { 0 };
        let n = data.len().min(out_len);
        buf[off..off + n].copy_from_slice(&data[..n]);
        let mut f = self.open()?;
        f.write(&buf)
    }

    pub fn report_descriptor(&self) -> Vec<u8> {
        fs::read(Path::new("/sys/class/hidraw").join(&self.node).join("device/report_descriptor"))
            .unwrap_or_default()
    }

    /// Parser mínimo del descriptor HID: solo los informes Input/Output/Feature.
    pub fn reports(&self) -> BTreeMap<(ReportKind, u8), usize> {
        let d = self.report_descriptor();
        let mut map: BTreeMap<(ReportKind, u8), usize> = BTreeMap::new();
        let mut i = 0usize;
        let (mut report_id, mut size, mut count) = (0u8, 0usize, 0usize);
        while i < d.len() {
            let b = d[i];
            if b == 0xFE {
                // long item: bDataSize, bLongItemTag, data...
                if i + 2 >= d.len() {
                    break;
                }
                i += 3 + d[i + 1] as usize;
                continue;
            }
            let mut len = (b & 0x03) as usize;
            if len == 3 {
                len = 4;
            }
            let itype = (b >> 2) & 0x03;
            let tag = (b >> 4) & 0x0F;
            let data: usize = (0..len)
                .map(|k| (d.get(i + 1 + k).copied().unwrap_or(0) as usize) << (8 * k))
                .sum();
            i += 1 + len;
            match (itype, tag) {
                (1, 7) => size = data,            // Global: Report Size (bits)
                (1, 8) => report_id = data as u8, // Global: Report ID
                (1, 9) => count = data,           // Global: Report Count
                (0, 8) | (0, 9) | (0, 11) => {
                    // Main item: Input(8) / Output(9) / Feature(11)
                    let kind = match tag {
                        8 => ReportKind::Input,
                        9 => ReportKind::Output,
                        _ => ReportKind::Feature,
                    };
                    let bytes = (size * count + 7) / 8;
                    let e = map.entry((kind, report_id)).or_insert(0);
                    if bytes > *e {
                        *e = bytes;
                    }
                }
                _ => {}
            }
        }
        map
    }

    /// ¿el descriptor usa informes numerados? (aparece algún item Report ID)
    pub fn numbered_reports(&self) -> bool {
        let d = self.report_descriptor();
        let mut i = 0usize;
        while i < d.len() {
            let b = d[i];
            if b == 0xFE {
                if i + 2 >= d.len() {
                    break;
                }
                i += 3 + d[i + 1] as usize;
                continue;
            }
            let len = match b & 0x03 {
                3 => 4,
                n => n as usize,
            };
            if (b >> 2) & 0x03 == 1 && (b >> 4) & 0x0F == 8 {
                return true; // Global / Report ID
            }
            i += 1 + len;
        }
        false
    }
}

#[cfg(unix)]
fn read_trim(p: PathBuf) -> String {
    fs::read_to_string(p).unwrap_or_default().trim().to_string()
}

#[cfg(unix)]
fn read_hex(p: PathBuf) -> io::Result<u16> {
    let s = fs::read_to_string(p)?;
    u16::from_str_radix(s.trim().trim_start_matches("0x"), 16)
        .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e.to_string()))
}
