//! Moods and gestures on the generic controls (docs/24-motion.md).
//!
//! An emotion is a **mood**: it changes how the character moves (how lively,
//! how strong its beats with speech), its resting posture and face, and
//! which gestures it makes by itself. A **gesture** is a short clip added on
//! top of whatever the character is doing, so it blends into speaking and
//! idling instead of replacing them. Both are written once, in control units,
//! in `stage/motions/library.json`, and reach each character through its
//! calibration; a gesture is offered only to characters that have every
//! control it needs.

use serde_json::Value;

use crate::behaviour::{Pose, State};
use crate::smooth::Spring;

/// The controls moods and gestures may move, in `Pose` field names.
pub const KEYS: [&str; 16] = [
	"head_yaw", "head_pitch", "head_roll", "body_yaw", "body_pitch", "body_roll", "gaze_x", "gaze_y", "brows",
	"brow_form", "smile", "eye_smile", "cheek", "arm_left", "arm_right", "shoulders",
];

fn slot<'a>(pose: &'a mut Pose, key: usize) -> &'a mut f32 {
	match KEYS[key] {
		"head_yaw" => &mut pose.head_yaw,
		"head_pitch" => &mut pose.head_pitch,
		"head_roll" => &mut pose.head_roll,
		"body_yaw" => &mut pose.body_yaw,
		"body_pitch" => &mut pose.body_pitch,
		"body_roll" => &mut pose.body_roll,
		"gaze_x" => &mut pose.gaze_x,
		"gaze_y" => &mut pose.gaze_y,
		"brows" => &mut pose.brows,
		"brow_form" => &mut pose.brow_form,
		"smile" => &mut pose.smile,
		"eye_smile" => &mut pose.eye_smile,
		"cheek" => &mut pose.cheek,
		"arm_left" => &mut pose.arm_left,
		"arm_right" => &mut pose.arm_right,
		_ => &mut pose.shoulders,
	}
}

/// Controls that run from 0 to 1; the rest run from -1 to 1.
fn one_sided(key: usize) -> bool {
	matches!(KEYS[key], "eye_smile" | "cheek")
}

fn key_index(name: &str) -> Result<usize, String> {
	KEYS.iter().position(|k| *k == name).ok_or(format!("unknown control '{name}'"))
}

#[derive(Clone, Debug)]
pub struct Clip {
	pub name: String,
	pub needs: Vec<usize>,
	tracks: Vec<(usize, Vec<(f32, f32)>)>,
	pub duration: f32,
}

impl Clip {
	/// The clip's offsets `t` seconds in; keys are joined by smooth steps.
	fn sample(&self, t: f32, out: &mut [f32; KEYS.len()], weight: f32) {
		for (key, points) in &self.tracks {
			let value = match points.iter().position(|(at, _)| *at > t) {
				None => points.last().map(|p| p.1).unwrap_or(0.0),
				Some(0) => points[0].1,
				Some(i) => {
					let (t0, v0) = points[i - 1];
					let (t1, v1) = points[i];
					let u = ((t - t0) / (t1 - t0).max(1e-4)).clamp(0.0, 1.0);
					v0 + (v1 - v0) * u * u * (3.0 - 2.0 * u)
				}
			};
			out[*key] += value * weight;
		}
	}
}

#[derive(Clone, Debug)]
pub struct Mood {
	pub name: String,
	offsets: Vec<(usize, f32)>,
	energy: f32,
	beats: f32,
	random_every: (f32, f32),
	gestures: Vec<(String, f32)>,
	on_enter: Option<String>,
}

#[derive(Clone, Debug)]
pub struct Library {
	pub moods: Vec<Mood>,
	pub clips: Vec<Clip>,
}

fn number(v: &Value, what: &str) -> Result<f32, String> {
	v.as_f64().map(|x| x as f32).ok_or(format!("{what} must be a number"))
}

impl Library {
	pub fn builtin() -> Self {
		Self::parse(include_str!("../motions/library.json")).expect("the built-in motion library is valid")
	}

