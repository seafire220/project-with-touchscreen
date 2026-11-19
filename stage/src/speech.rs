//! A sentence's performance: the mouth's shape for each syllable, and movements started on given
//! syllables, so they land on their words.
//!
//! As a sentence's sound starts, the core sends
//! `{"perform": {"syllables": "eaoeo", "events": [[0, "nod", 0.7]]}}`: the vowel of each syllable
//! (a, e, i, o or u) and the movements that start on a syllable (one or two before their word). Then,
//! as each syllable is heard, it sends `{"syllable": k}`. Each mark sets the mouth's shape and starts
//! the movements due by then. The voice's loudness still sets how far the mouth opens; the shape scales
//! that (an "i" opens less than an "a") and widens or rounds the mouth through the mouth-shape control.
//!
//! Nothing here is needed for talking: without a performance, or if the marks stop, the mouth simply
//! follows the loudness and the beats still come from the voice's stresses.

use crate::behaviour::Pose;

/// How long a syllable's shape holds without a new mark before the mouth relaxes to plain opening.
const SHAPE_HOLD: f32 = 0.6;
/// How quickly the mouth moves between shapes, in seconds.
const SHAPE_TIME: f32 = 0.06;
/// How much a shape widens or rounds the mouth, on the mouth-shape control.
const FORM_WEIGHT: f32 = 0.6;

#[derive(Clone, Debug, PartialEq)]
pub struct Performance {
	pub syllables: Vec<u8>,
	/// (syllable, movement, strength), in order of syllable.
	pub events: Vec<(usize, String, f32)>,
}

/// How far the mouth opens for a vowel (a share of the loudness's opening), and how wide (+) or
/// round (-) it is.
fn shape(vowel: u8) -> (f32, f32) {
	match vowel {
		b'a' => (1.0, 0.0),
		b'e' => (0.8, 0.3),
		b'i' => (0.6, 0.55),
		b'o' => (0.85, -0.35),
		b'u' => (0.55, -0.6),
		_ => (1.0, 0.0),
	}
}

pub struct Speech {
	perf: Option<Performance>,
	fired: usize,
	current: Option<u8>,
	since_mark: f32,
	open: f32,
	form: f32,
	/// How much the mouth is shaped for each vowel (a, i, u, e, o), eased between syllables.
	vowels: [f32; 5],
}

const VOWELS: &[u8; 5] = b"aiueo";

impl Default for Speech {
	fn default() -> Self {
		Self::new()
	}
}

impl Speech {
	pub fn new() -> Self {
		Self { perf: None, fired: 0, current: None, since_mark: 0.0, open: 1.0, form: 0.0, vowels: [0.0; 5] }
	}

	/// A new sentence starts.
	pub fn start(&mut self, mut perf: Performance) {
		perf.events.sort_by(|a, b| a.0.cmp(&b.0));
		self.perf = Some(perf);
		self.fired = 0;
		self.current = None;
		self.since_mark = 0.0;
	}

	/// Speaking ended or was cut short.
	pub fn stop(&mut self) {
		self.perf = None;
		self.current = None;
	}

	/// Syllable `k` is being heard: its shape, and the movements due by now (name, strength).
	pub fn syllable(&mut self, k: usize) -> Vec<(String, f32)> {
		let Some(perf) = &self.perf else {
			return Vec::new();
		};
		self.current = perf.syllables.get(k).copied().or(perf.syllables.last().copied());
		self.since_mark = 0.0;
		let mut due = Vec::new();
		while self.fired < perf.events.len() && perf.events[self.fired].0 <= k {
			let (_, name, strength) = &perf.events[self.fired];
			due.push((name.clone(), *strength));
			self.fired += 1;
		}
		due
	}

