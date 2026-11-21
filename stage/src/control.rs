//! The command channel into the stage and the event channel out of it.
//!
//! Commands are JSON objects, one per line, from standard input, a local
//! socket, or a timed script file (used by tests):
//!
//! ```text
//! {"state": "speaking"}
//! {"mouth": 0.7}
//! {"look": [0.2, -0.1]}
//! {"blink": true}
//! {"set": {"ParamCheek": 1.0, "ParamAngleX": 20}, "ease": 0.3}
//! {"set": {"ParamCheek": null}}
//! {"clear": true}
//! {"emotion": "happy", "intensity": 0.8}
//! {"gesture": "nod"}
//! {"random_gestures": false}
//! {"perform": {"syllables": "eaoe", "events": [[0, "nod", 0.7]]}}
//! {"syllable": 2}
//! {"emotion": "happy", "expression": "Smile"}
//! {"clock": 21.5}
//! {"poke": true}
//! {"heard": 0.4}
//! {"temperament": {"energy": 1.2, "expressiveness": 0.8}}
//! {"gestures_off": ["wave", "stretch"]}
//! {"define": {"name": "wiggle", "kind": "gesture", "needs": ["head_roll"], "tracks": {"head_roll": [[0, 0], [0.3, 0.4], [0.6, 0]]}}}
//! {"undefine": "wiggle"}
//! {"describe": true}
//! {"try_animation": "/var/lib/companion/characters/ada/animations/wave.vrma"}
//! {"overlay": {"slot": "caption", "image": "caption-3.png", "anchor": "bottom"}}
//! {"overlay": {"slot": "caption", "image": null}}
//! {"screen": "dim"}
//! {"model_motions": 0.5}
//! {"quit": true}
//! ```
//!
//! `clock` is the local time of day in hours (the character is sleepy at night); `poke` says someone
//! is there (the button was pressed); `heard` is the loudness of the person speaking, 0 to 1, sent
//! while the character listens. `temperament` is how lively and how expressive the character is (1 is
//! usual, 0.4 to 1.6); `gestures_off` names gestures and idle actions it never starts by itself.
//! `define` adds a gesture or idle action, or changes one, as the library writes it (the settings page's
//! editor); `undefine` puts a changed one back as built, or takes an added one away; `describe` asks for
//! the whole library, sent back as a `library` event.
//!
//! `emotion` changes the mood (how the character moves, its face, and which
//! gestures it makes by itself); `gesture` plays one of the library's
//! gestures on top of whatever it is doing; `intensity` (0 to 1, default 1)
//! applies to both.
//!
//! `set` drives named puppet parameters directly, for expressions and
//! previews; `null` or `clear` hands them back to the built-in behaviour.
//! `ease` is the blend time in seconds (default 0.25).
//!
//! `overlay` shows a picture from the overlay folder over the character, in a named slot (a caption,
//! the microphone-off sign), or with `"image": null` fades the slot out; `screen` dims the screen or
//! makes it dark (`"on"`, `"dim"`, `"off"`). See overlay.rs.
//!
//! `model_motions` is how much of a Live2D-format model's own idle motions shows, 0 (off) to 1 (as its
//! artist made them). See live2d_motion.rs.
//!
//! A script line also carries `"at": seconds`.

use std::io::{BufRead, BufReader, Write};
use std::os::unix::fs::FileTypeExt;
use std::os::unix::net::{UnixListener, UnixStream};
use std::path::Path;
use std::sync::mpsc::Sender;
use std::sync::{Arc, Mutex};

use serde_json::Value;

use crate::behaviour::State;
use crate::overlay::{self, Anchor, Screen, Slide};
use crate::touch::{Phase as TouchPhase, Rect, TouchCapture, TouchConfig, TouchSample};

