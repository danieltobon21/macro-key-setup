//! Interfaz gráfica (egui) del configurador del teclado macro.
//!
//! Se apoya en el mismo protocolo y el mismo transporte que el CLI: la ventana
//! solo construye `Binding`s y llama a `Target::set_key`, así que la GUI y el
//! CLI no pueden divergir.
//!
//! Paleta: la de la casa para programas abiertos (`tobon-app-identity`):
//! fondo `#181A1F`, claro `#ECEEF2`, acento `#FF5A1F`.
//!
//! El aparato se dibuja con las medidas reales del teclado del usuario
//! (100 × 60 mm, teclas 18 × 17 mm, perilla ⌀ 20 mm), a 6 px por mm: las teclas
//! físicas vienen en negro sin leyenda, así que la pantalla es la única
//! referencia de qué hace cada una.

use eframe::egui;
use egui::{Align2, Color32, CornerRadius, FontId, Rect, Sense, Stroke, Vec2};

use crate::hidraw::{Device, VID_OEM};
use crate::protocol::*;
use crate::{target, DeviceArgs};

// ---------------------------------------------------------------- paleta
const FONDO_APP: Color32 = Color32::from_rgb(0x18, 0x1A, 0x1F);
const PANEL: Color32 = Color32::from_rgb(0x1C, 0x1F, 0x26);
const LINEA: Color32 = Color32::from_rgb(0x34, 0x3A, 0x45);
const CLARO: Color32 = Color32::from_rgb(0xEC, 0xEE, 0xF2);
const GRIS: Color32 = Color32::from_rgb(0x9A, 0xA2, 0xB1);
const NARANJA: Color32 = Color32::from_rgb(0xFF, 0x5A, 0x1F);
const CUERPO: Color32 = Color32::from_rgb(0x0E, 0x0F, 0x12);
const PLACA: Color32 = Color32::from_rgb(0x15, 0x16, 0x1A);
const TECLA: Color32 = Color32::from_rgb(0x1F, 0x21, 0x26);
const TECLA_B: Color32 = Color32::from_rgb(0x3B, 0x3D, 0x45);

/// Lienzo del aparato en unidades de diseño: 1 mm = 6 px, 100 × 60 mm.
const APARATO_W: f32 = 600.0;
const APARATO_H: f32 = 360.0;

// ---------------------------------------------------------------- estado

#[derive(Clone, Copy, PartialEq)]
enum Tipo {
    Teclado,
    Raton,
    Multimedia,
    Secuencia,
}

pub struct GuiArgs {
    pub profile: Option<String>,
    pub dev: DeviceArgs,
}

struct App {
    /// Ajustes de dispositivo (report id, transporte) heredados del CLI.
    dev: DeviceArgs,
    /// Una asignación por elemento: teclas 1..6 + las tres acciones de la perilla.
    bindings: Vec<Binding>,
    sel: usize,
    profile: Option<String>,
    log: Vec<String>,
    estado: Option<(String, bool)>, // (descripción, conectado)
    aviso: Option<String>,
}

const PERILLA: [(&str, &str); 3] = [
    ("knob-left", "girar izq"),
    ("knob-push", "pulsar"),
    ("knob-right", "girar der"),
];

fn perfil_por_defecto() -> Vec<Binding> {
    let b = |key: &str, codes: &[&str], mods: &[&str], mouse: Option<&str>, media: Option<&str>| {
        Binding {
            key: key.to_string(),
            layer: 1,
            clear: false,
            codes: codes.iter().map(|s| s.to_string()).collect(),
            mods: mods.iter().map(|s| s.to_string()).collect(),
            media: media.map(|s| s.to_string()),
            mouse: mouse.map(|s| s.to_string()),
            delay_ms: 0,
        }
    };
    vec![
        b("1", &["C"], &["ctrl"], None, None),
        b("2", &["V"], &["ctrl"], None, None),
        b("3", &["X"], &["ctrl"], None, None),
        b("4", &["ESC"], &[], None, None),
        b("5", &[], &[], Some("middle"), None),
        b("6", &[], &[], Some("right"), None),
        b("knob-left", &[], &[], None, Some("voldown")),
        b("knob-push", &[], &[], None, Some("play")),
        b("knob-right", &[], &[], None, Some("volup")),
    ]
}

