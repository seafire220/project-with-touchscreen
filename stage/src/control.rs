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
//! {"quit": true}
//! ```
//!
//! `clock` is the local time of day in hours (the character is sleepy at night); `poke` says someone
//! is there (the button was pressed); `heard` is the loudness of the person speaking, 0 to 1, sent
//! while the character listens.
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
//! A script line also carries `"at": seconds`.

use std::io::{BufRead, BufReader, Write};
use std::os::unix::fs::FileTypeExt;
use std::os::unix::net::{UnixListener, UnixStream};
use std::path::Path;
use std::sync::mpsc::Sender;
use std::sync::{Arc, Mutex};

use serde_json::Value;

use crate::behaviour::State;

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
		assert_eq!(parse_line(r#"{"quit": false}"#).unwrap(), (None, vec![]));
		assert_eq!(parse_line(r#"{"blink": true}"#).unwrap(), (None, vec![Command::Blink]));
		let (at, commands) = parse_line(r#"{"at": 1.5, "mouth": 1, "state": "speaking"}"#).unwrap();
		assert_eq!(at, Some(1.5));
		assert_eq!(commands.len(), 2);
		assert_eq!(parse_line(r#"{"clock": 21.5}"#).unwrap().1, vec![Command::Clock(21.5)]);
		assert!(parse_line(r#"{"clock": 25}"#).is_err());
		assert_eq!(parse_line(r#"{"poke": true}"#).unwrap().1, vec![Command::Poke]);
		assert_eq!(parse_line(r#"{"heard": 1.7}"#).unwrap().1, vec![Command::Heard(1.0)]);
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
