//! Transporte HID para Windows.
//!
//! En Linux el canal de configuración se escribe por `/dev/hidraw` o por usbfs;
//! en Windows no existe ninguno de los dos. La vía nativa es la API HID:
//! enumerar las interfaces del aparato con SetupAPI, abrir la colección de la
//! interfaz de configuración y escribirle el informe de salida con `WriteFile`
//! (el primer byte es el **report id**, y el buffer va relleno hasta el tamaño
//! declarado por el descriptor). Es exactamente lo que hace la app del
//! fabricante con HidLibrary.
//!
//! Verificado contra el aparato real: 65 B = 1 (report id 3) + 64 de datos.

#![cfg(windows)]

use std::ffi::c_void;
use std::os::windows::ffi::OsStrExt;
use std::path::PathBuf;

use windows_sys::Win32::Devices::DeviceAndDriverInstallation::{
    SetupDiDestroyDeviceInfoList, SetupDiEnumDeviceInterfaces, SetupDiGetClassDevsW,
    SetupDiGetDeviceInterfaceDetailW, DIGCF_DEVICEINTERFACE, DIGCF_PRESENT,
    SP_DEVICE_INTERFACE_DATA, SP_DEVICE_INTERFACE_DETAIL_DATA_W, SP_DEVINFO_DATA,
};
use windows_sys::Win32::Devices::HumanInterfaceDevice::{HidD_GetHidGuid, HidD_GetProductString, HidD_GetPreparsedData, HidD_FreePreparsedData, HidP_GetCaps, HIDP_CAPS};
use windows_sys::Win32::Foundation::{CloseHandle, GENERIC_READ, GENERIC_WRITE, HANDLE, INVALID_HANDLE_VALUE};
use windows_sys::Win32::Storage::FileSystem::{
    CreateFileW, WriteFile, FILE_ATTRIBUTE_NORMAL, FILE_SHARE_READ, FILE_SHARE_WRITE,
    OPEN_EXISTING,
};

/// Una interfaz HID del aparato, tal como la ve Windows.
#[derive(Clone, Debug)]
pub struct Info {
    /// ruta de la colección, p.ej. `\\?\hid#vid_1189&pid_8890&mi_01#...`
    pub path: String,
    pub vid: u16,
    pub pid: u16,
    /// número de interfaz (`mi_XX` de la ruta; 0 si no aparece)
    pub interface: u8,
    pub product: String,
}

fn ancho(s: &str) -> Vec<u16> {
    std::ffi::OsStr::new(s)
        .encode_wide()
        .chain(std::iter::once(0))
        .collect()
}

/// `mi_07` -> 7 ; sin `mi_` -> 0 (el aparato no tiene interfaces numeradas).
fn interfaz_de_ruta(ruta: &str) -> u8 {
    let baja = ruta.to_ascii_lowercase();
    if let Some(p) = baja.find("&mi_") {
        let hex: String = baja[p + 4..]
            .chars()
            .take_while(|c| c.is_ascii_hexdigit())
            .collect();
        return u8::from_str_radix(&hex, 16).unwrap_or(0);
    }
    0
}

/// VID/PID tal como los escribe Windows en la ruta (`vid_1189&pid_8890`).
fn vid_pid_de_ruta(ruta: &str) -> Option<(u16, u16)> {
    let baja = ruta.to_ascii_lowercase();
    let tras = |clave: &str| -> Option<u16> {
        let p = baja.find(clave)?;
        let hex: String = baja[p + clave.len()..]
            .chars()
            .take_while(|c| c.is_ascii_hexdigit())
            .collect();
        u16::from_str_radix(&hex, 16).ok()
    };
    Some((tras("vid_")?, tras("pid_")?))
}

/// Todas las interfaces HID presentes del VID indicado.
pub fn enumerar(vid: u16) -> Vec<Info> {
    let mut salida = Vec::new();
    unsafe {
        let mut guid = std::mem::zeroed();
        HidD_GetHidGuid(&mut guid);
        let hdev = SetupDiGetClassDevsW(
            &guid,
            std::ptr::null(),
            std::ptr::null_mut(),
            DIGCF_PRESENT | DIGCF_DEVICEINTERFACE,
        );
        // HDEVINFO es isize: INVALID_HANDLE_VALUE se compara como -1
        if hdev == -1 {
            return salida;
        }
        let mut i = 0u32;
        loop {
            let mut datos: SP_DEVICE_INTERFACE_DATA = std::mem::zeroed();
            datos.cbSize = std::mem::size_of::<SP_DEVICE_INTERFACE_DATA>() as u32;
            if SetupDiEnumDeviceInterfaces(hdev, std::ptr::null(), &guid, i, &mut datos) == 0 {
                break;
            }
            i += 1;

            // dos llamadas: la primera pide el tamaño necesario
            let mut necesita = 0u32;
            SetupDiGetDeviceInterfaceDetailW(
                hdev,
                &datos,
                std::ptr::null_mut(),
                0,
                &mut necesita,
                std::ptr::null_mut(),
            );
            if necesita == 0 {
                continue;
            }
            let mut buffer = vec![0u8; necesita as usize];
            let detalle = buffer.as_mut_ptr() as *mut SP_DEVICE_INTERFACE_DETAIL_DATA_W;
            (*detalle).cbSize = std::mem::size_of::<SP_DEVICE_INTERFACE_DETAIL_DATA_W>() as u32;
            if SetupDiGetDeviceInterfaceDetailW(
                hdev,
                &datos,
                detalle,
                necesita,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
            ) == 0
            {
                continue;
            }
            let ancho_buf = &(*detalle).DevicePath as *const u16;
            let len = (0..).take_while(|k| *ancho_buf.add(*k) != 0).count();
            let ruta = String::from_utf16_lossy(std::slice::from_raw_parts(ancho_buf, len));
            let Some((v, p)) = vid_pid_de_ruta(&ruta) else {
                continue;
            };
            if v != vid {
                continue;
            }
            let (product, _) = nombre_producto(&ruta);
            salida.push(Info {
                interface: interfaz_de_ruta(&ruta),
                path: ruta,
                vid: v,
                pid: p,
                product,
            });
        }
        SetupDiDestroyDeviceInfoList(hdev);
    }
    salida
}