impl App {
    fn new(args: &GuiArgs) -> Self {
        let (bindings, profile) = match &args.profile {
            Some(path) => match std::fs::read_to_string(path) {
                Ok(texto) => match parse_profile(&texto) {
                    Ok(p) => (p.bindings, Some(path.clone())),
                    Err(e) => {
                        eprintln!("perfil {path} inválido: {e}");
                        (perfil_por_defecto(), None)
                    }
                },
                Err(e) => {
                    eprintln!("no puedo leer {path}: {e}");
                    (perfil_por_defecto(), None)
                }
            },
            None => (perfil_por_defecto(), None),
        };
        let mut app = Self {
            dev: args.dev.clone(),
            bindings,
            sel: 0,
            profile,
            log: vec![],
            estado: None,
            aviso: None,
        };
        app.detectar();
        app
    }

    fn detectar(&mut self) {
        self.estado = match Device::discover(VID_OEM) {
            Ok(devs) if !devs.is_empty() => {
                let d = &devs[0];
                let kp = crate::hidraw::known_pid(d.pid);
                Some((
                    format!(
                        "HID {:04x}:{:04x}  {}  {}",
                        d.vid,
                        d.pid,
                        kp.map(|k| format!("protocolo {}", k.0)).unwrap_or_default(),
                        d.product
                    ),
                    true,
                ))
            }
            _ => None,
        };
    }

    fn binding(&self) -> &Binding {
        &self.bindings[self.sel]
    }

    fn binding_mut(&mut self) -> &mut Binding {
        &mut self.bindings[self.sel]
    }

    fn tipo(&self) -> Tipo {
        let b = self.binding();
        if b.media.is_some() {
            Tipo::Multimedia
        } else if b.mouse.is_some() {
            Tipo::Raton
        } else if b.codes.len() > 1 {
            Tipo::Secuencia
        } else {
            Tipo::Teclado
        }
    }

    fn poner_tipo(&mut self, t: Tipo) {
        let b = self.binding_mut();
        match t {
            Tipo::Teclado => {
                b.media = None;
                b.mouse = None;
                b.codes = vec!["C".into()];
            }
            Tipo::Secuencia => {
                b.media = None;
                b.mouse = None;
                b.codes = vec!["H".into(), "O".into(), "L".into(), "A".into()];
            }
            Tipo::Raton => {
                b.media = None;
                b.mouse = Some("right".into());
                b.codes.clear();
            }
            Tipo::Multimedia => {
                b.mouse = None;
                b.media = Some("play".into());
                b.codes.clear();
            }
        }
    }

    /// Índice del firmware para la asignación seleccionada.
    fn indice(&self, new_mul_mouse: bool) -> Option<u8> {
        key_index(&self.binding().key, new_mul_mouse)
    }

    /// Tramas que se enviarían, para enseñarlas antes de escribir.
    fn tramas(&self, report_id: u8) -> Result<Vec<String>, String> {
        let b = self.binding();
        if b.clear {
            return Ok(vec!["(tecla sin función)".into()]);
        }
        let (tipo, steps) = steps_for(b, report_id)?;
        let idx = key_index(&b.key, false).unwrap_or(1);
        let frames = short_frames(idx, b.layer, tipo, &steps, report_id, false);
        let mut out: Vec<String> = frames.iter().map(|f| hex(f)).collect();
        out.push("AA AA (grabar)".into());
        Ok(out)
    }

    fn aplicar(&mut self, todas: bool) {
        let mut dev = self.dev.clone();
        dev.dry_run = false;
        let mut t = match target(&dev, true) {
            Ok(t) => t,
            Err(e) => {
                self.aviso = Some(format!("no encuentro el teclado: {e}"));
                return;
            }
        };
        let rd = t.report_id;
        let nmm = t.new_mul_mouse;
        let objetivo: Vec<usize> = if todas {
            (0..self.bindings.len()).collect()
        } else {
            vec![self.sel]
        };
        let mut ok = 0;
        let mut errores = 0;
        for i in objetivo {
            let b = self.bindings[i].clone();
            let Some(idx) = key_index(&b.key, nmm) else {
                continue;
            };
            match steps_for(&b, rd).and_then(|(tipo, steps)| {
                t.set_key(idx, b.layer, tipo, &steps, b.delay_ms, false)
            }) {
                Ok(()) => ok += 1,
                Err(e) => {
                    self.log.push(format!("error en la tecla {}: {e}", b.key));
                    errores += 1;
                }
            }
        }
        self.log
            .push(format!("aplicado: {ok} asignaciones, {errores} errores"));
        self.aviso = None;
    }