#[derive(Clone, Debug, PartialEq)]
pub enum Command {
	Mouth(f32),
	State(State),
	Look(f32, f32),
	Blink,
	/// Drive a named parameter directly: name, value, blend time.
	Set(String, [f32; 2], f32),
	/// Hand a parameter back to the built-in behaviour: name, blend time.
	Unset(String, f32),
	/// Hand every parameter back.
	ClearAll(f32),
	/// Change mood: name, intensity.
	Emotion(String, f32),
	/// Play a gesture: name, intensity.
	Gesture(String, f32),
	/// Let the mood start gestures by itself, or not.
	RandomGestures(bool),
	/// Show one of the model's own expressions with the mood, or none.
	Expression(Option<String>),
	/// A sentence starts: its syllables' mouth shapes and the movements tied to them.
	Perform(crate::speech::Performance),
	/// Syllable k of the sentence is being heard.
	Syllable(usize),
	/// The local time of day, in hours.
	Clock(f32),
	/// Someone is there.
	Poke,
	/// How loud the person speaking is, 0 to 1.
	Heard(f32),
	/// How lively and how expressive the character is, 1 usual.
	Temperament(f32, f32),
	/// Gestures and idle actions it never starts by itself.
	GesturesOff(Vec<String>),
	/// Add or change a clip.
	Define(Value),
	/// Put a changed clip back, or take an added one away.
	Undefine(String),
	/// Send the whole library.
	Describe,
	/// Play a VRM Animation clip once from this file (a VRM avatar trying one before it is kept).
	TryAnimation(std::path::PathBuf),
	/// Show a picture from the overlay folder in a slot, or (None) fade the slot out.
	Overlay { slot: String, image: Option<String>, anchor: Anchor, layer: i32, slide: Slide, scrim: f32 },
	/// Light the screen, dim it, or make it dark.
	Screen(Screen),
	/// How much of a Live2D-format model's own idle motions shows, 0 to 1.
	ModelMotions(f32),
	/// Configure touchscreen features (enabled, character petting/poking, GPU touch effects).
	TouchConfig(TouchConfig),
	/// Active touch UI hit regions (modal sheet/dock panel, floating pill, edge swipes).
	TouchCapture(TouchCapture),
	/// Simulated raw touch input (for scripted tests and virtual-device testing).
	TouchSim(TouchSample),
	Quit,
}

const DEFAULT_EASE: f32 = 0.25;

/// `{"syllables": "eaoe", "events": [[syllable, "gesture", strength], ...]}`
fn parse_performance(val: &Value) -> Result<crate::speech::Performance, String> {
	let syllables = val.get("syllables").and_then(Value::as_str).ok_or("\"perform\" needs \"syllables\"")?;
	if syllables.len() > 2000 || !syllables.bytes().all(|b| b"aeiou".contains(&b)) {
		return Err("\"syllables\" must be letters a, e, i, o and u".into());
	}
	let mut events = Vec::new();
	for e in val.get("events").and_then(Value::as_array).map(|a| a.as_slice()).unwrap_or(&[]) {
		let item = e.as_array().filter(|a| a.len() == 3).ok_or("each event is [syllable, gesture, strength]")?;
		let at = item[0].as_u64().ok_or("an event's syllable must be a number")? as usize;
		let name = item[1].as_str().ok_or("an event names a gesture")?.to_string();
		let strength = item[2].as_f64().ok_or("an event's strength must be a number")? as f32;
		events.push((at, name, strength.clamp(0.0, 1.5)));
	}
	Ok(crate::speech::Performance { syllables: syllables.as_bytes().to_vec(), events })
}