/// Nombre del producto (la descripción del canal de configuración suele estar
/// vacía, así que no es grave si falla).
fn nombre_producto(ruta: &str) -> (String, u8) {
    unsafe {
        let h = CreateFileW(
            ancho(ruta).as_ptr(),
            GENERIC_READ,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            std::ptr::null(),
            OPEN_EXISTING,
            FILE_ATTRIBUTE_NORMAL,
            std::ptr::null_mut(),
        );
        if h == INVALID_HANDLE_VALUE {
            return (String::new(), 0);
        }
        let mut buf = [0u16; 128];
        let ok = HidD_GetProductString(h, buf.as_mut_ptr() as *mut c_void, (buf.len() * 2) as u32);
        CloseHandle(h);
        if ok == 0 {
            return (String::new(), 0);
        }
        let len = buf.iter().position(|c| *c == 0).unwrap_or(buf.len());
        (String::from_utf16_lossy(&buf[..len]).trim().to_string(), 0)
    }
}

/// Canal de escritura ya abierto para la interfaz de configuración.
pub struct Salida {
    handle: HANDLE,
    path: PathBuf,
    /// bytes que espera el informe de salida (report id incluido)
    pub out_len: usize,
}

unsafe impl Send for Salida {}

impl Salida {
    /// Abre la colección HID indicada. `out_len` por defecto: 65 = 1 + 64.
    pub fn abrir(ruta: &str) -> Result<Self, String> {
        unsafe {
            let mut handle = CreateFileW(
                ancho(ruta).as_ptr(),
                GENERIC_READ | GENERIC_WRITE,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                std::ptr::null(),
                OPEN_EXISTING,
                FILE_ATTRIBUTE_NORMAL,
                std::ptr::null_mut(),
            );
            if handle == INVALID_HANDLE_VALUE {
                // algunos modelos no dejan abrir para lectura: solo escritura
                handle = CreateFileW(
                    ancho(ruta).as_ptr(),
                    GENERIC_WRITE,
                    FILE_SHARE_READ | FILE_SHARE_WRITE,
                    std::ptr::null(),
                    OPEN_EXISTING,
                    FILE_ATTRIBUTE_NORMAL,
                    std::ptr::null_mut(),
                );
            }
            if handle == INVALID_HANDLE_VALUE {
                return Err(format!("CreateFileW falló en {ruta}"));
            }
            // PHIDP_PREPARSED_DATA es un `isize` en windows-sys (no un puntero)
            let mut preparsed: isize = 0;
            let mut out_len = 65usize;
            if HidD_GetPreparsedData(handle, &mut preparsed) != 0 {
                let mut caps: HIDP_CAPS = std::mem::zeroed();
                if HidP_GetCaps(preparsed, &mut caps) >= 0 && caps.OutputReportByteLength > 0 {
                    out_len = caps.OutputReportByteLength as usize;
                }
                HidD_FreePreparsedData(preparsed);
            }
            Ok(Self {
                handle,
                path: PathBuf::from(ruta),
                out_len,
            })
        }
    }

    pub fn path(&self) -> &PathBuf {
        &self.path
    }

    /// Escribe el informe: primer byte = report id, relleno hasta `out_len`.
    pub fn escribir(&self, report_id: u8, datos: &[u8]) -> Result<(), String> {
        let mut buf = vec![0u8; self.out_len.max(datos.len() + 1)];
        buf[1..1 + datos.len()].copy_from_slice(datos);
        if report_id != 0 {
            buf[0] = report_id;
        }
        let mut escritos = 0u32;
        unsafe {
            let ok = WriteFile(
                self.handle,
                buf.as_ptr() as *const c_void,
                buf.len() as u32,
                &mut escritos,
                std::ptr::null_mut(),
            );
            if ok == 0 {
                return Err("WriteFile falló (¿permisos? ¿la app del fabricante tiene el aparato abierto?)".into());
            }
        }
        if (escritos as usize) != buf.len() {
            return Err(format!("escritos {escritos} de {} bytes", buf.len()));
        }
        Ok(())
    }
}

impl Drop for Salida {
    fn drop(&mut self) {
        unsafe {
            CloseHandle(self.handle);
        }
    }
}