    fn guardar_perfil(&mut self) {
        let ruta = self
            .profile
            .clone()
            .unwrap_or_else(|| "perfil-macrokey.toml".to_string());
        let mut texto = String::from("# Perfil del configurador de macrokey\n\n");
        for b in &self.bindings {
            texto.push_str("[[binding]]\n");
            texto.push_str(&format!("key = \"{}\"\n", b.key));
            if b.clear {
                texto.push_str("clear = true\n");
            }
            if !b.codes.is_empty() {
                let c: Vec<String> = b.codes.iter().map(|c| format!("\"{c}\"")).collect();
                texto.push_str(&format!("codes = [{}]\n", c.join(", ")));
            }
            if !b.mods.is_empty() {
                let m: Vec<String> = b.mods.iter().map(|m| format!("\"{m}\"")).collect();
                texto.push_str(&format!("mods = [{}]\n", m.join(", ")));
            }
            if let Some(m) = &b.media {
                texto.push_str(&format!("media = \"{m}\"\n"));
            }
            if let Some(m) = &b.mouse {
                texto.push_str(&format!("mouse = \"{m}\"\n"));
            }
            if b.delay_ms > 0 {
                texto.push_str(&format!("delay_ms = {}\n", b.delay_ms));
            }
            texto.push('\n');
        }
        match std::fs::write(&ruta, texto) {
            Ok(()) => {
                self.log.push(format!("perfil guardado en {ruta}"));
                self.profile = Some(ruta);
            }
            Err(e) => self.log.push(format!("no puedo escribir {ruta}: {e}")),
        }
    }
}

fn hex(bytes: &[u8]) -> String {
    bytes
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect::<Vec<_>>()
        .join(" ")
}

// ---------------------------------------------------------------- etiquetas

/// Texto corto y legible de lo que hace una asignación.
fn etiqueta(b: &Binding) -> String {
    if b.clear {
        return "(sin función)".into();
    }
    if let Some(m) = &b.media {
        return match m.as_str() {
            "play" => "play/pausa".into(),
            "next" => "siguiente".into(),
            "prev" => "anterior".into(),
            "mute" => "silencio".into(),
            "volup" => "volumen +".into(),
            "voldown" => "volumen -".into(),
            otro => otro.into(),
        };
    }
    if let Some(m) = &b.mouse {
        let base = match m.as_str() {
            "left" => "boton izq".into(),
            "right" => "boton der".into(),
            "middle" => "boton centro".into(),
            "wheelup" => "rueda arriba".into(),
            "wheeldown" => "rueda abajo".into(),
            otro => otro.to_string(),
        };
        return con_mods(&b.mods, &base);
    }
    let codigo = b.codes.first().cloned().unwrap_or_default();
    let tecla = if b.codes.len() > 1 {
        format!("{}...", b.codes.join("+"))
    } else {
        codigo
    };
    con_mods(&b.mods, &tecla)
}

fn con_mods(mods: &[String], base: &str) -> String {
    if mods.is_empty() {
        return base.into();
    }
    let m: Vec<String> = mods
        .iter()
        .map(|m| match m.to_ascii_lowercase().as_str() {
            "ctrl" => "Ctrl".to_string(),
            "shift" => "Shift".to_string(),
            "alt" => "Alt".to_string(),
            "win" => "Win".to_string(),
            otro => otro.to_string(),
        })
        .collect();
    format!("{}+{}", m.join("+"), base)
}

// ---------------------------------------------------------------- dibujo

