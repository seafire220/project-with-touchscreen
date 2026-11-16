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
//! {"quit": true}
//! ```
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

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Command {
	Mouth(f32),
	State(State),
	Look(f32, f32),
	Blink,
	Quit,
}

/// Parse one line. Returns the optional `at` time and the commands it holds.
pub fn parse_line(line: &str) -> Result<(Option<f32>, Vec<Command>), String> {
	let v: Value = serde_json::from_str(line).map_err(|e| format!("not valid JSON: {e}"))?;
	let Some(obj) = v.as_object() else {
		return Err("a command must be a JSON object".into());
	};
	let mut at = None;
	let mut out = Vec::new();
	for (key, val) in obj {
		match key.as_str() {
			"at" => at = Some(val.as_f64().ok_or("\"at\" must be a number")? as f32),
			"mouth" => out.push(Command::Mouth(val.as_f64().ok_or("\"mouth\" must be a number")? as f32)),
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
			out.push(self.items[self.next].1);
			self.next += 1;
		}
		out
	}
}

/// Where events go: standard output and any connected socket clients.
#[derive(Clone, Default)]
pub struct Events {
	clients: Arc<Mutex<Vec<UnixStream>>>,
}

impl Events {
	pub fn emit(&self, event: Value) {
		let line = event.to_string();
		println!("{line}");
		if let Ok(mut clients) = self.clients.lock() {
			clients.retain_mut(|c| writeln!(c, "{line}").is_ok());
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
				if let Ok(mut clients) = events.clients.lock() {
					clients.push(writer);
				}
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
