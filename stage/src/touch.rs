//! Tactile touchscreen interaction engine for the stage.
//!
//! Classifies raw touch / pointer input into:
//! - screen wake taps (when the display is dim or dark at night — wakes and consumes the tap);
//! - UI panel / floating pill / backdrop / edge-swipe events forwarded to the core;
//! - character petting (headpats & cheek rubs with real stroke detection), pokes, taps,
//!   double-taps, long presses, and real-time finger eye-tracking.
//!
//! Pure logic with no OpenGL or windowing dependencies so every gesture and edge case is
//! unit-tested deterministically.

use serde_json::{json, Value};

use crate::behaviour::Pose;
use crate::fx::FxState;
use crate::smooth::Spring;
use crate::vrm::render::Shot;

/// Raw pointer/touch lifecycle phase.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Phase {
	Down,
	Move,
	Up,
	Cancel,
}

/// One raw touch or mouse sample in normalized screen coordinates `(0..1, 0..1)`.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct TouchSample {
	pub id: u64,
	pub phase: Phase,
	/// 0.0 = left edge, 1.0 = right edge.
	pub x: f32,
	/// 0.0 = top edge, 1.0 = bottom edge.
	pub y: f32,
}

/// How the character is framed on screen (calibrates anatomical hit zones).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Framing {
	Bust,
	Upper,
	Full,
}

impl From<Shot> for Framing {
	fn from(shot: Shot) -> Self {
		match shot {
			Shot::Bust => Framing::Bust,
			Shot::Upper => Framing::Upper,
			Shot::Full => Framing::Full,
		}
	}
}

/// Anatomical region on the character canvas.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Zone {
	Head,
	Face,
	Body,
	Background,
}

impl Zone {
	pub fn name(self) -> &'static str {
		match self {
			Zone::Head => "head",
			Zone::Face => "face",
			Zone::Body => "body",
			Zone::Background => "background",
		}
	}

	/// Map normalized screen point `(x, y)` to a character zone for the active framing.
	pub fn from_point(x: f32, y: f32, framing: Framing) -> Self {
		let (x_min, x_max, head_top, head_bot, face_bot, body_bot) = match framing {
			Framing::Bust => (0.16, 0.84, 0.04, 0.34, 0.62, 0.96),
			Framing::Upper => (0.18, 0.82, 0.06, 0.28, 0.47, 0.88),
			Framing::Full => (0.22, 0.78, 0.05, 0.20, 0.32, 0.88),
		};
		if x < x_min || x > x_max || y < head_top || y > body_bot {
			Zone::Background
		} else if y < head_bot {
			Zone::Head
		} else if y < face_bot {
			Zone::Face
		} else {
			Zone::Body
		}
	}

	/// Approximate vertical center of the character's eyes (for finger eye-tracking).
	fn eye_line(framing: Framing) -> f32 {
		match framing {
			Framing::Bust => 0.44,
			Framing::Upper => 0.35,
			Framing::Full => 0.24,
		}
	}
}

/// Normalized rectangle `[x0, y0, x1, y1]` in `(0..1, 0..1)`.
pub type Rect = [f32; 4];

fn in_rect(x: f32, y: f32, r: Rect) -> bool {
	x >= r[0] && x <= r[2] && y >= r[1] && y <= r[3]
}

/// Settings pushed from core (`{"touch_config": ...}`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct TouchConfig {
	pub enabled: bool,
	pub character_touch: bool,
	pub effects: bool,
}

impl Default for TouchConfig {
	fn default() -> Self {
		Self { enabled: true, character_touch: true, effects: true }
	}
}

/// Active UI hit regions pushed from core (`{"touch_capture": ...}`).
#[derive(Clone, Debug, PartialEq)]
pub struct TouchCapture {
	/// When true, a dock or modal sheet is open: touches never poke/pet the character underneath,
	/// and tapping outside `panel` dismisses it.
	pub modal: bool,
	/// Bounding rect of the open dock or modal sheet, if any.
	pub panel: Option<Rect>,
	/// Bounding rect of the subtle floating bottom pill, when visible.
	pub pill: Option<Rect>,
	/// Whether edge swipes (bottom swipe-up for dock, top swipe-down for quick status) are active.
	pub edge_swipe: bool,
}

impl Default for TouchCapture {
	fn default() -> Self {
		Self { modal: false, panel: None, pill: None, edge_swipe: true }
	}
}