fn dibujar_aparato(ui: &mut egui::Ui, app: &mut App, escala: f32) {
    let tam = Vec2::new(APARATO_W * escala, APARATO_H * escala + 26.0);
    let (resp, painter) = ui.allocate_painter(tam, Sense::click());
    let r = resp.rect;
    let mm = 6.0 * escala;
    let mapa = |x_mm: f32, y_mm: f32| r.min + Vec2::new(x_mm * mm, y_mm * mm);
    let caja = |x_mm: f32, y_mm: f32, w_mm: f32, h_mm: f32| {
        Rect::from_min_size(mapa(x_mm, y_mm), Vec2::new(w_mm * mm, h_mm * mm))
    };

    // cuerpo y placa
    painter.rect_filled(caja(0.0, 0.0, 100.0, 60.0), CornerRadius::same(8), CUERPO);
    painter.rect_stroke(
        caja(0.0, 0.0, 100.0, 60.0),
        CornerRadius::same(8),
        Stroke::new(1.0, Color32::from_rgb(0x78, 0x7E, 0x8A)),
        egui::StrokeKind::Inside,
    );
    painter.rect_filled(caja(1.0, 1.0, 98.0, 58.0), CornerRadius::same(6), PLACA);
    painter.rect_stroke(
        caja(1.0, 1.0, 98.0, 58.0),
        CornerRadius::same(6),
        Stroke::new(1.0, LINEA),
        egui::StrokeKind::Inside,
    );
    for (x, y) in [(1.5f32, 1.5f32), (97.0, 1.5), (1.5, 57.0), (97.0, 57.0)] {
        painter.circle_filled(mapa(x, y), 1.0 * mm, Color32::from_rgb(0x8B, 0x91, 0x9C));
    }

    // teclas 2 x 3
    let posiciones = [(4.0f32, 11.5f32), (24.0, 11.5), (44.0, 11.5), (4.0, 31.5), (24.0, 31.5), (44.0, 31.5)];
    let mut acciones: Vec<Option<egui::Response>> = Vec::new();
    for (i, (x, y)) in posiciones.iter().enumerate() {
        let rect = caja(*x, *y, 18.0, 17.0);
        let sel = app.sel == i;
        let clic = ui.interact(rect, ui.id().with(("tecla", i)), Sense::click());
        let (fondo, borde) = if sel {
            (Color32::from_rgb(0x2A, 0x22, 0x1E), NARANJA)
        } else if clic.hovered() {
            (TECLA, Color32::from_rgb(0x7F, 0x87, 0x94))
        } else {
            (TECLA, TECLA_B)
        };
        painter.rect_filled(rect, CornerRadius::same(4), fondo);
        painter.rect_stroke(
            rect,
            CornerRadius::same(4),
            Stroke::new(if sel { 2.0 } else { 1.0 }, borde),
            egui::StrokeKind::Inside,
        );
        painter.text(
            rect.left_top() + Vec2::new(4.0 * escala, 3.0 * escala),
            Align2::LEFT_TOP,
            format!("TECLA {}", i + 1),
            FontId::proportional(7.0 * escala),
            GRIS,
        );
        painter.text(
            rect.center(),
            Align2::CENTER_CENTER,
            etiqueta(&app.bindings[i]),
            FontId::proportional(9.0 * escala),
            if sel { NARANJA } else { CLARO },
        );
        if clic.clicked() {
            app.sel = i;
        }
        acciones.push(Some(clic));
    }

    // perilla: tres zonas (izquierda, pulsar, derecha)
    let (cx_mm, cy_mm, r_mm) = (81.0f32, 30.0f32, 10.0f32);
    let centro = mapa(cx_mm, cy_mm);
    let radio = r_mm * mm;
    let idx_perilla = [6usize, 7, 8];
    let sel_p = idx_perilla.contains(&app.sel);
    painter.circle_filled(centro, radio, Color32::from_rgb(0x1A, 0x1B, 0x20));
    painter.circle_stroke(
        centro,
        radio,
        Stroke::new(
            if sel_p { 2.5 } else { 2.0 },
            if sel_p { NARANJA } else { Color32::from_rgb(0x8B, 0x91, 0x9C) },
        ),
    );
    for i in 0..12 {
        let a = i as f32 * std::f32::consts::TAU / 12.0 + 0.26;
        let p1 = centro + Vec2::new(a.cos(), a.sin()) * (radio - 3.0 * escala);
        let p2 = centro + Vec2::new(a.cos(), a.sin()) * (radio * 0.62);
        painter.line_segment([p1, p2], Stroke::new(1.5 * escala, Color32::from_rgb(0x5B, 0x60, 0x6C)));
    }
    painter.circle_filled(centro, radio * 0.30, Color32::from_rgb(0x22, 0x24, 0x2A));
    painter.line_segment(
        [centro + Vec2::new(0.0, -radio + 3.0 * escala), centro + Vec2::new(0.0, -radio * 0.45)],
        Stroke::new(2.0 * escala, NARANJA),
    );

    // zonas clicables de la perilla, con su acción
    let zonas = [
        (caja(66.0, 25.0, 6.7, 10.0), idx_perilla[0], "<"),
        (caja(72.0, 45.0, 20.0, 5.0), idx_perilla[1], "pulsar"),
        (caja(87.3, 25.0, 6.7, 10.0), idx_perilla[2], ">"),
    ];
    for (rect, idx, flecha) in zonas {
        let clic = ui.interact(rect, ui.id().with(("zona", idx)), Sense::click());
        let sel_z = app.sel == idx;
        painter.rect_filled(rect, CornerRadius::same(4), Color32::from_rgb(0x20, 0x22, 0x28));
        painter.rect_stroke(
            rect,
            CornerRadius::same(4),
            Stroke::new(
                if sel_z { 2.0 } else { 1.0 },
                if sel_z { NARANJA } else { LINEA },
            ),
            egui::StrokeKind::Inside,
        );
        let texto = if flecha == "pulsar" {
            etiqueta(&app.bindings[idx])
        } else {
            etiqueta(&app.bindings[idx])
        };
        painter.text(
            rect.center() + Vec2::new(0.0, 2.0 * escala),
            Align2::CENTER_CENTER,
            texto,
            FontId::proportional(6.2 * escala),
            if sel_z { NARANJA } else { GRIS },
        );
        if flecha != "pulsar" {
            // flecha dibujada (vectorial): los glifos de flecha no están garantizados
            let c = rect.center_top() + Vec2::new(0.0, 3.0 * escala);
            let d = 2.6 * escala;
            let signo = if flecha == "<" { -1.0 } else { 1.0 };
            painter.add(egui::Shape::convex_polygon(
                vec![
                    c + Vec2::new(-d * signo, 0.0),
                    c + Vec2::new(d * signo, -d * 0.8),
                    c + Vec2::new(d * signo, d * 0.8),
                ],
                if sel_z { NARANJA } else { GRIS },
                Stroke::NONE,
            ));
        }
        if clic.clicked() {
            app.sel = idx;
        }
    }

    let nota = format!(
        "100 x 60 mm  -  perilla diam. 20 mm  -  teclas 18 x 17 mm  -  escala {:.0}%",
        escala * 100.0
    );
    painter.text(
        r.left_bottom() + Vec2::new(0.0, 4.0 * escala),
        Align2::LEFT_TOP,
        nota,
        FontId::proportional(9.0 * escala),
        GRIS,
    );
}