/// Parse one line. Returns the optional `at` time and the commands it holds.
pub fn parse_line(line: &str) -> Result<(Option<f32>, Vec<Command>), String> {
	let v: Value = serde_json::from_str(line).map_err(|e| format!("not valid JSON: {e}"))?;
	let Some(obj) = v.as_object() else {
		return Err("a command must be a JSON object".into());
	};
	let mut at = None;
	let mut out = Vec::new();
	let ease = match obj.get("ease") {
		Some(v) => v.as_f64().filter(|e| *e >= 0.0).ok_or("\"ease\" must be a number of seconds, 0 or more")? as f32,
		None => DEFAULT_EASE,
	};
	let intensity = match obj.get("intensity") {
		Some(v) => v.as_f64().filter(|e| (0.0..=1.0).contains(e)).ok_or("\"intensity\" must be between 0 and 1")? as f32,
		None => 1.0,
	};
	for (key, val) in obj {
		match key.as_str() {
			"at" => at = Some(val.as_f64().ok_or("\"at\" must be a number")? as f32),
			"ease" | "intensity" => {}
			"emotion" => out.push(Command::Emotion(val.as_str().ok_or("\"emotion\" must be a name")?.to_string(), intensity)),
			"gesture" => out.push(Command::Gesture(val.as_str().ok_or("\"gesture\" must be a name")?.to_string(), intensity)),
			"expression" => out.push(Command::Expression(if val.is_null() {
				None
			} else {
				Some(val.as_str().ok_or("\"expression\" must be a name or null")?.to_string())
			})),
			"random_gestures" => out.push(Command::RandomGestures(val.as_bool().ok_or("\"random_gestures\" must be true or false")?)),
			"set" => {
				let items = val.as_object().ok_or("\"set\" must be an object of parameter names and values")?;
				for (name, v) in items {
					if v.is_null() {
						out.push(Command::Unset(name.clone(), ease));
					} else if let Some(x) = v.as_f64() {
						out.push(Command::Set(name.clone(), [x as f32, 0.0], ease));
					} else if let Some(xy) = v.as_array().filter(|a| a.len() == 2) {
						let x = xy[0].as_f64().ok_or("a \"set\" value must be a number or [x, y]")? as f32;
						let y = xy[1].as_f64().ok_or("a \"set\" value must be a number or [x, y]")? as f32;
						out.push(Command::Set(name.clone(), [x, y], ease));
					} else {
						return Err("a \"set\" value must be a number, [x, y] or null".into());
					}
				}
			}
			"clear" => {
				if val.as_bool() == Some(true) {
					out.push(Command::ClearAll(ease));
				}
			}
			"mouth" => out.push(Command::Mouth(val.as_f64().ok_or("\"mouth\" must be a number")? as f32)),
			"syllable" => out.push(Command::Syllable(val.as_u64().ok_or("\"syllable\" must be a number")? as usize)),
			"perform" => out.push(Command::Perform(parse_performance(val)?)),
			"clock" => {
				let hour = val.as_f64().filter(|h| (0.0..24.0).contains(h)).ok_or("\"clock\" must be the hour, 0 to 24")?;
				out.push(Command::Clock(hour as f32));
			}
			"poke" => {
				if val.as_bool() == Some(true) {
					out.push(Command::Poke);
				}
			}
			"heard" => out.push(Command::Heard(val.as_f64().ok_or("\"heard\" must be a number")?.clamp(0.0, 1.0) as f32)),
			"temperament" => {
				let number = |key: &str| {
					val.get(key).and_then(Value::as_f64).map(|v| v.clamp(0.4, 1.6) as f32).ok_or(format!("\"temperament\" needs \"{key}\""))
				};
				out.push(Command::Temperament(number("energy")?, number("expressiveness")?));
			}
			"define" => {
				if !val.is_object() {
					return Err("\"define\" is a library entry with its \"name\"".into());
				}
				out.push(Command::Define(val.clone()));
			}
			"undefine" => out.push(Command::Undefine(val.as_str().ok_or("\"undefine\" names a gesture")?.to_string())),
			"describe" => {
				if val.as_bool() == Some(true) {
					out.push(Command::Describe);
				}
			}
			"gestures_off" => {
				let names = val.as_array().ok_or("\"gestures_off\" must be a list of names")?;
				out.push(Command::GesturesOff(names.iter().filter_map(Value::as_str).take(100).map(str::to_string).collect()));
			}
			"state" => {
				let s = val.as_str().ok_or("\"state\" must be a string")?;
				out.push(Command::State(State::parse(s).ok_or(format!("unknown state '{s}'"))?));
			}
			"look" => {
				let xy = val.as_array().filter(|a| a.len() == 2).ok_or("\"look\" must be [x, y]")?;
				let x = xy[0].as_f64().ok_or("\"look\" must hold numbers")? as f32;
				let y = xy[1].as_f64().ok_or("\"look\" must hold numbers")? as f32;
				out.push(Command::Look(x, y));
			}
			"blink" => {
				if val.as_bool() == Some(true) {
					out.push(Command::Blink);
				}
			}
			"try_animation" => {
				let path = val.as_str().filter(|p| p.len() < 4096).ok_or("\"try_animation\" names a .vrma file")?;
				if !path.to_ascii_lowercase().ends_with(".vrma") {
					return Err("\"try_animation\" names a .vrma file".into());
				}
				out.push(Command::TryAnimation(path.into()));
			}
			"overlay" => {
				let slot = val
					.get("slot")
					.and_then(Value::as_str)
					.filter(|s| overlay::valid_slot(s))
					.ok_or("\"overlay\" needs a \"slot\": lower-case letters, digits and dashes")?;
				let image = match val.get("image") {
					None | Some(Value::Null) => None,
					Some(v) => Some(
						v.as_str()
							.filter(|n| overlay::valid_name(n))
							.ok_or("an overlay's \"image\" is the name of a .png file in the overlay folder")?
							.to_string(),
					),
				};
				let anchor = match val.get("anchor") {
					None => Anchor::Bottom,
					Some(v) => v.as_str().and_then(Anchor::parse).ok_or(
						"\"anchor\" is top, bottom, center, top_left, top_right, bottom_left or bottom_right",
					)?,
				};
				let layer = match val.get("layer") {
					None => 0,
					Some(v) => v.as_i64().filter(|l| (-100..=100).contains(l)).ok_or("\"layer\" must be an integer -100..100")? as i32,
				};
				let slide = match val.get("slide") {
					None => Slide::None,
					Some(v) => v.as_str().and_then(Slide::parse).ok_or("\"slide\" is none, up or down")?,
				};
				let scrim = match val.get("scrim") {
					None => 0.0,
					Some(v) => v.as_f64().filter(|s| (0.0..=0.85).contains(s)).ok_or("\"scrim\" must be 0 to 0.85")? as f32,
				};
				out.push(Command::Overlay { slot: slot.to_string(), image, anchor, layer, slide, scrim });
			}
			"screen" => {
				out.push(Command::Screen(val.as_str().and_then(Screen::parse).ok_or("\"screen\" is on, dim or off")?))
			}
			"model_motions" => {
				let v = val.as_f64().filter(|v| (0.0..=1.0).contains(v)).ok_or("\"model_motions\" is a number from 0 to 1")?;
				out.push(Command::ModelMotions(v as f32))
			}
			"touch_config" => {
				let obj = val.as_object().ok_or("\"touch_config\" must be an object")?;
				let mut cfg = TouchConfig::default();
				if let Some(v) = obj.get("enabled") {
					cfg.enabled = v.as_bool().ok_or("\"touch_config.enabled\" must be true or false")?;
				}
				if let Some(v) = obj.get("character_touch") {
					cfg.character_touch = v.as_bool().ok_or("\"touch_config.character_touch\" must be true or false")?;
				}
				if let Some(v) = obj.get("effects") {
					cfg.effects = v.as_bool().ok_or("\"touch_config.effects\" must be true or false")?;
				}
				out.push(Command::TouchConfig(cfg));
			}
			"touch_capture" => {
				let obj = val.as_object().ok_or("\"touch_capture\" must be an object")?;
				let mut cap = TouchCapture::default();
				if let Some(v) = obj.get("modal") {
					cap.modal = v.as_bool().ok_or("\"touch_capture.modal\" must be true or false")?;
				}
				if let Some(v) = obj.get("edge_swipe") {
					cap.edge_swipe = v.as_bool().ok_or("\"touch_capture.edge_swipe\" must be true or false")?;
				}
				cap.panel = parse_opt_rect(obj.get("panel"), "panel")?;
				cap.pill = parse_opt_rect(obj.get("pill"), "pill")?;
				out.push(Command::TouchCapture(cap));
			}
			"touch_sim" => {
				let obj = val.as_object().ok_or("\"touch_sim\" must be an object")?;
				let phase = match obj.get("phase").and_then(Value::as_str) {
					Some("down") => TouchPhase::Down,
					Some("move") => TouchPhase::Move,
					Some("up") => TouchPhase::Up,
					Some("cancel") => TouchPhase::Cancel,
					_ => return Err("\"touch_sim.phase\" must be down, move, up or cancel".into()),
				};
				let x = obj.get("x").and_then(Value::as_f64).ok_or("\"touch_sim.x\" must be a number")? as f32;
				let y = obj.get("y").and_then(Value::as_f64).ok_or("\"touch_sim.y\" must be a number")? as f32;
				let id = obj.get("id").and_then(Value::as_u64).unwrap_or(1);
				out.push(Command::TouchSim(TouchSample { id, phase, x: x.clamp(0.0, 1.0), y: y.clamp(0.0, 1.0) }));
			}
			"quit" => {
				if val.as_bool() == Some(true) {
					out.push(Command::Quit);
				}
			}
			other => return Err(format!("unknown field '{other}'")),
		}
	}
	Ok((at, out))
}