	/// Shape the mouth of this frame's pose.
	pub fn apply(&mut self, dt: f32, speaking: bool, pose: &mut Pose) {
		self.since_mark += dt;
		if !speaking || self.since_mark > SHAPE_HOLD {
			self.current = None;
		}
		let (open, form) = self.current.map(shape).unwrap_or((1.0, 0.0));
		let k = 1.0 - (-dt / SHAPE_TIME).exp();
		self.open += (open - self.open) * k;
		self.form += (form - self.form) * k;
		pose.mouth_open *= self.open;
		// The shape shows while the mouth is open; a closed mouth keeps the mood's smile.
		let showing = (pose.mouth_open * 2.5).min(1.0);
		pose.smile = (pose.smile + FORM_WEIGHT * self.form * showing).clamp(-1.0, 1.0);
		// Characters with a parameter for each vowel: the one being said, as far as the mouth is open.
		for (i, v) in VOWELS.iter().enumerate() {
			let target = if self.current == Some(*v) { 1.0 } else { 0.0 };
			self.vowels[i] += (target - self.vowels[i]) * k;
		}
		let open = (pose.mouth_open * 1.4).min(1.0);
		pose.vowel_a = self.vowels[0] * open;
		pose.vowel_i = self.vowels[1] * open;
		pose.vowel_u = self.vowels[2] * open;
		pose.vowel_e = self.vowels[3] * open;
		pose.vowel_o = self.vowels[4] * open;
	}
}

#[cfg(test)]
mod tests {
	use super::*;

	fn perf() -> Performance {
		Performance {
			syllables: b"aiu".to_vec(),
			events: vec![(2, "tilt".into(), 0.6), (0, "nod".into(), 0.7)],
		}
	}

	fn settle(s: &mut Speech, speaking: bool, open: f32) -> Pose {
		let mut pose = Pose::default();
		for _ in 0..30 {
			pose = Pose { mouth_open: open, smile: 0.1, ..Default::default() };
			s.apply(1.0 / 60.0, speaking, &mut pose);
		}
		pose
	}

	#[test]
	fn movements_start_on_their_syllable_once() {
		let mut s = Speech::new();
		s.start(perf());
		assert_eq!(s.syllable(0), vec![("nod".to_string(), 0.7)]);
		assert!(s.syllable(1).is_empty());
		assert_eq!(s.syllable(2), vec![("tilt".to_string(), 0.6)]);
		assert!(s.syllable(2).is_empty(), "never twice");
		s.start(perf());
		assert_eq!(s.syllable(5).len(), 2, "a mark that skips ahead starts everything due");
	}

	#[test]
	fn each_vowel_shapes_the_open_mouth() {
		let mut s = Speech::new();
		s.start(perf());
		s.syllable(0);
		let a = settle(&mut s, true, 0.8);
		s.syllable(1);
		let i = settle(&mut s, true, 0.8);
		s.syllable(2);
		let u = settle(&mut s, true, 0.8);
		assert!(a.mouth_open > i.mouth_open && i.mouth_open > u.mouth_open, "{} {} {}", a.mouth_open, i.mouth_open, u.mouth_open);
		assert!(i.smile > a.smile && u.smile < a.smile, "an i widens, a u rounds");
		let shut = settle(&mut s, true, 0.0);
		assert!((shut.smile - 0.1).abs() < 0.02, "a closed mouth keeps the mood's smile");
		// Per-vowel parameters: the vowel being said, as open as the mouth.
		s.syllable(1);
		let i = settle(&mut s, true, 0.5);
		assert!(i.vowel_i > 0.4 && i.vowel_a < 0.02 && i.vowel_u < 0.02, "{i:?}");
		assert!(settle(&mut s, true, 0.0).vowel_i < 0.01, "shut between syllables");
	}

	#[test]
	fn without_marks_the_mouth_just_follows_the_loudness() {
		let mut s = Speech::new();
		let plain = settle(&mut s, true, 0.7);
		assert!((plain.mouth_open - 0.7).abs() < 1e-3 && (plain.smile - 0.1).abs() < 1e-3);
		s.start(perf());
		s.syllable(2);
		let mut pose = Pose { mouth_open: 0.7, ..Default::default() };
		for _ in 0..60 {
			pose = Pose { mouth_open: 0.7, ..Default::default() };
			s.apply(1.0 / 60.0, true, &mut pose);
		}
		assert!((pose.mouth_open - 0.7).abs() < 0.01, "a shape relaxes when the marks stop");
		s.stop();
		assert!(s.syllable(0).is_empty());
	}
}