/// What the touch engine wants the stage to emit or play right now.
#[derive(Clone, Debug, Default)]
pub struct TouchOutput {
	/// JSON events to send to the core service over the local socket.
	pub events: Vec<Value>,
	/// Immediate reaction clips to play on the character.
	pub reactions: Vec<&'static str>,
	/// True if the screen should wake immediately (touch arrived while dim/off).
	pub wake_screen: bool,
	/// True if the director should be poked (character wakes/brightens).
	pub poke_director: bool,
	/// True if the character should blink right now (cute reflex on boop/tap).
	pub blink: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Route {
	ConsumedWake,
	UiPanel,
	UiBackdrop,
	UiPill,
	EdgeBottom,
	EdgeTop,
	Character,
}

struct ActiveTouch {
	id: u64,
	route: Route,
	start_x: f32,
	start_y: f32,
	x: f32,
	y: f32,
	start_t: f32,
	total_dist: f32,
	/// Tracking back-and-forth petting strokes.
	last_dx_sign: i8,
	reversals: u32,
	pet_dist: f32,
	petting: bool,
	pet_zone: Zone,
	pet_event_sent: bool,
	last_pet_fx: f32,
	last_pet_reaction: f32,
	long_press_fired: bool,
	last_ui_move: f32,
	edge_swiped: bool,
}

const TAP_MAX_DIST: f32 = 0.045;
const TAP_MAX_TIME: f32 = 0.45;
const DOUBLE_TAP_GAP: f32 = 0.34;
const DOUBLE_TAP_DIST: f32 = 0.085;
const LONG_PRESS_TIME: f32 = 0.55;
const SWIPE_MIN_DIST: f32 = 0.085;
const EDGE_SWIPE_MIN: f32 = 0.065;
const LOOK_LINGER: f32 = 1.2;
const UI_MOVE_INTERVAL: f32 = 0.03; // ~33 Hz max for slider drag forwarding

pub struct TouchEngine {
	config: TouchConfig,
	capture: TouchCapture,
	framing: Framing,
	t: f32,
	active: Option<ActiveTouch>,
	/// Last completed tap for double-tap detection: (time, x, y, zone).
	last_tap: Option<(f32, f32, f32, Zone)>,
	/// Alternate between playful surprised/giggle reactions on repeated pokes.
	poke_toggle: bool,
	/// Finger eye-tracking target and how long it lingers after lift.
	look_target: (f32, f32),
	look_until: f32,
	look_weight: Spring,
	/// Smooth tactile petting blend while finger is stroking head/cheek.
	pet_weight: Spring,
	pet_sway: Spring,
	pet_target_sway: f32,
	pet_is_cheek: bool,
}

impl TouchEngine {
	pub fn new(framing: Framing) -> Self {
		Self {
			config: TouchConfig::default(),
			capture: TouchCapture::default(),
			framing,
			t: 0.0,
			active: None,
			last_tap: None,
			poke_toggle: false,
			look_target: (0.0, 0.0),
			look_until: -10.0,
			look_weight: Spring::new(0.0, 0.14),
			pet_weight: Spring::new(0.0, 0.22),
			pet_sway: Spring::new(0.0, 0.16),
			pet_target_sway: 0.0,
			pet_is_cheek: false,
		}
	}

	pub fn set_config(&mut self, config: TouchConfig) {
		self.config = config;
		if !config.enabled {
			self.active = None;
		}
	}

	pub fn set_capture(&mut self, capture: TouchCapture) {
		self.capture = capture;
	}

	/// True when a modal sheet or dock currently covers the bottom area.
	pub fn ui_covering_bottom(&self) -> bool {
		self.capture.modal
	}

	/// Process one raw touch sample. `screen_sleeping` is true when the screen is currently `Dim` or `Off`.
	pub fn on_sample(&mut self, sample: TouchSample, screen_sleeping: bool, fx: &mut FxState) -> TouchOutput {
		let mut out = TouchOutput::default();
		let x = sample.x.clamp(0.0, 1.0);
		let y = sample.y.clamp(0.0, 1.0);

		if !self.config.enabled {
			// Even when touch controls are turned off, tapping a sleeping screen wakes it cleanly.
			if screen_sleeping && sample.phase == Phase::Down {
				out.wake_screen = true;
				out.poke_director = true;
				out.events.push(json!({"event": "touch_wake", "x": round3(x), "y": round3(y)}));
			}
			return out;
		}

		match sample.phase {
			Phase::Down => self.handle_down(sample.id, x, y, screen_sleeping, fx, &mut out),
			Phase::Move => self.handle_move(sample.id, x, y, fx, &mut out),
			Phase::Up => self.handle_up(sample.id, x, y, fx, &mut out),
			Phase::Cancel => self.handle_cancel(sample.id, fx),
		}
		out
	}

