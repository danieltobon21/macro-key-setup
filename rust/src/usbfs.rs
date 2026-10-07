//! Canal de configuración por USB directo (usbfs).
//!
//! El canal de configuración de estos teclados es una interfaz HID que declara
//! informes de 64 bytes con Report ID (el nuestro usa el 3) y **solo un endpoint
//! OUT** (EP 0x02, interrupción, 64 bytes). Al no tener endpoint de entrada,
//! `usbhid` no la enlaza y NO existe `/dev/hidraw` para ella: hay que hablar con
//! el dispositivo directamente por `/dev/bus/usb/BBB/DDD`, reclamando la interfaz
//! y enviando URBs de interrupción.
//!
//! Se implementa con `ioctl` (USBDEVFS_*) sin libusb: es lo mismo que hace
//! libusb por dentro, pero sin dependencia C adicional.

use std::fs::{self, File, OpenOptions};
use std::io;
use std::os::unix::io::AsRawFd;
use std::path::{Path, PathBuf};

const USBDEVFS_URB_TYPE_INTERRUPT: u8 = 1;
const IOC_NONE: u32 = 0;
const IOC_WRITE: u32 = 1;
const IOC_READ: u32 = 2;

const fn ioc(dir: u32, ty: u8, nr: u8, size: u32) -> u64 {
    ((dir as u64) << 30) | ((size as u64) << 16) | ((ty as u64) << 8) | (nr as u64)
}

const USBDEVFS_SUBMITURB: u64 = ioc(IOC_READ, b'U', 10, 56);
const USBDEVFS_DISCARDURB: u64 = ioc(IOC_NONE, b'U', 11, 0);
const USBDEVFS_REAPURB: u64 = ioc(IOC_WRITE, b'U', 12, 8);
const USBDEVFS_CLAIMINTERFACE: u64 = ioc(IOC_READ, b'U', 15, 4);
const USBDEVFS_RELEASEINTERFACE: u64 = ioc(IOC_READ, b'U', 16, 4);

/// `struct usbdevfs_urb` del núcleo (mismo orden que en <linux/usbdevice_fs.h>).
#[repr(C)]
#[derive(Debug)]
struct UsbdevfsUrb {
    type_: u8,
    endpoint: u8,
    status: i32,
    flags: u32,
    buffer: *mut u8,
    buffer_length: i32,
    actual_length: i32,
    start_frame: i32,
    number_of_packets_or_stream_id: i32,
    error_count: i32,
    signr: u32,
    usercontext: *mut std::ffi::c_void,
}

unsafe fn ioctl_ptr(fd: i32, request: u64, arg: *mut std::ffi::c_void) -> io::Result<i32> {
    let rc = unsafe { libc::ioctl(fd, request as libc::c_ulong, arg) };
    if rc < 0 {
        Err(io::Error::last_os_error())
    } else {
        Ok(rc)
    }
}

/// Interfaz de configuración del teclado accesible por USB directo.
#[derive(Debug)]
pub struct UsbfsConfig {
    pub interface: u8,
    pub endpoint: u8,
    /// bytes por transferencia: 1 (report id) + informe declarado
    pub transfer_len: usize,
    pub path: PathBuf,
    file: Option<File>,
}

impl UsbfsConfig {
    /// Busca el dispositivo USB con ese VID:PID y se queda con la interfaz dada.
    pub fn find(vid: u16, pid: u16, interface: u8) -> Option<UsbfsConfig> {
        let base = Path::new("/sys/bus/usb/devices");
        let mut dirs: Vec<_> = fs::read_dir(base).ok()?.filter_map(|e| e.ok()).collect();
        dirs.sort_by_key(|e| e.file_name());
        for d in dirs {
            let p = d.path();
            // OJO: casi ningún directorio de /sys/bus/usb/devices tiene idVendor
            // (los hay de hubs, interfaces, etc.), así que nada de `?` aquí: hay
            // que ignorar los que no lo tengan y seguir buscando.
            let (v, prod) = match (
                fs::read_to_string(p.join("idVendor")),
                fs::read_to_string(p.join("idProduct")),
            ) {
                (Ok(v), Ok(prod)) => (v, prod),
                _ => continue,
            };
            if v.trim().to_ascii_lowercase() != format!("{vid:04x}")
                || prod.trim().to_ascii_lowercase() != format!("{pid:04x}")
            {
                continue;
            }
            let bus = fs::read_to_string(p.join("busnum"))
                .ok()
                .and_then(|s| s.trim().parse::<u8>().ok());
            let addr = fs::read_to_string(p.join("devnum"))
                .ok()
                .and_then(|s| s.trim().parse::<u8>().ok());
            let (bus, addr) = match (bus, addr) {
                (Some(b), Some(a)) => (b, a),
                _ => continue,
            };
            return Some(UsbfsConfig {
                interface,
                endpoint: 0x02,
                transfer_len: 65,
                path: PathBuf::from(format!("/dev/bus/usb/{bus:03}/{addr:03}")),
                file: None,
            });
        }
        None
    }