fn parse_opt_rect(val: Option<&Value>, name: &str) -> Result<Option<Rect>, String> {
	let Some(v) = val else { return Ok(None) };
	if v.is_null() {
		return Ok(None);
	}
	let arr = v.as_array().filter(|a| a.len() == 4).ok_or(format!("\"{name}\" must be [x0, y0, x1, y1] or null"))?;
	let mut r = [0.0f32; 4];
	for (i, item) in arr.iter().enumerate() {
		r[i] = item.as_f64().ok_or(format!("\"{name}\" must contain numbers"))? as f32;
	}
	if r[2] < r[0] || r[3] < r[1] {
		return Err(format!("\"{name}\" must have x1 >= x0 and y1 >= y0"));
	}
	Ok(Some(r))
}

/// Timed commands, for reproducible tests.
pub struct Script {
	items: Vec<(f32, Command)>,
	next: usize,
}

impl Script {
	pub fn parse(text: &str) -> Result<Self, String> {
		let mut items = Vec::new();
		for (n, line) in text.lines().enumerate() {
			let line = line.trim();
			if line.is_empty() || line.starts_with('#') {
				continue;
			}
			let (at, commands) = parse_line(line).map_err(|e| format!("script line {}: {e}", n + 1))?;
			let at = at.ok_or(format!("script line {}: missing \"at\"", n + 1))?;
			items.extend(commands.into_iter().map(|c| (at, c)));
		}
		items.sort_by(|a, b| a.0.total_cmp(&b.0));
		Ok(Self { items, next: 0 })
	}