	fn handle_down(&mut self, id: u64, x: f32, y: f32, screen_sleeping: bool, fx: &mut FxState, out: &mut TouchOutput) {
		// Ignore a second simultaneous finger while tracking the primary touch.
		if self.active.is_some() {
			return;
		}

		if screen_sleeping {
			out.wake_screen = true;
			out.poke_director = true;
			out.reactions.push("touch_wake");
			out.events.push(json!({"event": "touch_wake", "x": round3(x), "y": round3(y)}));
			fx.spawn_ripple(x, y, [0.58, 0.78, 1.0, 0.85]);
			self.active = Some(self.new_touch(id, Route::ConsumedWake, x, y));
			return;
		}

		let route = self.classify_route(x, y);
		let mut touch = self.new_touch(id, route, x, y);

		match route {
			Route::UiPanel => {
				fx.spawn_ripple(x, y, [0.72, 0.84, 1.0, 0.55]);
				out.events.push(json!({
					"event": "ui_touch", "phase": "down", "target": "panel",
					"x": round3(x), "y": round3(y),
				}));
			}
			Route::UiPill => {
				fx.spawn_ripple(x, y, [0.64, 0.82, 1.0, 0.7]);
				out.events.push(json!({
					"event": "ui_touch", "phase": "down", "target": "pill",
					"x": round3(x), "y": round3(y),
				}));
			}
			Route::UiBackdrop => {
				// Wait for tap/release to dismiss cleanly (or swipe down).
			}
			Route::EdgeBottom | Route::EdgeTop => {
				fx.spawn_ripple(x, y, [0.6, 0.78, 1.0, 0.5]);
			}
			Route::Character => {
				if self.config.character_touch {
					let zone = Zone::from_point(x, y, self.framing);
					touch.pet_zone = zone;
					self.update_look_from_point(x, y);
					let warm = matches!(zone, Zone::Head | Zone::Face);
					fx.set_finger(Some((x, y)), warm);
					fx.spawn_ripple(x, y, if warm { [1.0, 0.68, 0.84, 0.72] } else { [0.58, 0.78, 1.0, 0.68] });
					out.poke_director = true;
				}
			}
			Route::ConsumedWake => {}
		}

		self.active = Some(touch);
	}

