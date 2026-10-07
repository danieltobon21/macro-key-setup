//! Incrusta el icono y la información de versión en el .exe de Windows.
//!
//! Sólo se compila al construir para Windows (`winres` es una dependencia de
//! build sólo de Windows): usa `rc.exe` (Visual Studio) o `windres` (MinGW) y
//! necesita el .ico de `gui/`.

#[cfg(windows)]
fn main() {
    println!("cargo:rerun-if-changed=../gui/icono-macrokey.ico");
    let mut res = winres::WindowsResource::new();
    res.set_icon("../gui/icono-macrokey.ico");
    res.set("ProductName", "macrokey");
    res.set("FileDescription", "Configurador del teclado macro");
    res.set("LegalCopyright", "Software libre");
    if let Err(e) = res.compile() {
        println!("cargo:warning=no pude incrustar el icono: {e}");
    }
}

#[cfg(not(windows))]
fn main() {}