	pub fn parse(text: &str) -> Result<Self, String> {
		let root: Value = serde_json::from_str(text).map_err(|e| format!("motion library: {e}"))?;
		let mut clips = Vec::new();
		for (name, g) in root.get("gestures").and_then(Value::as_object).ok_or("motion library has no gestures")? {
			let needs = g
				.get("needs")
				.and_then(Value::as_array)
				.ok_or(format!("gesture {name}: no 'needs'"))?
				.iter()
				.map(|k| key_index(k.as_str().unwrap_or("")))
				.collect::<Result<Vec<_>, _>>()?;
			let mut tracks = Vec::new();
			let mut duration: f32 = 0.0;
			for (key, points) in g.get("tracks").and_then(Value::as_object).ok_or(format!("gesture {name}: no tracks"))? {
				let mut pts = Vec::new();
				for p in points.as_array().ok_or(format!("gesture {name}: track {key} must be a list"))? {
					let pair = p.as_array().filter(|a| a.len() == 2).ok_or(format!("gesture {name}: keys are [seconds, value]"))?;
					pts.push((number(&pair[0], "a key's time")?, number(&pair[1], "a key's value")?));
				}
				if pts.len() < 2 || pts.windows(2).any(|w| w[1].0 <= w[0].0) {
					return Err(format!("gesture {name}: track {key} needs two or more keys in time order"));
				}
				if pts[0].1 != 0.0 || pts.last().unwrap().1 != 0.0 {
					return Err(format!("gesture {name}: track {key} must start and end at 0"));
				}
				duration = duration.max(pts.last().unwrap().0);
				tracks.push((key_index(key)?, pts));
			}
			clips.push(Clip { name: name.clone(), needs, tracks, duration });
		}
		let mut moods = Vec::new();
		for (name, m) in root.get("moods").and_then(Value::as_object).ok_or("motion library has no moods")? {
			let mut offsets = Vec::new();
			for (key, v) in m.get("offsets").and_then(Value::as_object).ok_or(format!("mood {name}: no offsets"))? {
				offsets.push((key_index(key)?, number(v, "an offset")?));
			}
			let every = m.get("random_every").and_then(Value::as_array).filter(|a| a.len() == 2);
			let every = every.ok_or(format!("mood {name}: random_every must be [min, max] seconds"))?;
			let mut gestures = Vec::new();
			for (g, w) in m.get("gestures").and_then(Value::as_object).ok_or(format!("mood {name}: no gestures"))? {
				if !clips.iter().any(|c| &c.name == g) {
					return Err(format!("mood {name}: no gesture called {g}"));
				}
				gestures.push((g.clone(), number(w, "a gesture's weight")?));
			}
			let on_enter = m.get("on_enter").and_then(Value::as_str).map(str::to_string);
			if let Some(g) = &on_enter {
				if !clips.iter().any(|c| &c.name == g) {
					return Err(format!("mood {name}: no gesture called {g}"));
				}
			}
			moods.push(Mood {
				name: name.clone(),
				offsets,
				energy: number(m.get("energy").unwrap_or(&Value::Null), "energy")?,
				beats: number(m.get("beats").unwrap_or(&Value::Null), "beats")?,
				random_every: (number(&every[0], "random_every")?, number(&every[1], "random_every")?),
				gestures,
				on_enter,
			});
		}
		if !moods.iter().any(|m| m.name == "neutral") {
			return Err("motion library needs a neutral mood".into());
		}
		Ok(Self { moods, clips })
	}
}

struct Playing {
	clip: usize,
	start: f32,
	weight: f32,
	/// Asked for by a command, rather than started by the mood.
	asked: bool,
	/// When it was cut short by another gesture; it then fades out.
	cut: Option<f32>,
}

const MOOD_TIME: f32 = 0.5;
const CUT_FADE: f32 = 0.25;
/// Quiet time after a gesture before another starts by itself.
const RANDOM_REST: f32 = 0.8;