	/// Commands whose time has come.
	pub fn take_due(&mut self, t: f32) -> Vec<Command> {
		let mut out = Vec::new();
		while self.next < self.items.len() && self.items[self.next].0 <= t {
			out.push(self.items[self.next].1.clone());
			self.next += 1;
		}
		out
	}
}

/// Where events go: standard output and any connected socket clients.
///
/// The last "ready" event is kept and sent to each client as it connects, so
/// a client that connects after start-up (the usual case) still learns the
/// puppet's parameters.
#[derive(Clone, Default)]
pub struct Events {
	clients: Arc<Mutex<Vec<UnixStream>>>,
	ready: Arc<Mutex<Option<String>>>,
}

impl Events {
	pub fn emit(&self, event: Value) {
		let line = event.to_string();
		println!("{line}");
		if event.get("event").and_then(Value::as_str) == Some("ready") {
			if let Ok(mut ready) = self.ready.lock() {
				*ready = Some(line.clone());
			}
		}
		if let Ok(mut clients) = self.clients.lock() {
			clients.retain_mut(|c| writeln!(c, "{line}").is_ok());
		}
	}

	fn add_client(&self, mut client: UnixStream) {
		if let Ok(ready) = self.ready.lock() {
			if let Some(line) = ready.as_ref() {
				if writeln!(client, "{line}").is_err() {
					return;
				}
			}
		}
		if let Ok(mut clients) = self.clients.lock() {
			clients.push(client);
		}
	}
}