	fn handle_move(&mut self, id: u64, x: f32, y: f32, fx: &mut FxState, out: &mut TouchOutput) {
		let Some(mut touch) = self.active.take() else { return };
		if touch.id != id {
			self.active = Some(touch);
			return;
		}
		let dx = x - touch.x;
		let dy = y - touch.y;
		let step = dx.hypot(dy);
		touch.total_dist += step;
		touch.x = x;
		touch.y = y;

		match touch.route {
			Route::ConsumedWake => {}
			Route::UiPanel => {
				if self.t - touch.last_ui_move >= UI_MOVE_INTERVAL {
					touch.last_ui_move = self.t;
					out.events.push(json!({
						"event": "ui_touch", "phase": "move", "target": "panel",
						"x": round3(x), "y": round3(y),
						"dx": round3(x - touch.start_x), "dy": round3(y - touch.start_y),
					}));
				}
			}
			Route::UiPill => {
				// Swiping upward from the floating pill opens the Quick Dock immediately.
				let total_dy = y - touch.start_y;
				let total_dx = x - touch.start_x;
				if !touch.edge_swiped && total_dy <= -EDGE_SWIPE_MIN && total_dy.abs() > total_dx.abs() * 1.2 {
					touch.edge_swiped = true;
					out.events.push(json!({
						"event": "ui_touch", "phase": "swipe", "target": "pill", "dir": "up",
						"x": round3(x), "y": round3(y),
					}));
				}
			}
			Route::UiBackdrop => {}
			Route::EdgeBottom => {
				let total_dy = y - touch.start_y;
				let total_dx = x - touch.start_x;
				if !touch.edge_swiped && total_dy <= -EDGE_SWIPE_MIN && total_dy.abs() > total_dx.abs() * 1.2 {
					touch.edge_swiped = true;
					out.events.push(json!({
						"event": "ui_touch", "phase": "swipe", "target": "edge", "dir": "up",
						"x": round3(x), "y": round3(y),
					}));
				}
			}
			Route::EdgeTop => {
				let total_dy = y - touch.start_y;
				let total_dx = x - touch.start_x;
				if !touch.edge_swiped && total_dy >= EDGE_SWIPE_MIN && total_dy.abs() > total_dx.abs() * 1.2 {
					touch.edge_swiped = true;
					out.events.push(json!({
						"event": "ui_touch", "phase": "swipe", "target": "edge", "dir": "down",
						"x": round3(x), "y": round3(y),
					}));
				}
			}
			Route::Character => {
				if self.config.character_touch {
					self.update_look_from_point(x, y);
					let zone = Zone::from_point(x, y, self.framing);
					let pettable = matches!(zone, Zone::Head | Zone::Face);
					fx.set_finger(Some((x, y)), pettable || touch.petting);

					if pettable {
						touch.pet_dist += step;
						if dx.abs() > 0.008 {
							let sign = if dx > 0.0 { 1 } else { -1 };
							if touch.last_dx_sign != 0 && sign != touch.last_dx_sign {
								touch.reversals += 1;
							}
							touch.last_dx_sign = sign;
						}
						// Engage petting on either a back-and-forth rub or a smooth sustained stroke.
						if !touch.petting && (touch.pet_dist >= 0.075 || (touch.reversals >= 1 && touch.pet_dist >= 0.04)) {
							touch.petting = true;
							touch.pet_zone = zone;
							self.pet_is_cheek = zone == Zone::Face;
						}
						if touch.petting {
							// Head leans gently in the direction of the stroke.
							self.pet_target_sway = ((x - 0.5) * 1.1 + dx * 6.0).clamp(-0.45, 0.45);
							if self.t - touch.last_pet_fx >= 0.22 {
								touch.last_pet_fx = self.t;
								fx.spawn_hearts(x, y, 1);
								fx.spawn_sparkles(x, y, 2, true);
							}
							if self.t - touch.last_pet_reaction >= 1.45 {
								touch.last_pet_reaction = self.t;
								out.reactions.push(if touch.pet_zone == Zone::Face { "cheek_rub" } else { "headpat" });
							}
							if !touch.pet_event_sent {
								touch.pet_event_sent = true;
								out.events.push(json!({
									"event": "touch", "kind": "pet", "zone": touch.pet_zone.name(),
									"x": round3(x), "y": round3(y),
								}));
							}
						}
					}
				}
			}
		}

		self.active = Some(touch);
	}