// ---------------------------------------------------------------- ventana

impl eframe::App for App {
    // eframe 0.36: el trait pide `ui()` (no `update()`) y los paneles se montan
    // dentro del `Ui` que da el framework.
    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        ui.ctx().all_styles_mut(|estilo| {
            estilo.visuals.dark_mode = true;
            estilo.visuals.panel_fill = FONDO_APP;
            estilo.visuals.window_fill = PANEL;
            estilo.visuals.override_text_color = Some(CLARO);
            estilo.visuals.widgets.noninteractive.bg_stroke = Stroke::new(1.0, LINEA);
            estilo.spacing.item_spacing = Vec2::new(8.0, 6.0);
            // el azul de selección por defecto no es de la paleta
            estilo.visuals.selection.bg_fill = NARANJA;
            estilo.visuals.selection.stroke = Stroke::new(1.0, Color32::from_rgb(0x14, 0x0A, 0x02));
            estilo.visuals.hyperlink_color = NARANJA;
            estilo.visuals.widgets.hovered.bg_stroke = Stroke::new(1.0, GRIS);
            estilo.visuals.widgets.active.bg_stroke = Stroke::new(1.0, NARANJA);
            estilo.visuals.widgets.inactive.weak_bg_fill = PANEL;
            estilo.visuals.extreme_bg_color = Color32::from_rgb(0x12, 0x14, 0x18);
        });