fn forward_lines(reader: impl BufRead, tx: &Sender<Command>, events: &Events) {
	for line in reader.lines() {
		let Ok(line) = line else { break };
		if line.trim().is_empty() {
			continue;
		}
		match parse_line(&line) {
			Ok((_, commands)) => {
				for c in commands {
					if tx.send(c).is_err() {
						return;
					}
				}
			}
			Err(e) => events.emit(serde_json::json!({"event": "error", "message": e})),
		}
	}
}

pub fn spawn_stdin(tx: Sender<Command>, events: Events) {
	std::thread::spawn(move || forward_lines(std::io::stdin().lock(), &tx, &events));
}

/// Listen on a local socket. Each client can send commands and receives events.
pub fn spawn_socket(path: &Path, tx: Sender<Command>, events: Events) -> Result<(), String> {
	if let Ok(meta) = std::fs::symlink_metadata(path) {
		if !meta.file_type().is_socket() {
			return Err(format!("{} exists and is not a socket", path.display()));
		}
		std::fs::remove_file(path).map_err(|e| format!("cannot replace {}: {e}", path.display()))?;
	}
	let listener = UnixListener::bind(path).map_err(|e| format!("cannot listen on {}: {e}", path.display()))?;
	std::thread::spawn(move || {
		for stream in listener.incoming().flatten() {
			if let Ok(writer) = stream.try_clone() {
				events.add_client(writer);
			}
			let tx = tx.clone();
			let events = events.clone();
			std::thread::spawn(move || forward_lines(BufReader::new(stream), &tx, &events));
		}
	});
	Ok(())
}

#[cfg(test)]
mod tests {
	use super::*;