	fn handle_up(&mut self, id: u64, x: f32, y: f32, fx: &mut FxState, out: &mut TouchOutput) {
		let Some(touch) = self.active.take() else { return };
		if touch.id != id {
			self.active = Some(touch);
			return;
		}
		fx.set_finger(None, false);
		let duration = (self.t - touch.start_t).max(0.0);
		let dx = x - touch.start_x;
		let dy = y - touch.start_y;
		let displacement = dx.hypot(dy);
		let is_tap = touch.total_dist <= TAP_MAX_DIST && duration <= TAP_MAX_TIME && !touch.long_press_fired;

		match touch.route {
			Route::ConsumedWake => {}
			Route::UiPanel => {
				out.events.push(json!({
					"event": "ui_touch", "phase": "up", "target": "panel",
					"x": round3(x), "y": round3(y),
				}));
				if is_tap {
					out.events.push(json!({
						"event": "ui_touch", "phase": "tap", "target": "panel",
						"x": round3(touch.start_x), "y": round3(touch.start_y),
					}));
				} else if displacement >= SWIPE_MIN_DIST {
					let dir = swipe_dir(dx, dy);
					out.events.push(json!({
						"event": "ui_touch", "phase": "swipe", "target": "panel", "dir": dir,
						"x": round3(x), "y": round3(y), "dx": round3(dx), "dy": round3(dy),
					}));
				}
			}
			Route::UiPill => {
				if !touch.edge_swiped {
					if is_tap {
						out.events.push(json!({
							"event": "ui_touch", "phase": "tap", "target": "pill",
							"x": round3(touch.start_x), "y": round3(touch.start_y),
						}));
					} else if displacement >= EDGE_SWIPE_MIN {
						out.events.push(json!({
							"event": "ui_touch", "phase": "swipe", "target": "pill", "dir": swipe_dir(dx, dy),
							"x": round3(x), "y": round3(y),
						}));
					}
				}
			}
			Route::UiBackdrop => {
				if is_tap || (displacement >= SWIPE_MIN_DIST && swipe_dir(dx, dy) == "down") {
					out.events.push(json!({
						"event": "ui_touch", "phase": "tap", "target": "backdrop",
						"x": round3(x), "y": round3(y),
					}));
				}
			}
			Route::EdgeBottom | Route::EdgeTop => {
				if !touch.edge_swiped && is_tap && self.config.character_touch {
					// A short tap near an edge (without swiping) still feels responsive as a gentle tap.
					let zone = Zone::from_point(x, y, self.framing);
					self.handle_character_tap(x, y, zone, fx, out);
				}
			}
			Route::Character => {
				if !self.config.character_touch {
					return;
				}
				if touch.petting {
					// Finishing a headpat leaves a warm celebratory sparkle flourish.
					fx.spawn_hearts(x, y, 2);
					fx.spawn_sparkles(x, y, 3, true);
					self.look_until = self.t + LOOK_LINGER;
					return;
				}
				if touch.long_press_fired {
					self.look_until = self.t + LOOK_LINGER;
					return;
				}
				if is_tap {
					let zone = Zone::from_point(touch.start_x, touch.start_y, self.framing);
					self.handle_character_tap(touch.start_x, touch.start_y, zone, fx, out);
				} else if displacement >= SWIPE_MIN_DIST && dy <= -SWIPE_MIN_DIST && dy.abs() > dx.abs() * 1.4 && self.capture.edge_swipe && touch.start_y > 0.65 {
					// Generous upward swipe from the lower third also brings up the Quick Dock smoothly.
					out.events.push(json!({
						"event": "ui_touch", "phase": "swipe", "target": "edge", "dir": "up",
						"x": round3(x), "y": round3(y),
					}));
				} else {
					self.look_until = self.t + LOOK_LINGER;
				}
			}
		}
	}

	fn handle_cancel(&mut self, id: u64, fx: &mut FxState) {
		if self.active.as_ref().is_some_and(|a| a.id == id) {
			self.active = None;
			fx.set_finger(None, false);
		}
	}

	fn handle_character_tap(&mut self, x: f32, y: f32, zone: Zone, fx: &mut FxState, out: &mut TouchOutput) {
		let is_double = self
			.last_tap
			.is_some_and(|(lt, lx, ly, lz)| self.t - lt <= DOUBLE_TAP_GAP && (x - lx).hypot(y - ly) <= DOUBLE_TAP_DIST && lz == zone);
		self.last_tap = if is_double { None } else { Some((self.t, x, y, zone)) };
		self.update_look_from_point(x, y);
		self.look_until = self.t + LOOK_LINGER;
		out.poke_director = true;

		if is_double {
			if zone != Zone::Background {
				out.reactions.push("poke_giggle");
				fx.spawn_hearts(x, y, 2);
				fx.spawn_sparkles(x, y, 5, true);
			} else {
				fx.spawn_sparkles(x, y, 4, false);
			}
			out.events.push(json!({
				"event": "touch", "kind": "double_tap", "zone": zone.name(),
				"x": round3(x), "y": round3(y),
			}));
			return;
		}

		match zone {
			Zone::Head => {
				out.reactions.push("headpat");
				fx.spawn_hearts(x, y, 1);
				fx.spawn_sparkles(x, y, 3, true);
				out.events.push(json!({
					"event": "touch", "kind": "tap", "zone": "head",
					"x": round3(x), "y": round3(y),
				}));
			}
			Zone::Face => {
				self.poke_toggle = !self.poke_toggle;
				out.reactions.push(if self.poke_toggle { "poke_surprised" } else { "poke_giggle" });
				out.blink = true;
				fx.spawn_sparkles(x, y, 4, true);
				out.events.push(json!({
					"event": "touch", "kind": "poke", "zone": "face",
					"x": round3(x), "y": round3(y),
				}));
			}
			Zone::Body => {
				self.poke_toggle = !self.poke_toggle;
				out.reactions.push(if self.poke_toggle { "poke_giggle" } else { "look_up" });
				fx.spawn_sparkles(x, y, 3, false);
				out.events.push(json!({
					"event": "touch", "kind": "poke", "zone": "body",
					"x": round3(x), "y": round3(y),
				}));
			}
			Zone::Background => {
				fx.spawn_sparkles(x, y, 2, false);
				out.events.push(json!({
					"event": "touch", "kind": "tap", "zone": "background",
					"x": round3(x), "y": round3(y),
				}));
			}
		}
	}