pub struct Motion {
	lib: Library,
	available: Vec<bool>,
	mood: usize,
	intensity: f32,
	offsets: Vec<Spring>,
	energy: Spring,
	beats: Spring,
	playing: Vec<Playing>,
	last_end: f32,
	t: f32,
	random: bool,
	next_random: f32,
	rng: u64,
	/// False while the model's own expression shows the face: the mood then
	/// moves only posture and liveliness.
	face: bool,
	/// Gestures asked for while another asked-for one plays; they follow it.
	queued: Vec<(usize, f32)>,
}

/// Asked-for gestures waiting their turn, at most.
const QUEUE: usize = 2;

/// Controls that belong to the face, which a model's own expression replaces.
const FACE: [&str; 5] = ["smile", "eye_smile", "cheek", "brows", "brow_form"];

impl Motion {
	/// `has` says whether the character has a parameter for a control.
	pub fn new(lib: Library, has: impl Fn(&str) -> bool, seed: u64) -> Self {
		let available = lib.clips.iter().map(|c| c.needs.iter().all(|k| has(KEYS[*k]))).collect();
		let mood = lib.moods.iter().position(|m| m.name == "neutral").unwrap_or(0);
		let mut m = Self {
			lib,
			available,
			mood,
			intensity: 1.0,
			offsets: KEYS.iter().map(|_| Spring::new(0.0, MOOD_TIME)).collect(),
			energy: Spring::new(1.0, MOOD_TIME),
			beats: Spring::new(1.0, MOOD_TIME),
			playing: Vec::new(),
			last_end: 0.0,
			t: 0.0,
			random: true,
			next_random: 0.0,
			rng: seed.wrapping_mul(0x9E37_79B9_7F4A_7C15).max(1),
			face: true,
			queued: Vec::new(),
		};
		m.next_random = m.random_gap(1.0);
		m
	}

	pub fn emotions(&self) -> Vec<String> {
		let mut names: Vec<String> = self.lib.moods.iter().map(|m| m.name.clone()).collect();
		names.sort();
		names
	}

	/// Gestures this character can make.
	pub fn gestures(&self) -> Vec<String> {
		let mut names: Vec<String> =
			self.lib.clips.iter().zip(&self.available).filter(|(_, ok)| **ok).map(|(c, _)| c.name.clone()).collect();
		names.sort();
		names
	}

	pub fn mood(&self) -> &str {
		&self.lib.moods[self.mood].name
	}

	pub fn set_random(&mut self, on: bool) {
		self.random = on;
	}

	/// Whether the mood shows on the face (off while a model's own expression does).
	pub fn set_face(&mut self, on: bool) {
		self.face = on;
	}

	fn next_random_number(&mut self) -> f32 {
		self.rng ^= self.rng >> 12;
		self.rng ^= self.rng << 25;
		self.rng ^= self.rng >> 27;
		((self.rng.wrapping_mul(0x2545_F491_4F6C_DD1D) >> 40) as f32) / ((1u64 << 24) as f32)
	}

	fn random_gap(&mut self, scale: f32) -> f32 {
		let (lo, hi) = self.lib.moods[self.mood].random_every;
		self.t + scale * (lo + self.next_random_number() * (hi - lo))
	}

	/// Change mood; plays its entry gesture if it has one. Returns the gesture started, if any.
	pub fn set_emotion(&mut self, name: &str, intensity: f32) -> Result<Option<String>, String> {
		let i = self.lib.moods.iter().position(|m| m.name == name).ok_or(format!("unknown emotion '{name}'"))?;
		let changed = i != self.mood;
		self.mood = i;
		self.intensity = intensity.clamp(0.0, 1.0);
		self.next_random = self.random_gap(1.0);
		// A mood's entry gesture never cuts short one that was asked for.
		if changed && !self.playing.iter().any(|p| p.asked && p.cut.is_none()) {
			if let Some(g) = self.lib.moods[i].on_enter.clone() {
				if self.start(&g, self.intensity, false).is_ok() {
					return Ok(Some(g));
				}
			}
		}
		Ok(None)
	}