        egui::Panel::top("barra").show(ui, |ui| {
            ui.add_space(4.0);
            ui.horizontal(|ui| {
                ui.heading("macrokey");
                ui.label(
                    egui::RichText::new("configurador del teclado macro")
                        .color(GRIS)
                        .size(12.0),
                );
                ui.add_space(12.0);
                if ui
                    .add(egui::Button::new(
                        egui::RichText::new("Aplicar al teclado")
                            .color(Color32::from_rgb(0x14, 0x0A, 0x02))
                            .strong(),
                    )
                    .fill(NARANJA))
                    .clicked()
                {
                    self.aplicar(true);
                }
                if ui.button("Guardar perfil").clicked() {
                    self.guardar_perfil();
                }
                if ui.button("Buscar teclado").clicked() {
                    self.detectar();
                }
                ui.add_space(8.0);
                ui.label(
                    egui::RichText::new("Leer del teclado: no disponible (el firmware no expone lectura)")
                        .color(GRIS)
                        .size(11.0),
                );
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    match &self.estado {
                        Some((desc, true)) => {
                            ui.label(egui::RichText::new(desc).color(GRIS).size(11.5));
                            let (rect, _) = ui.allocate_exact_size(Vec2::splat(9.0), Sense::hover());
                            ui.painter().circle_filled(rect.center(), 4.5, NARANJA);
                        }
                        _ => {
                            ui.label(
                                egui::RichText::new("sin teclado detectado")
                                    .color(GRIS)
                                    .size(11.5),
                            );
                            let (rect, _) = ui.allocate_exact_size(Vec2::splat(9.0), Sense::hover());
                            ui.painter()
                                .circle_filled(rect.center(), 4.5, Color32::from_rgb(0x4A, 0x50, 0x5C));
                        }
                    }
                });
            });
            ui.add_space(4.0);
        });

        egui::Panel::bottom("log").show(ui, |ui| {
            ui.add_space(2.0);
            let texto = self
                .log
                .last()
                .cloned()
                .unwrap_or_else(|| "listo".to_string());
            ui.label(egui::RichText::new(texto).color(GRIS).size(11.5).monospace());
            ui.add_space(2.0);
        });

        egui::Panel::right("editor")
            .resizable(false)
            .show(ui, |ui| {
                ui.set_min_width(360.0);
                self.editor(ui);
            });

        egui::CentralPanel::default().show(ui, |ui| {
            let disp = ui.available_width();
            let escala = ((disp - 8.0) / APARATO_W).clamp(0.55, 1.6);
            ui.add_space(6.0);
            dibujar_aparato(ui, self, escala);
            ui.add_space(10.0);
            if let Some(a) = &self.aviso {
                ui.colored_label(NARANJA, a);
            }
        });
    }
}