	fn classify_route(&self, x: f32, y: f32) -> Route {
		if self.capture.modal {
			if self.capture.panel.is_some_and(|r| in_rect(x, y, r)) {
				return Route::UiPanel;
			}
			return Route::UiBackdrop;
		}
		if self.capture.pill.is_some_and(|r| in_rect(x, y, r)) {
			return Route::UiPill;
		}
		if self.capture.edge_swipe && y >= 0.88 {
			return Route::EdgeBottom;
		}
		if self.capture.edge_swipe && y <= 0.09 {
			return Route::EdgeTop;
		}
		Route::Character
	}

	fn new_touch(&self, id: u64, route: Route, x: f32, y: f32) -> ActiveTouch {
		ActiveTouch {
			id,
			route,
			start_x: x,
			start_y: y,
			x,
			y,
			start_t: self.t,
			total_dist: 0.0,
			last_dx_sign: 0,
			reversals: 0,
			pet_dist: 0.0,
			petting: false,
			pet_zone: Zone::Background,
			pet_event_sent: false,
			last_pet_fx: -10.0,
			last_pet_reaction: -10.0,
			long_press_fired: false,
			last_ui_move: -10.0,
			edge_swiped: false,
		}
	}

	fn update_look_from_point(&mut self, x: f32, y: f32) {
		let eye_y = Zone::eye_line(self.framing);
		let lx = ((x - 0.5) * 1.8).clamp(-1.0, 1.0);
		let ly = ((eye_y - y) * 2.0).clamp(-1.0, 1.0);
		self.look_target = (lx, ly);
		self.look_until = self.t + LOOK_LINGER;
	}

	/// Advance timers (long press detection, smooth petting & eye-tracking springs).
	pub fn tick(&mut self, dt: f32, fx: &mut FxState) -> TouchOutput {
		let mut out = TouchOutput::default();
		let dt = dt.clamp(0.0, 0.1);
		self.t += dt;

		let mut actively_petting = false;
		if let Some(touch) = &mut self.active {
			actively_petting = touch.petting;
			// Long press detection while finger stays still.
			if !touch.long_press_fired && !touch.petting && touch.total_dist <= TAP_MAX_DIST && self.t - touch.start_t >= LONG_PRESS_TIME {
				touch.long_press_fired = true;
				match touch.route {
					Route::UiPill => {
						out.events.push(json!({
							"event": "ui_touch", "phase": "long_press", "target": "pill",
							"x": round3(touch.x), "y": round3(touch.y),
						}));
					}
					Route::UiPanel => {
						out.events.push(json!({
							"event": "ui_touch", "phase": "long_press", "target": "panel",
							"x": round3(touch.x), "y": round3(touch.y),
						}));
					}
					Route::Character if self.config.character_touch => {
						let zone = Zone::from_point(touch.x, touch.y, self.framing);
						if matches!(zone, Zone::Head | Zone::Face) {
							touch.petting = true;
							touch.pet_zone = zone;
							touch.pet_event_sent = true;
							self.pet_is_cheek = zone == Zone::Face;
							actively_petting = true;
							out.reactions.push(if zone == Zone::Face { "cheek_rub" } else { "headpat" });
							fx.spawn_hearts(touch.x, touch.y, 2);
							fx.spawn_sparkles(touch.x, touch.y, 3, true);
							out.events.push(json!({
								"event": "touch", "kind": "pet", "zone": zone.name(),
								"x": round3(touch.x), "y": round3(touch.y),
							}));
						} else {
							fx.spawn_sparkles(touch.x, touch.y, 3, false);
							out.events.push(json!({
								"event": "touch", "kind": "long_press", "zone": zone.name(),
								"x": round3(touch.x), "y": round3(touch.y),
							}));
						}
					}
					_ => {}
				}
			}
			// Keep eye-tracking fresh while holding on the character.
			if touch.route == Route::Character && self.config.character_touch {
				self.look_until = self.t + LOOK_LINGER;
			}
		}

		let look_active = self.config.enabled && self.config.character_touch && self.t <= self.look_until && !self.capture.modal;
		self.look_weight.update(if look_active { 1.0 } else { 0.0 }, dt);
		self.pet_weight.update(if actively_petting { 1.0 } else { 0.0 }, dt);
		self.pet_sway.update(if actively_petting { self.pet_target_sway } else { 0.0 }, dt);
		out
	}