	/// Start a gesture now, as asked, cutting short any that is playing.
	pub fn play(&mut self, name: &str, intensity: f32) -> Result<(), String> {
		self.start(name, intensity, true)
	}

	fn start(&mut self, name: &str, intensity: f32, asked: bool) -> Result<(), String> {
		let i = self.lib.clips.iter().position(|c| c.name == name).ok_or(format!("unknown gesture '{name}'"))?;
		if !self.available[i] {
			return Err(format!("this character cannot make the gesture '{name}'"));
		}
		// One asked-for gesture after another: the next waits for the one playing.
		if asked && self.playing.iter().any(|p| p.asked && p.cut.is_none()) {
			if self.queued.len() < QUEUE {
				self.queued.push((i, intensity));
			}
			return Ok(());
		}
		self.begin(i, intensity, asked);
		Ok(())
	}

	fn begin(&mut self, i: usize, intensity: f32, asked: bool) {
		for p in &mut self.playing {
			p.cut.get_or_insert(self.t);
		}
		self.playing.push(Playing { clip: i, start: self.t, weight: intensity.clamp(0.0, 1.5), asked, cut: None });
	}

	/// How lively idle motion should be, and how strong the beats with speech.
	pub fn style(&self) -> (f32, f32) {
		(self.energy.value, self.beats.value)
	}

	/// Advance and add the mood and any gestures to `pose`. Returns a gesture
	/// that started now without a command, and why: "queued" (asked for earlier,
	/// waiting its turn) or "mood" (started by the mood).
	pub fn apply(&mut self, dt: f32, pose: &mut Pose, state: State, idle_motion: bool) -> Option<(String, &'static str)> {
		self.t += dt;
		let k = self.intensity;
		let mut target = [0.0f32; KEYS.len()];
		let (energy, beats, mood_gestures) = {
			let mood = &self.lib.moods[self.mood];
			for (key, v) in &mood.offsets {
				if self.face || !FACE.contains(&KEYS[*key]) {
					target[*key] = v * k;
				}
			}
			(1.0 + (mood.energy - 1.0) * k, 1.0 + (mood.beats - 1.0) * k, mood.gestures.clone())
		};
		self.energy.update(energy, dt);
		self.beats.update(beats, dt);

		let mut started = None;
		let was_playing = !self.playing.is_empty();
		self.playing.retain(|p| {
			let clip = &self.lib.clips[p.clip];
			let done = self.t - p.start >= clip.duration;
			let faded = p.cut.is_some_and(|c| self.t - c >= CUT_FADE);
			!(done || faded)
		});
		if was_playing && self.playing.is_empty() {
			self.last_end = self.t;
		}
		if !self.queued.is_empty() && !self.playing.iter().any(|p| p.asked && p.cut.is_none()) {
			let (i, intensity) = self.queued.remove(0);
			self.begin(i, intensity, true);
			started = Some((self.lib.clips[i].name.clone(), "queued"));
		}
		if self.random && idle_motion && self.playing.is_empty() && self.t - self.last_end > RANDOM_REST && self.t >= self.next_random {
			// Listening calls for small responses only; idling for fewer gestures.
			let (pool, scale): (Vec<(String, f32)>, f32) = match state {
				State::Listening => (vec![("nod".into(), 2.0), ("tilt".into(), 1.0)], 1.0),
				State::Idle => (mood_gestures.clone(), 1.5),
				_ => (mood_gestures, 1.0),
			};
			let pool: Vec<(String, f32)> = pool
				.into_iter()
				.filter(|(g, _)| self.lib.clips.iter().zip(&self.available).any(|(c, ok)| *ok && &c.name == g))
				.collect();
			let total: f32 = pool.iter().map(|(_, w)| w).sum();
			if total > 0.0 {
				let mut pick = self.next_random_number() * total;
				for (g, w) in &pool {
					if pick < *w {
						let strength = if state == State::Listening { 0.6 } else { k.max(0.5) };
						if self.start(g, strength, false).is_ok() {
							started = Some((g.clone(), "mood"));
						}
						break;
					}
					pick -= w;
				}
			}
			self.next_random = self.random_gap(scale);
		}

		let mut add = [0.0f32; KEYS.len()];
		for p in &self.playing {
			let fade = p.cut.map(|c| (1.0 - (self.t - c) / CUT_FADE).max(0.0)).unwrap_or(1.0);
			self.lib.clips[p.clip].sample(self.t - p.start, &mut add, p.weight * fade);
		}
		for key in 0..KEYS.len() {
			let mood_offset = self.offsets[key].update(target[key], dt);
			let v = slot(pose, key);
			*v += mood_offset + add[key];
			*v = if one_sided(key) { v.clamp(0.0, 1.0) } else { v.clamp(-1.0, 1.0) };
		}
		started
	}
}