impl App {
    fn editor(&mut self, ui: &mut egui::Ui) {
        ui.add_space(6.0);
        let idx_txt = match self.sel {
            0..=5 => format!("Tecla {} seleccionada", self.sel + 1),
            _ => format!("Perilla ({})", PERILLA[self.sel - 6].1),
        };
        ui.label(egui::RichText::new(idx_txt).strong().size(14.0));
        if let Some(n) = self.indice(false) {
            ui.label(
                egui::RichText::new(format!("índice del firmware: {n}"))
                    .color(GRIS)
                    .size(11.0),
            );
        }
        ui.add_space(6.0);

        // tipo de acción
        ui.label(egui::RichText::new("Tipo de acción").color(GRIS).size(11.5));
        let actual = self.tipo();
        ui.horizontal(|ui| {
            for (t, nombre) in [
                (Tipo::Teclado, "Teclado"),
                (Tipo::Raton, "Ratón"),
                (Tipo::Multimedia, "Multimedia"),
                (Tipo::Secuencia, "Secuencia"),
            ] {
                if ui.selectable_label(actual == t, nombre).clicked() {
                    self.poner_tipo(t);
                }
            }
        });
        ui.add_space(6.0);

        match self.tipo() {
            Tipo::Teclado | Tipo::Secuencia => {
                let etiqueta = if self.tipo() == Tipo::Secuencia {
                    "Secuencia de teclas (separadas por comas: H,O,L,A)"
                } else {
                    "Tecla (código HID: A, F5, ENTER, KP1...)"
                };
                ui.label(egui::RichText::new(etiqueta).color(GRIS).size(11.5));
                let mut texto = self.binding().codes.join(",");
                if ui.text_edit_singleline(&mut texto).changed() {
                    let codes: Vec<String> = texto
                        .split(',')
                        .map(|s| s.trim().to_ascii_uppercase())
                        .filter(|s| !s.is_empty())
                        .collect();
                    self.binding_mut().codes = codes;
                }
                if self.tipo() == Tipo::Secuencia {
                    let mut d = self.binding().delay_ms as u32;
                    ui.label(egui::RichText::new("Retardo entre teclas (ms)").color(GRIS).size(11.5));
                    if ui.add(egui::Slider::new(&mut d, 0..=500)).changed() {
                        self.binding_mut().delay_ms = d as u16;
                    }
                }
            }
            Tipo::Raton => {
                ui.label(egui::RichText::new("Acción de ratón").color(GRIS).size(11.5));
                let actual = self.binding().mouse.clone().unwrap_or_default();
                egui::ComboBox::from_id_salt("raton")
                    .selected_text(match actual.as_str() {
                        "left" => "Botón izquierdo",
                        "right" => "Botón derecho (arrastrar = rotate)",
                        "middle" => "Botón central (arrastrar = pan)",
                        "wheelup" => "Rueda arriba (zoom +)",
                        "wheeldown" => "Rueda abajo (zoom -)",
                        otro => otro,
                    })
                    .show_ui(ui, |ui| {
                        for (v, n) in [
                            ("middle", "Botón central (arrastrar = pan)"),
                            ("right", "Botón derecho (arrastrar = rotate)"),
                            ("left", "Botón izquierdo"),
                            ("wheelup", "Rueda arriba (zoom +)"),
                            ("wheeldown", "Rueda abajo (zoom -)"),
                        ] {
                            if ui.selectable_label(actual == v, n).clicked() {
                                self.binding_mut().mouse = Some(v.into());
                            }
                        }
                    });
            }
            Tipo::Multimedia => {
                ui.label(egui::RichText::new("Acción multimedia").color(GRIS).size(11.5));
                let actual = self.binding().media.clone().unwrap_or_default();
                egui::ComboBox::from_id_salt("media")
                    .selected_text(actual.clone())
                    .show_ui(ui, |ui| {
                        for v in ["play", "next", "prev", "mute", "volup", "voldown"] {
                            if ui.selectable_label(actual == v, v).clicked() {
                                self.binding_mut().media = Some(v.into());
                            }
                        }
                    });
            }
        }

        // modificadores (no aplican a multimedia)
        if self.tipo() != Tipo::Multimedia {
            ui.add_space(6.0);
            ui.label(
                egui::RichText::new("Modificadores (p. ej. Ctrl + rueda)")
                    .color(GRIS)
                    .size(11.5),
            );
            ui.horizontal(|ui| {
                for m in ["ctrl", "shift", "alt", "win"] {
                    let on = self
                        .binding()
                        .mods
                        .iter()
                        .any(|x| x.eq_ignore_ascii_case(m));
                    if ui.selectable_label(on, m).clicked() {
                        let b = self.binding_mut();
                        if on {
                            b.mods.retain(|x| !x.eq_ignore_ascii_case(m));
                        } else {
                            b.mods.push(m.into());
                        }
                    }
                }
            });
        }

        ui.add_space(8.0);
        ui.label(egui::RichText::new("Se enviará a la flash").color(GRIS).size(11.5));
        let tramas = self.tramas(3);
        let texto = match &tramas {
            Ok(t) => t.join("\n"),
            Err(e) => format!("error: {e}"),
        };
        ui.add(
            egui::Label::new(
                egui::RichText::new(texto)
                    .monospace()
                    .size(11.5)
                    .color(if tramas.is_ok() { CLARO } else { NARANJA }),
            )
            .wrap(),
        );

        ui.add_space(8.0);
        if ui
            .add(
                egui::Button::new(
                    egui::RichText::new("Aplicar a esta tecla")
                        .color(Color32::from_rgb(0x14, 0x0A, 0x02))
                        .strong(),
                )
                .fill(NARANJA),
            )
            .clicked()
        {
            self.aplicar(false);
        }
        ui.add_space(8.0);
        ui.label(
            egui::RichText::new(
                "Las teclas físicas vienen en negro y sin leyenda: lo que se ve aquí es lo que \
                 hace cada una. El editor cambia según el tipo. Escribir en la flash requiere \
                 permisos (regla udev instalada o sudo).",
            )
            .color(GRIS)
            .size(11.0),
        );
    }
}

pub fn run(args: GuiArgs) -> Result<(), String> {
    let opciones = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_inner_size([1180.0, 640.0])
            .with_min_inner_size([900.0, 520.0])
            .with_title("macrokey - configurador del teclado macro"),
        ..Default::default()
    };
    let app = App::new(&args);
    eframe::run_native(
        "macrokey",
        opciones,
        Box::new(|_cc| Ok(Box::new(app))),
    )
    .map_err(|e| format!("no puedo abrir la ventana: {e}"))
}