	/// Real-time continuous tactile blend applied smoothly onto the character's `Pose` each frame:
	/// finger eye-tracking and gentle headpat/cheek-rub lean & warmth.
	pub fn apply_pose(&self, pose: &mut Pose) {
		let lw = self.look_weight.value.clamp(0.0, 1.0);
		if lw > 0.005 {
			pose.gaze_x = (pose.gaze_x * (1.0 - lw) + self.look_target.0 * lw).clamp(-1.0, 1.0);
			pose.gaze_y = (pose.gaze_y * (1.0 - lw) + self.look_target.1 * lw).clamp(-1.0, 1.0);
			pose.head_yaw = (pose.head_yaw + self.look_target.0 * 0.35 * lw).clamp(-1.0, 1.0);
			pose.head_pitch = (pose.head_pitch + self.look_target.1 * 0.28 * lw).clamp(-1.0, 1.0);
		}
		let pw = self.pet_weight.value.clamp(0.0, 1.0);
		if pw > 0.005 {
			pose.smile = (pose.smile + 0.55 * pw).clamp(-1.0, 1.0);
			pose.eye_smile = (pose.eye_smile + 0.72 * pw).clamp(0.0, 1.0);
			pose.cheek = (pose.cheek + if self.pet_is_cheek { 0.85 } else { 0.65 } * pw).clamp(0.0, 1.0);
			pose.head_roll = (pose.head_roll + self.pet_sway.value * pw).clamp(-1.0, 1.0);
			pose.head_pitch = (pose.head_pitch - 0.12 * pw).clamp(-1.0, 1.0);
		}
	}
}

fn swipe_dir(dx: f32, dy: f32) -> &'static str {
	if dx.abs() > dy.abs() {
		if dx > 0.0 { "right" } else { "left" }
	} else if dy > 0.0 {
		"down"
	} else {
		"up"
	}
}

fn round3(v: f32) -> f64 {
	((v as f64) * 1000.0).round() / 1000.0
}

#[cfg(test)]
mod tests {
	use super::*;

	fn down(x: f32, y: f32) -> TouchSample {
		TouchSample { id: 1, phase: Phase::Down, x, y }
	}
	fn mv(x: f32, y: f32) -> TouchSample {
		TouchSample { id: 1, phase: Phase::Move, x, y }
	}
	fn up(x: f32, y: f32) -> TouchSample {
		TouchSample { id: 1, phase: Phase::Up, x, y }
	}

	#[test]
	fn zones_match_framing() {
		assert_eq!(Zone::from_point(0.5, 0.16, Framing::Upper), Zone::Head);
		assert_eq!(Zone::from_point(0.5, 0.36, Framing::Upper), Zone::Face);
		assert_eq!(Zone::from_point(0.5, 0.65, Framing::Upper), Zone::Body);
		assert_eq!(Zone::from_point(0.05, 0.40, Framing::Upper), Zone::Background);
		assert_eq!(Zone::from_point(0.5, 0.45, Framing::Bust), Zone::Face);
		assert_eq!(Zone::from_point(0.5, 0.12, Framing::Full), Zone::Head);
	}

	#[test]
	fn touching_a_sleeping_screen_wakes_it_and_consumes_that_touch() {
		let mut engine = TouchEngine::new(Framing::Upper);
		let mut fx = FxState::new(1);
		let o1 = engine.on_sample(down(0.5, 0.35), true, &mut fx);
		assert!(o1.wake_screen && o1.poke_director);
		assert_eq!(o1.events[0]["event"], "touch_wake");
		let o2 = engine.on_sample(up(0.5, 0.35), false, &mut fx);
		assert!(o2.events.is_empty(), "releasing the wake tap does not poke the character");
	}