#[cfg(test)]
mod tests {
	use super::*;

	const DT: f32 = 1.0 / 60.0;

	fn all(_: &str) -> bool {
		true
	}

	fn run(m: &mut Motion, seconds: f32, state: State) -> (Vec<Pose>, Vec<String>) {
		let mut poses = Vec::new();
		let mut started = Vec::new();
		for _ in 0..(seconds / DT) as usize {
			let mut p = Pose::default();
			if let Some((g, _)) = m.apply(DT, &mut p, state, true) {
				started.push(g);
			}
			poses.push(p);
		}
		(poses, started)
	}

	#[test]
	fn the_built_in_library_is_complete() {
		let lib = Library::builtin();
		for emotion in ["neutral", "happy", "sad", "angry", "surprised", "embarrassed", "thinking"] {
			assert!(lib.moods.iter().any(|m| m.name == emotion), "{emotion}");
		}
		for gesture in ["nod", "shake", "bow", "tilt", "wave", "hands_on_hips", "sway", "laugh", "shrug"] {
			assert!(lib.clips.iter().any(|c| c.name == gesture), "{gesture}");
		}
	}

	#[test]
	fn bad_libraries_are_refused() {
		for bad in [
			r#"{"moods": {}, "gestures": {}}"#,
			r#"{"moods": {"neutral": {"offsets": {"tail": 1}, "energy": 1, "beats": 1, "random_every": [1, 2], "gestures": {}}}, "gestures": {}}"#,
			r#"{"moods": {"neutral": {"offsets": {}, "energy": 1, "beats": 1, "random_every": [1, 2], "gestures": {"fly": 1}}}, "gestures": {}}"#,
			r#"{"moods": {"neutral": {"offsets": {}, "energy": 1, "beats": 1, "random_every": [1, 2], "gestures": {}}}, "gestures": {"g": {"needs": [], "tracks": {"head_yaw": [[0, 0], [1, 0.5]]}}}}"#,
		] {
			assert!(Library::parse(bad).is_err(), "{bad}");
		}
	}

	#[test]
	fn a_gesture_adds_to_the_pose_and_returns_to_it() {
		let mut m = Motion::new(Library::builtin(), all, 1);
		m.set_random(false);
		m.play("nod", 1.0).unwrap();
		let (poses, _) = run(&mut m, 1.2, State::Speaking);
		let lowest = poses.iter().map(|p| p.head_pitch).fold(f32::MAX, f32::min);
		assert!(lowest < -0.3, "the head dips: {lowest}");
		assert!(poses.last().unwrap().head_pitch.abs() < 1e-4, "and returns");
		assert!(poses.windows(2).all(|w| (w[1].head_pitch - w[0].head_pitch).abs() < 0.08), "smoothly");
	}