    pub fn is_open(&self) -> bool {
        self.file.is_some()
    }

    pub fn open(&mut self) -> io::Result<()> {
        let file = OpenOptions::new().read(true).write(true).open(&self.path)?;
        let fd = file.as_raw_fd();
        let mut ifnum: libc::c_uint = self.interface as libc::c_uint;
        // La interfaz no la tiene ningún driver del núcleo, así que se puede reclamar.
        match unsafe {
            ioctl_ptr(
                fd,
                USBDEVFS_CLAIMINTERFACE,
                &mut ifnum as *mut libc::c_uint as *mut std::ffi::c_void,
            )
        } {
            Ok(_) => {
                self.file = Some(file);
                Ok(())
            }
            Err(e) => Err(e),
        }
    }

    pub fn close(&mut self) {
        if let Some(file) = self.file.take() {
            let fd = file.as_raw_fd();
            let mut ifnum: libc::c_uint = self.interface as libc::c_uint;
            unsafe {
                let _ = ioctl_ptr(
                    fd,
                    USBDEVFS_RELEASEINTERFACE,
                    &mut ifnum as *mut libc::c_uint as *mut std::ffi::c_void,
                );
            }
        }
    }

    /// Envía un informe por el endpoint de interrupción y espera a que complete.
    pub fn write(&self, data: &[u8]) -> io::Result<usize> {
        let file = self
            .file
            .as_ref()
            .ok_or_else(|| io::Error::new(io::ErrorKind::NotConnected, "UsbfsConfig sin open()"))?;
        let fd = file.as_raw_fd();
        let mut buf = vec![0u8; self.transfer_len];
        let n = data.len().min(self.transfer_len);
        buf[..n].copy_from_slice(&data[..n]);

        let mut urb = UsbdevfsUrb {
            type_: USBDEVFS_URB_TYPE_INTERRUPT,
            endpoint: self.endpoint,
            status: 0,
            flags: 0,
            buffer: buf.as_mut_ptr(),
            buffer_length: self.transfer_len as i32,
            actual_length: 0,
            start_frame: 0,
            number_of_packets_or_stream_id: 0,
            error_count: 0,
            signr: 0,
            usercontext: std::ptr::null_mut(),
        };

        let submitted = unsafe {
            ioctl_ptr(
                fd,
                USBDEVFS_SUBMITURB,
                &mut urb as *mut UsbdevfsUrb as *mut std::ffi::c_void,
            )
        };
        if let Err(e) = submitted {
            return Err(e);
        }
        let mut slot: *mut UsbdevfsUrb = std::ptr::null_mut();
        let reaped = unsafe {
            ioctl_ptr(
                fd,
                USBDEVFS_REAPURB,
                &mut slot as *mut *mut UsbdevfsUrb as *mut std::ffi::c_void,
            )
        };
        if let Err(e) = reaped {
            unsafe {
                let _ = ioctl_ptr(
                    fd,
                    USBDEVFS_DISCARDURB,
                    &mut urb as *mut UsbdevfsUrb as *mut std::ffi::c_void,
                );
            }
            return Err(e);
        }
        if urb.status != 0 {
            return Err(io::Error::new(
                io::ErrorKind::Other,
                format!("URB completado con error ({})", urb.status),
            ));
        }
        Ok(urb.actual_length.max(0) as usize)
    }
}

impl Drop for UsbfsConfig {
    fn drop(&mut self) {
        self.close();
    }
}