	#[test]
	fn parses_commands() {
		assert_eq!(parse_line(r#"{"mouth": 0.5}"#).unwrap(), (None, vec![Command::Mouth(0.5)]));
		assert_eq!(
			parse_line(r#"{"state": "thinking"}"#).unwrap(),
			(None, vec![Command::State(State::Thinking)])
		);
		assert_eq!(parse_line(r#"{"look": [0.5, -1]}"#).unwrap(), (None, vec![Command::Look(0.5, -1.0)]));
		assert_eq!(parse_line(r#"{"quit": true}"#).unwrap(), (None, vec![Command::Quit]));
		assert_eq!(
			parse_line(r#"{"try_animation": "/x/wave.vrma"}"#).unwrap().1,
			vec![Command::TryAnimation("/x/wave.vrma".into())]
		);
		assert!(parse_line(r#"{"try_animation": "/etc/passwd"}"#).is_err());
		assert_eq!(parse_line(r#"{"quit": false}"#).unwrap(), (None, vec![]));
		assert_eq!(parse_line(r#"{"blink": true}"#).unwrap(), (None, vec![Command::Blink]));
		let (at, commands) = parse_line(r#"{"at": 1.5, "mouth": 1, "state": "speaking"}"#).unwrap();
		assert_eq!(at, Some(1.5));
		assert_eq!(commands.len(), 2);
		assert_eq!(parse_line(r#"{"clock": 21.5}"#).unwrap().1, vec![Command::Clock(21.5)]);
		assert!(parse_line(r#"{"clock": 25}"#).is_err());
		assert_eq!(parse_line(r#"{"poke": true}"#).unwrap().1, vec![Command::Poke]);
		assert_eq!(parse_line(r#"{"heard": 1.7}"#).unwrap().1, vec![Command::Heard(1.0)]);
		assert_eq!(
			parse_line(r#"{"temperament": {"energy": 3, "expressiveness": 0.8}}"#).unwrap().1,
			vec![Command::Temperament(1.6, 0.8)]
		);
		assert!(parse_line(r#"{"temperament": {"energy": 1}}"#).is_err());
		assert_eq!(parse_line(r#"{"gestures_off": ["wave"]}"#).unwrap().1, vec![Command::GesturesOff(vec!["wave".into()])]);
	}

	#[test]
	fn parses_overlay_and_screen_commands() {
		assert_eq!(
			parse_line(r#"{"overlay": {"slot": "caption", "image": "caption-3.png", "anchor": "bottom"}}"#).unwrap().1,
			vec![Command::Overlay {
				slot: "caption".into(),
				image: Some("caption-3.png".into()),
				anchor: Anchor::Bottom,
				layer: 0,
				slide: Slide::None,
				scrim: 0.0,
			}]
		);
		assert_eq!(
			parse_line(r#"{"overlay": {"slot": "touch-dock", "image": "dock-1.png", "anchor": "bottom", "layer": 30, "slide": "up", "scrim": 0.45}}"#)
				.unwrap()
				.1,
			vec![Command::Overlay {
				slot: "touch-dock".into(),
				image: Some("dock-1.png".into()),
				anchor: Anchor::Bottom,
				layer: 30,
				slide: Slide::Up,
				scrim: 0.45,
			}]
		);
		assert_eq!(
			parse_line(r#"{"overlay": {"slot": "mic-off", "image": null}}"#).unwrap().1,
			vec![Command::Overlay {
				slot: "mic-off".into(),
				image: None,
				anchor: Anchor::Bottom,
				layer: 0,
				slide: Slide::None,
				scrim: 0.0,
			}]
		);
		assert_eq!(parse_line(r#"{"screen": "off"}"#).unwrap().1, vec![Command::Screen(Screen::Off)]);
		assert_eq!(parse_line(r#"{"model_motions": 0.5}"#).unwrap().1, vec![Command::ModelMotions(0.5)]);
		assert!(parse_line(r#"{"model_motions": 2}"#).is_err());
		for bad in [
			r#"{"overlay": {"image": "a.png"}}"#,
			r#"{"overlay": {"slot": "caption", "image": "../../etc/passwd"}}"#,
			r#"{"overlay": {"slot": "caption", "image": "/run/x.png"}}"#,
			r#"{"overlay": {"slot": "caption", "image": "a.png", "anchor": "middle"}}"#,
			r#"{"overlay": {"slot": "caption", "image": "a.png", "slide": "left"}}"#,
			r#"{"overlay": {"slot": "caption", "image": "a.png", "scrim": 0.99}}"#,
			r#"{"screen": "sleep"}"#,
		] {
			assert!(parse_line(bad).is_err(), "{bad}");
		}
	}

	#[test]
	fn parses_touch_commands() {
		assert_eq!(
			parse_line(r#"{"touch_config": {"enabled": true, "character_touch": false, "effects": true}}"#).unwrap().1,
			vec![Command::TouchConfig(TouchConfig { enabled: true, character_touch: false, effects: true })]
		);
		assert_eq!(
			parse_line(r#"{"touch_capture": {"modal": true, "panel": [0.05, 0.5, 0.95, 0.98], "pill": null, "edge_swipe": false}}"#)
				.unwrap()
				.1,
			vec![Command::TouchCapture(TouchCapture {
				modal: true,
				panel: Some([0.05, 0.5, 0.95, 0.98]),
				pill: None,
				edge_swipe: false,
			})]
		);
		assert_eq!(
			parse_line(r#"{"touch_sim": {"phase": "down", "x": 0.5, "y": 0.2, "id": 7}}"#).unwrap().1,
			vec![Command::TouchSim(TouchSample { id: 7, phase: TouchPhase::Down, x: 0.5, y: 0.2 })]
		);
		for bad in [
			r#"{"touch_config": {"enabled": "yes"}}"#,
			r#"{"touch_capture": {"panel": [0.9, 0.5, 0.1, 0.8]}}"#,
			r#"{"touch_sim": {"phase": "hover", "x": 0.5, "y": 0.5}}"#,
		] {
			assert!(parse_line(bad).is_err(), "{bad}");
		}
	}

	#[test]
	fn parses_direct_parameter_commands() {
		let (_, c) = parse_line(r#"{"set": {"Cheek": 1}, "ease": 0.5}"#).unwrap();
		assert_eq!(c, vec![Command::Set("Cheek".into(), [1.0, 0.0], 0.5)]);
		let (_, c) = parse_line(r#"{"set": {"Head": [0.5, -1]}}"#).unwrap();
		assert_eq!(c, vec![Command::Set("Head".into(), [0.5, -1.0], DEFAULT_EASE)]);
		let (_, c) = parse_line(r#"{"set": {"Cheek": null}, "ease": 0}"#).unwrap();
		assert_eq!(c, vec![Command::Unset("Cheek".into(), 0.0)]);
		let (_, c) = parse_line(r#"{"clear": true}"#).unwrap();
		assert_eq!(c, vec![Command::ClearAll(DEFAULT_EASE)]);
		let (_, c) = parse_line(r#"{"perform": {"syllables": "aei", "events": [[1, "nod", 0.5]]}}"#).unwrap();
		assert_eq!(c, vec![Command::Perform(crate::speech::Performance {
			syllables: b"aei".to_vec(),
			events: vec![(1, "nod".into(), 0.5)],
		})]);
		let (_, c) = parse_line(r#"{"syllable": 3}"#).unwrap();
		assert_eq!(c, vec![Command::Syllable(3)]);
		for bad in [r#"{"perform": {"syllables": "xyz"}}"#, r#"{"perform": {"syllables": "a", "events": [[1, "nod"]]}}"#,
			r#"{"syllable": "two"}"#] {
			assert!(parse_line(bad).is_err(), "{bad}");
		}
		for bad in [r#"{"set": 3}"#, r#"{"set": {"Cheek": "pink"}}"#, r#"{"set": {"Cheek": 1}, "ease": -1}"#] {
			assert!(parse_line(bad).is_err(), "{bad}");
		}
	}

	#[test]
	fn rejects_bad_commands() {
		for bad in [
			"nonsense",
			"[1,2]",
			r#"{"mouth": "wide"}"#,
			r#"{"state": "dancing"}"#,
			r#"{"look": [1]}"#,
			r#"{"volume": 3}"#,
		] {
			assert!(parse_line(bad).is_err(), "{bad}");
		}
	}

	#[test]
	fn a_late_client_is_told_the_puppet_is_ready() {
		let events = Events::default();
		events.emit(serde_json::json!({"event": "ready", "puppet": "x"}));
		events.emit(serde_json::json!({"event": "heartbeat"}));
		let (ours, theirs) = UnixStream::pair().unwrap();
		events.add_client(ours);
		let mut line = String::new();
		BufReader::new(theirs).read_line(&mut line).unwrap();
		assert!(line.contains("\"ready\""), "{line}");
	}

	#[test]
	fn script_releases_commands_in_time_order() {
		let mut s = Script::parse(
			"# comment\n{\"at\": 2, \"mouth\": 1}\n\n{\"at\": 0.5, \"state\": \"speaking\"}\n{\"at\": 3, \"quit\": true}\n",
		)
		.unwrap();
		assert!(s.take_due(0.4).is_empty());
		assert_eq!(s.take_due(0.5), vec![Command::State(State::Speaking)]);
		assert_eq!(s.take_due(2.9), vec![Command::Mouth(1.0)]);
		assert_eq!(s.take_due(10.0), vec![Command::Quit]);
		assert!(s.take_due(11.0).is_empty());
		assert!(Script::parse("{\"mouth\": 1}").is_err());
	}
}