	#[test]
	fn stroking_the_head_triggers_headpat_hearts_and_pose_warmth() {
		let mut engine = TouchEngine::new(Framing::Upper);
		let mut fx = FxState::new(2);
		engine.on_sample(down(0.45, 0.16), false, &mut fx);
		let mut pet_events = Vec::new();
		let mut reactions = Vec::new();
		for &(x, y) in &[(0.52, 0.16), (0.58, 0.17), (0.48, 0.16), (0.42, 0.17), (0.55, 0.16)] {
			engine.tick(0.08, &mut fx);
			let o = engine.on_sample(mv(x, y), false, &mut fx);
			pet_events.extend(o.events);
			reactions.extend(o.reactions);
		}
		assert_eq!(pet_events.len(), 1, "one clean pet event per headpat session: {pet_events:?}");
		assert_eq!(pet_events[0]["kind"], "pet");
		assert_eq!(pet_events[0]["zone"], "head");
		assert!(reactions.contains(&"headpat"));
		assert!(fx.count() > 1, "hearts and sparkles spawned");

		let mut pose = Pose::default();
		engine.tick(0.1, &mut fx);
		engine.apply_pose(&mut pose);
		assert!(pose.smile > 0.2 && pose.eye_smile > 0.2 && pose.cheek > 0.2, "warm petting pose: {pose:?}");
		engine.on_sample(up(0.55, 0.16), false, &mut fx);
	}

	#[test]
	fn tapping_face_pokes_with_blinks_and_finger_eye_tracking() {
		let mut engine = TouchEngine::new(Framing::Upper);
		let mut fx = FxState::new(3);
		engine.on_sample(down(0.65, 0.36), false, &mut fx);
		engine.tick(0.06, &mut fx);
		let o = engine.on_sample(up(0.65, 0.36), false, &mut fx);
		assert!(o.blink);
		assert_eq!(o.events[0]["kind"], "poke");
		assert_eq!(o.events[0]["zone"], "face");
		let mut pose = Pose::default();
		for _ in 0..10 {
			engine.tick(0.04, &mut fx);
		}
		engine.apply_pose(&mut pose);
		assert!(pose.gaze_x > 0.1, "eyes track where the user touched: {}", pose.gaze_x);
	}

	#[test]
	fn modal_ui_captures_panel_taps_and_dismisses_on_backdrop_without_poking_character() {
		let mut engine = TouchEngine::new(Framing::Upper);
		let mut fx = FxState::new(4);
		engine.set_capture(TouchCapture {
			modal: true,
			panel: Some([0.05, 0.45, 0.95, 0.98]),
			pill: None,
			edge_swipe: false,
		});
		// Tap inside panel.
		let d = engine.on_sample(down(0.5, 0.70), false, &mut fx);
		assert_eq!(d.events[0]["event"], "ui_touch");
		assert_eq!(d.events[0]["target"], "panel");
		let u = engine.on_sample(up(0.5, 0.70), false, &mut fx);
		assert!(u.events.iter().any(|e| e["phase"] == "tap" && e["target"] == "panel"));
		assert!(u.reactions.is_empty(), "panel tap never pokes the character");

		// Tap backdrop above panel (directly over the character's face!).
		engine.on_sample(down(0.5, 0.30), false, &mut fx);
		let u2 = engine.on_sample(up(0.5, 0.30), false, &mut fx);
		assert_eq!(u2.events.len(), 1);
		assert_eq!(u2.events[0]["target"], "backdrop");
		assert!(u2.reactions.is_empty(), "backdrop dismiss never pokes the character");
	}

	#[test]
	fn bottom_edge_swipe_up_and_pill_tap_route_to_ui() {
		let mut engine = TouchEngine::new(Framing::Upper);
		let mut fx = FxState::new(5);
		engine.set_capture(TouchCapture {
			modal: false,
			panel: None,
			pill: Some([0.32, 0.91, 0.68, 0.98]),
			edge_swipe: true,
		});
		// Tap pill.
		engine.on_sample(down(0.5, 0.94), false, &mut fx);
		let o = engine.on_sample(up(0.5, 0.94), false, &mut fx);
		assert_eq!(o.events[0]["event"], "ui_touch");
		assert_eq!(o.events[0]["target"], "pill");
		assert_eq!(o.events[0]["phase"], "tap");

		// Edge swipe up outside the pill.
		engine.on_sample(down(0.15, 0.95), false, &mut fx);
		let sw = engine.on_sample(mv(0.16, 0.84), false, &mut fx);
		assert_eq!(sw.events[0]["phase"], "swipe");
		assert_eq!(sw.events[0]["dir"], "up");
		assert_eq!(sw.events[0]["target"], "edge");
		engine.on_sample(up(0.16, 0.84), false, &mut fx);
	}
}