	#[test]
	fn a_mood_changes_the_face_and_the_liveliness_gradually() {
		let mut m = Motion::new(Library::builtin(), all, 1);
		m.set_random(false);
		assert_eq!(m.set_emotion("happy", 1.0).unwrap(), Some("bounce".to_string()));
		let (poses, _) = run(&mut m, 0.1, State::Idle);
		assert!(poses[0].smile < 0.1, "not at once");
		let (poses, _) = run(&mut m, 2.0, State::Idle);
		assert!((poses.last().unwrap().smile - 0.8).abs() < 0.02);
		let (energy, beats) = m.style();
		assert!(energy > 1.25 && beats > 1.25);
		m.set_emotion("sad", 0.5).unwrap();
		run(&mut m, 2.0, State::Idle);
		assert!(m.style().0 < 0.8, "half-strength sadness: {}", m.style().0);
		assert!(m.set_emotion("bored", 1.0).is_err());
	}

	#[test]
	fn an_asked_for_gesture_is_not_cut_short_by_a_moods_entry_gesture() {
		let mut m = Motion::new(Library::builtin(), all, 1);
		m.set_random(false);
		m.play("wave", 1.0).unwrap();
		assert_eq!(m.set_emotion("happy", 1.0).unwrap(), None);
		let (poses, _) = run(&mut m, 1.0, State::Speaking);
		assert!(poses.iter().any(|p| p.arm_right > 0.3), "the wave plays out");
	}

	#[test]
	fn gestures_asked_for_one_after_another_play_in_turn() {
		let mut m = Motion::new(Library::builtin(), all, 1);
		m.set_random(false);
		m.play("nod", 1.0).unwrap();
		m.play("tilt", 1.0).unwrap();
		let (poses, started) = run(&mut m, 3.0, State::Speaking);
		assert_eq!(started, vec!["tilt".to_string()], "the tilt starts when the nod is done");
		let nod_end = (0.75 / DT) as usize;
		assert!(poses[..nod_end - 2].iter().all(|p| p.head_roll.abs() < 1e-4), "no tilt during the nod");
		assert!(poses.iter().any(|p| p.head_roll > 0.4), "then the whole tilt");
	}

	#[test]
	fn gestures_need_the_controls_they_move() {
		let only_head = |k: &str| k.starts_with("head") || k.starts_with("body");
		let mut m = Motion::new(Library::builtin(), only_head, 1);
		assert!(m.gestures().contains(&"nod".to_string()));
		assert!(!m.gestures().contains(&"wave".to_string()));
		assert!(m.play("wave", 1.0).is_err());
	}

	#[test]
	fn the_mood_brings_its_own_gestures_by_itself() {
		let mut m = Motion::new(Library::builtin(), all, 3);
		m.set_emotion("happy", 1.0).unwrap();
		let (_, started) = run(&mut m, 60.0, State::Speaking);
		assert!(started.len() >= 5, "{started:?}");
		let happy = ["bounce", "tilt", "nod", "sway", "laugh", "hands_on_hips", "wave"];
		assert!(started.iter().all(|g| happy.contains(&g.as_str())), "{started:?}");
		// While listening, only small responses.
		let mut l = Motion::new(Library::builtin(), all, 3);
		let (_, heard) = run(&mut l, 60.0, State::Listening);
		assert!(!heard.is_empty() && heard.iter().all(|g| g == "nod" || g == "tilt"), "{heard:?}");
		// Switched off, none.
		let mut off = Motion::new(Library::builtin(), all, 3);
		off.set_random(false);
		assert!(run(&mut off, 60.0, State::Speaking).1.is_empty());
	}

	#[test]
	fn a_new_gesture_cuts_the_old_one_short_without_a_jump() {
		let mut m = Motion::new(Library::builtin(), all, 1);
		m.set_random(false);
		m.play("tilt", 1.0).unwrap();
		let (before, _) = run(&mut m, 0.5, State::Speaking);
		m.play("nod", 1.0).unwrap();
		let (after, _) = run(&mut m, 0.5, State::Speaking);
		let jump = (after[0].head_roll - before.last().unwrap().head_roll).abs();
		assert!(jump < 0.08, "{jump}");
	}
}
