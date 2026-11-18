//! Moods and gestures on the generic controls (docs/24-motion.md).
//!
//! An emotion is a **mood**: it changes how the character moves (how lively,
//! how strong its beats with speech), its resting posture and face, and
//! which gestures it makes by itself. A **gesture** is a short clip added on
//! top of whatever the character is doing, so it blends into speaking and
//! idling instead of replacing them. Both are written once, in control units,
//! in `stage/motions/library.json`, and reach each character through its
//! calibration; a gesture is offered only to characters that have every
//! control it needs. A need may name alternatives ("arm_left_b|arm_right_b":
//! either elbow will do), so a character with one moving arm still puts a
//! hand on its hip; tracks for controls it lacks are left out.
//!
//! **Channels.** The body is split into channels (head, torso, eyes, brows, expression, left arm, right
//! arm). A gesture holds the channels it moves strongly, so others can play at the same time on the
//! rest: a nod plays through a wave. A gesture that matters more (one asked for, over one the words
//! call for, over one the mood starts by itself) takes a held channel over; the other lets go of it
//! with a short fade and carries on with the rest. While a gesture holds a channel, the living motion
//! there (drifting, beats) mostly gives way to it.
//!
//! **Budget.** The gestures the character starts by itself are kept to a few a minute, big ones (a wave,
//! a bow) to two, and the mood picks gestures it has not made lately, so it never flails or repeats
//! itself. A gesture asked for always plays, if the character can make it.

use std::collections::VecDeque;

use serde_json::Value;

use crate::behaviour::{Pose, State};
use crate::smooth::Spring;

/// The controls moods and gestures may move, in `Pose` field names.
pub const KEYS: [&str; 18] = [
	"head_yaw", "head_pitch", "head_roll", "body_yaw", "body_pitch", "body_roll", "gaze_x", "gaze_y", "brows",
	"brow_form", "smile", "eye_smile", "cheek", "arm_left", "arm_right", "arm_left_b", "arm_right_b", "shoulders",
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
		"arm_left_b" => &mut pose.arm_left_b,
		"arm_right_b" => &mut pose.arm_right_b,
		_ => &mut pose.shoulders,
	}
}

/// Parts of the body a gesture can occupy.
pub const CHANNELS: [&str; 7] = ["head", "torso", "eyes", "brows", "expression", "arm_left", "arm_right"];

/// The channel a control belongs to.
fn channel_of(key: usize) -> usize {
	match KEYS[key] {
		"head_yaw" | "head_pitch" | "head_roll" => 0,
		"body_yaw" | "body_pitch" | "body_roll" | "shoulders" => 1,
		"gaze_x" | "gaze_y" => 2,
		"brows" | "brow_form" => 3,
		"smile" | "eye_smile" | "cheek" => 4,
		"arm_left" | "arm_left_b" => 5,
		_ => 6,
	}
}

/// A gesture holds a channel where it moves a control at least this far; smaller moves only colour a
/// channel, and give way to a gesture that holds it.
const HOLD_LEVEL: f32 = 0.25;
/// How much of the living motion (drifting, breathing, beats) gives way on a channel a gesture holds.
const GIVE_WAY: f32 = 0.7;

/// Who started a gesture, by precedence: one asked for (by the language model or the settings page)
/// over one the words call for or a new mood brings, over one the mood starts by itself.
pub const ASKED: u8 = 3;
pub const SPEECH: u8 = 2;
const MOOD: u8 = 1;

/// The budget for the gestures the character starts by itself (not asked for), per minute: all of
/// them; big ones; and those the mood starts with nothing said to prompt them.
const MINUTE: f32 = 60.0;
const OWN_PER_MINUTE: usize = 10;
const BIG_PER_MINUTE: usize = 2;
const MOOD_PER_MINUTE: usize = 6;
/// A gesture the mood picks is less likely again until this many seconds have passed (big ones longer),
/// and the one it picked last is much less likely next.
const FRESH_SMALL: f32 = 20.0;
const FRESH_BIG: f32 = 60.0;
const AGAIN: f32 = 0.3;

/// What became of a gesture that was asked for or suggested.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Start {
	Now,
	/// Waiting for an asked-for gesture using the same part of the body.
	Queued,
	/// Not played, and why.
	Skipped(&'static str),
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
	/// Each need is met by any one of its controls.
	pub needs: Vec<Vec<usize>>,
	tracks: Vec<(usize, Vec<(f32, f32)>)>,
	pub duration: f32,
	/// Channels it holds while it plays, and all it moves (one bit per channel).
	pub holds: u8,
	pub touches: u8,
	/// A big movement (a wave, a bow): rarer, and at most a couple a minute unless asked for.
	pub big: bool,
}

impl Clip {
	/// The clip's offsets `t` seconds in, each channel by its own weight; keys are joined by smooth steps.
	fn sample(&self, t: f32, out: &mut [f32; KEYS.len()], weights: &[f32; CHANNELS.len()]) {
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
			out[*key] += value * weights[channel_of(*key)];
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
				.map(|k| k.as_str().unwrap_or("").split('|').map(key_index).collect::<Result<Vec<_>, _>>())
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
			// The channels it holds: as listed, or those it moves far.
			let mut peak = [0.0f32; CHANNELS.len()];
			for (key, pts) in &tracks {
				let c = channel_of(*key);
				peak[c] = pts.iter().fold(peak[c], |m, p| m.max(p.1.abs()));
			}
			let touches = (0..CHANNELS.len()).filter(|c| peak[*c] > 0.0).fold(0u8, |m, c| m | 1 << c);
			let holds = match g.get("holds").and_then(Value::as_array) {
				Some(list) => {
					let mut m = 0u8;
					for c in list {
						let c = c.as_str().and_then(|n| CHANNELS.iter().position(|x| *x == n));
						m |= 1 << c.ok_or(format!("gesture {name}: 'holds' names channels: {}", CHANNELS.join(", ")))?;
					}
					m
				}
				None => {
					let strong = (0..CHANNELS.len()).filter(|c| peak[*c] >= HOLD_LEVEL).fold(0u8, |m, c| m | 1 << c);
					// At least the channel it moves most.
					let most = (0..CHANNELS.len()).max_by(|a, b| peak[*a].total_cmp(&peak[*b])).unwrap_or(0);
					if strong == 0 && peak[most] > 0.0 { 1 << most } else { strong }
				}
			};
			let big = g.get("big").and_then(Value::as_bool).unwrap_or(false);
			clips.push(Clip { name: name.clone(), needs, tracks, duration, holds, touches, big });
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
	/// Who started it: ASKED, SPEECH or MOOD.
	priority: u8,
	/// When it was cut short by another gesture; it then fades out.
	cut: Option<f32>,
	/// When it let go of each channel to a gesture that took it over; it fades out there.
	released: [Option<f32>; CHANNELS.len()],
}

/// How much is left of something fading out since `since`.
fn fade(since: Option<f32>, t: f32) -> f32 {
	since.map(|c| (1.0 - (t - c) / CUT_FADE).max(0.0)).unwrap_or(1.0)
}

impl Playing {
	/// The channels it still holds.
	fn holding(&self, clip: &Clip) -> u8 {
		if self.cut.is_some() {
			return 0;
		}
		(0..CHANNELS.len()).filter(|c| self.released[*c].is_some()).fold(clip.holds, |m, c| m & !(1 << c))
	}
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
	/// Gestures asked for while another asked-for one used the same channels; they follow it.
	queued: Vec<(usize, f32)>,
	/// How far each channel is held by gestures now (eased, so the living motion never jumps).
	busy: [f32; CHANNELS.len()],
	/// Gestures started in the last minute: (when, who started it, big), for the budget.
	recent: VecDeque<(f32, u8, bool)>,
	/// When each gesture last started, and the mood's last pick, for its choice of fresh ones.
	last_start: Vec<f32>,
	last_pick: Option<usize>,
}

/// Asked-for gestures waiting their turn, at most.
const QUEUE: usize = 2;

/// Controls that belong to the face, which a model's own expression replaces.
const FACE: [&str; 5] = ["smile", "eye_smile", "cheek", "brows", "brow_form"];

impl Motion {
	/// `has` says whether the character has a parameter for a control.
	pub fn new(lib: Library, has: impl Fn(&str) -> bool, seed: u64) -> Self {
		let available =
			lib.clips.iter().map(|c| c.needs.iter().all(|any| any.iter().any(|k| has(KEYS[*k])))).collect();
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
			busy: [0.0; CHANNELS.len()],
			recent: VecDeque::new(),
			last_start: Vec::new(),
			last_pick: None,
		};
		m.last_start = vec![f32::NEG_INFINITY; m.lib.clips.len()];
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

	/// Change mood; plays its entry gesture if it has one (and the body is free for it). Returns the
	/// gesture started, if any.
	pub fn set_emotion(&mut self, name: &str, intensity: f32) -> Result<Option<String>, String> {
		let i = self.lib.moods.iter().position(|m| m.name == name).ok_or(format!("unknown emotion '{name}'"))?;
		let changed = i != self.mood;
		self.mood = i;
		self.intensity = intensity.clamp(0.0, 1.0);
		self.next_random = self.random_gap(1.0);
		if changed {
			if let Some(g) = self.lib.moods[i].on_enter.clone() {
				if let Some(c) = self.lib.clips.iter().position(|c| c.name == g).filter(|c| self.available[*c]) {
					if self.begin(c, self.intensity, SPEECH) == Start::Now {
						return Ok(Some(g));
					}
				}
			}
		}
		Ok(None)
	}

	fn find(&self, name: &str) -> Result<usize, String> {
		self.lib.clips.iter().position(|c| c.name == name).ok_or(format!("unknown gesture '{name}'"))
	}

	/// Play a gesture, as asked. It starts now, taking over the parts of the body it needs, unless
	/// another asked-for gesture is using them: then it waits for that one.
	pub fn play(&mut self, name: &str, intensity: f32) -> Result<Start, String> {
		let i = self.find(name)?;
		if !self.available[i] {
			return Err(format!("this character cannot make the gesture '{name}'"));
		}
		Ok(self.begin(i, intensity, ASKED))
	}

	/// A gesture the speech suggests (a nod on "yes"). It plays if the character can make it, nothing
	/// asked for is using the parts of the body it needs, and the budget allows.
	pub fn suggest(&mut self, name: &str, intensity: f32) -> Result<Start, String> {
		let i = self.find(name)?;
		if !self.available[i] {
			return Ok(Start::Skipped("this character cannot make it"));
		}
		Ok(self.begin(i, intensity, SPEECH))
	}

	/// The budget, for gestures the character starts by itself.
	fn within_budget(&self, clip: usize, priority: u8) -> Result<(), &'static str> {
		if priority >= ASKED {
			return Ok(());
		}
		let (mut own, mut big, mut mood) = (0, 0, 0);
		for &(at, p, b) in &self.recent {
			if self.t - at < MINUTE && p < ASKED {
				own += 1;
				big += b as usize;
				mood += (p == MOOD) as usize;
			}
		}
		if own >= OWN_PER_MINUTE {
			return Err("enough gestures this minute");
		}
		if self.lib.clips[clip].big && big >= BIG_PER_MINUTE {
			return Err("enough big gestures this minute");
		}
		if priority == MOOD && mood >= MOOD_PER_MINUTE {
			return Err("enough of the mood's own gestures this minute");
		}
		Ok(())
	}

	fn begin(&mut self, i: usize, intensity: f32, priority: u8) -> Start {
		if let Err(why) = self.within_budget(i, priority) {
			return Start::Skipped(why);
		}
		let holds = self.lib.clips[i].holds;
		let conflicts: Vec<usize> = (0..self.playing.len())
			.filter(|j| self.playing[*j].holding(&self.lib.clips[self.playing[*j].clip]) & holds != 0)
			.collect();
		if conflicts.iter().any(|j| self.playing[*j].priority > priority) {
			return Start::Skipped("a gesture that matters more is using that part of the body");
		}
		// One asked-for gesture after another on the same part of the body: the next waits its turn.
		if priority == ASKED && conflicts.iter().any(|j| self.playing[*j].priority == ASKED) {
			if self.queued.len() < QUEUE {
				self.queued.push((i, intensity));
				return Start::Queued;
			}
			return Start::Skipped("two asked-for gestures are already waiting");
		}
		// The others let go of the channels it holds, and fade out there; one left holding nothing ends.
		let t = self.t;
		for p in &mut self.playing {
			let clip = &self.lib.clips[p.clip];
			for c in 0..CHANNELS.len() {
				if holds & (clip.holds | clip.touches) & (1 << c) != 0 {
					p.released[c].get_or_insert(t);
				}
			}
			if p.cut.is_none() && p.holding(clip) == 0 {
				p.cut = Some(t);
			}
		}
		// And it leaves alone the channels the others still hold.
		let others = self.playing.iter().fold(0u8, |m, p| m | p.holding(&self.lib.clips[p.clip]));
		let mut released = [None; CHANNELS.len()];
		for (c, r) in released.iter_mut().enumerate() {
			if others & self.lib.clips[i].touches & (1 << c) != 0 {
				*r = Some(t - CUT_FADE);
			}
		}
		self.playing.push(Playing { clip: i, start: t, weight: intensity.clamp(0.0, 1.5), priority, cut: None, released });
		self.recent.push_back((t, priority, self.lib.clips[i].big));
		self.last_start[i] = t;
		Start::Now
	}

	/// The gestures playing now (not cut short).
	pub fn playing(&self) -> Vec<String> {
		self.playing.iter().filter(|p| p.cut.is_none()).map(|p| self.lib.clips[p.clip].name.clone()).collect()
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
		while self.recent.front().is_some_and(|r| self.t - r.0 >= MINUTE) {
			self.recent.pop_front();
		}
		// An asked-for gesture waiting its turn starts once no other asked-for one uses its channels.
		if let Some(&(i, intensity)) = self.queued.first() {
			let holds = self.lib.clips[i].holds;
			let blocked = self
				.playing
				.iter()
				.any(|p| p.priority == ASKED && p.holding(&self.lib.clips[p.clip]) & holds != 0);
			if !blocked {
				self.queued.remove(0);
				if self.begin(i, intensity, ASKED) == Start::Now {
					started = Some((self.lib.clips[i].name.clone(), "queued"));
				}
			}
		}
		if self.random && idle_motion && self.playing.is_empty() && self.t - self.last_end > RANDOM_REST && self.t >= self.next_random {
			// Listening calls for small responses only; idling for fewer gestures.
			let (pool, scale): (Vec<(String, f32)>, f32) = match state {
				State::Listening => (vec![("nod".into(), 2.0), ("tilt".into(), 1.0)], 1.0),
				State::Idle => (mood_gestures.clone(), 1.5),
				_ => (mood_gestures, 1.0),
			};
			// Gestures it can make, less likely if made lately.
			let pool: Vec<(usize, f32)> = pool
				.into_iter()
				.filter_map(|(g, w)| {
					let i = self.lib.clips.iter().position(|c| c.name == g).filter(|i| self.available[*i])?;
					let wait = if self.lib.clips[i].big { FRESH_BIG } else { FRESH_SMALL };
					let again = if self.last_pick == Some(i) { AGAIN } else { 1.0 };
					Some((i, w * again * ((self.t - self.last_start[i]) / wait).clamp(0.0, 1.0)))
				})
				.filter(|(_, w)| *w > 0.0)
				.collect();
			let total: f32 = pool.iter().map(|(_, w)| w).sum();
			if total > 0.0 {
				let mut pick = self.next_random_number() * total;
				for &(i, w) in &pool {
					if pick < w {
						let strength = if state == State::Listening { 0.6 } else { k.max(0.5) };
						if self.begin(i, strength, MOOD) == Start::Now {
							started = Some((self.lib.clips[i].name.clone(), "mood"));
							self.last_pick = Some(i);
						}
						break;
					}
					pick -= w;
				}
			}
			self.next_random = self.random_gap(scale);
		}

		// Each gesture adds its offsets, faded where it was cut short or let a channel go; the channels
		// gestures hold are busy, and the living motion there gives way, eased in and out.
		let mut add = [0.0f32; KEYS.len()];
		let mut held = [0.0f32; CHANNELS.len()];
		for p in &self.playing {
			let clip = &self.lib.clips[p.clip];
			let whole = p.weight * fade(p.cut, self.t);
			let mut weights = [0.0f32; CHANNELS.len()];
			for (c, w) in weights.iter_mut().enumerate() {
				*w = whole * fade(p.released[c], self.t);
				if clip.holds & (1 << c) != 0 {
					held[c] = held[c].max(w.min(1.0));
				}
			}
			clip.sample(self.t - p.start, &mut add, &weights);
		}
		let step = dt / CUT_FADE;
		for (busy, target) in self.busy.iter_mut().zip(held) {
			*busy += (target - *busy).clamp(-step, step);
		}
		for key in 0..KEYS.len() {
			*slot(pose, key) *= 1.0 - GIVE_WAY * self.busy[channel_of(key)];
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

	/// The same run with one change made after `at` seconds.
	fn compare(first: &[(&str, u8)], at: f32, then: &[(&str, u8)], seconds: f32) -> (Vec<Pose>, Vec<Pose>) {
		let mut a = Motion::new(Library::builtin(), all, 1);
		let mut b = Motion::new(Library::builtin(), all, 1);
		for m in [&mut a, &mut b] {
			m.set_random(false);
			for (g, p) in first {
				m.begin(m.find(g).unwrap(), 1.0, *p);
			}
		}
		let (mut alone, _) = run(&mut a, at, State::Speaking);
		let (mut both, _) = run(&mut b, at, State::Speaking);
		for (g, p) in then {
			assert_eq!(b.begin(b.find(g).unwrap(), 1.0, *p), Start::Now, "{g}");
		}
		alone.extend(run(&mut a, seconds - at, State::Speaking).0);
		both.extend(run(&mut b, seconds - at, State::Speaking).0);
		(alone, both)
	}

	#[test]
	fn an_asked_for_gesture_is_not_disturbed_by_a_moods_entry_gesture() {
		let mut m = Motion::new(Library::builtin(), all, 1);
		m.set_random(false);
		m.play("wave", 1.0).unwrap();
		assert_eq!(m.set_emotion("happy", 1.0).unwrap(), Some("bounce".into()), "it bounces on the torso, free");
		let (poses, _) = run(&mut m, 1.0, State::Speaking);
		let mut w = Motion::new(Library::builtin(), all, 1);
		w.set_random(false);
		w.play("wave", 1.0).unwrap();
		let (alone, _) = run(&mut w, 1.0, State::Speaking);
		for (p, q) in poses.iter().zip(&alone) {
			assert!((p.arm_right - q.arm_right).abs() < 1e-5 && (p.arm_right_b - q.arm_right_b).abs() < 1e-5);
		}
		let mut m = Motion::new(Library::builtin(), all, 1);
		m.set_random(false);
		m.play("think", 1.0).unwrap();
		assert_eq!(m.set_emotion("surprised", 1.0).unwrap(), None, "a start in surprise would take the head from it");
	}

	#[test]
	fn a_nod_plays_through_a_wave() {
		let (alone, both) = compare(&[("wave", ASKED)], 0.3, &[("nod", SPEECH)], 1.6);
		for (p, q) in both.iter().zip(&alone) {
			assert!((p.arm_right - q.arm_right).abs() < 1e-5 && (p.arm_right_b - q.arm_right_b).abs() < 1e-5,
				"the arm waves on as if alone");
		}
		let dip = both.iter().map(|p| p.head_pitch).fold(f32::MAX, f32::min);
		assert!(dip < -0.3, "while the head nods: {dip}");
	}

	#[test]
	fn a_gesture_that_matters_more_takes_a_channel_and_the_other_keeps_the_rest() {
		// Thinking (a new mood's gesture) looks up and away; a tilt asked for takes the head from it.
		let (alone, both) = compare(&[("think", SPEECH)], 0.5, &[("tilt", ASKED)], 1.6);
		let at = (0.5 / DT) as usize;
		for (p, q) in both[at..].iter().zip(&alone[at..]) {
			assert!((p.gaze_x - q.gaze_x).abs() < 1e-5 && (p.gaze_y - q.gaze_y).abs() < 1e-5, "the eyes think on");
		}
		let later = at + (0.6 / DT) as usize;
		let mut tilt = Motion::new(Library::builtin(), all, 1);
		tilt.set_random(false);
		tilt.play("tilt", 1.0).unwrap();
		let (only, _) = run(&mut tilt, 1.1, State::Speaking);
		assert!((both[later].head_roll - only[(0.6 / DT) as usize].head_roll).abs() < 0.02, "the head tilts as asked");
	}

	#[test]
	fn a_suggested_gesture_never_takes_from_an_asked_one() {
		let mut m = Motion::new(Library::builtin(), all, 1);
		m.set_random(false);
		assert_eq!(m.play("wave", 1.0).unwrap(), Start::Now);
		assert!(matches!(m.suggest("hands_on_hips", 1.0).unwrap(), Start::Skipped(_)), "the right arm is waving");
		assert_eq!(m.suggest("nod", 1.0).unwrap(), Start::Now, "the head is free");
		assert_eq!(m.play("shake", 1.0).unwrap(), Start::Now, "asked: it takes the head from the nod");
		assert_eq!(m.playing(), vec!["wave".to_string(), "shake".to_string()]);
		assert!(matches!(m.suggest("brow_flash", 1.0).unwrap(), Start::Now), "the brows are free");
		assert_eq!(m.suggest("flap", 1.0).unwrap_err(), "unknown gesture 'flap'");
	}

	#[test]
	fn the_living_motion_gives_way_where_a_gesture_holds() {
		let mut m = Motion::new(Library::builtin(), all, 1);
		m.set_random(false);
		let mut out = Vec::new();
		m.play("wave", 1.0).unwrap();
		for _ in 0..(3.0 / DT) as usize {
			let mut p = Pose { arm_right: 0.05, arm_left: 0.05, ..Default::default() };
			m.apply(DT, &mut p, State::Speaking, true);
			out.push(p);
		}
		let mut w = Motion::new(Library::builtin(), all, 1);
		w.set_random(false);
		w.play("wave", 1.0).unwrap();
		let (bare, _) = run(&mut w, 3.0, State::Speaking);
		let mid = (1.0 / DT) as usize;
		let extra = out[mid].arm_right - bare[mid].arm_right;
		assert!((extra - 0.05 * (1.0 - GIVE_WAY)).abs() < 1e-3, "the living arm motion mostly gives way: {extra}");
		assert!((out[mid].arm_left - 0.05).abs() < 1e-5, "but not on the other arm");
		assert!((out.last().unwrap().arm_right - 0.05).abs() < 1e-5, "and comes back after");
		assert!(out.windows(2).all(|w| (w[1].arm_right - w[0].arm_right).abs() < 0.1), "smoothly");
	}

	#[test]
	fn no_channel_ever_jumps() {
		// The steepest any gesture moves by itself, frame to frame.
		let lib = Library::builtin();
		let mut steepest = 0.0f32;
		for clip in &lib.clips {
			let mut m = Motion::new(Library::builtin(), all, 1);
			m.set_random(false);
			m.play(&clip.name, 1.0).unwrap();
			let (poses, _) = run(&mut m, clip.duration + 0.2, State::Speaking);
			steepest = steepest.max(largest_step(&poses));
		}
		// Gestures started on top of each other, taking parts of the body from each other, at odd moments.
		let mut m = Motion::new(Library::builtin(), all, 7);
		let mut poses = Vec::new();
		let script = [
			(0.0, "wave", ASKED), (0.2, "nod", SPEECH), (0.45, "shake", ASKED), (0.5, "brow_flash", SPEECH),
			(0.9, "hands_on_hips", ASKED), (1.1, "tilt", SPEECH), (1.3, "shrug", ASKED), (1.35, "laugh", SPEECH),
			(2.0, "think", SPEECH), (2.1, "look_away", ASKED), (2.2, "bow", SPEECH), (2.6, "lean_in", ASKED),
		];
		let mut next = 0;
		for i in 0..(6.0 / DT) as usize {
			let t = i as f32 * DT;
			while next < script.len() && script[next].0 <= t {
				let (_, g, p) = script[next];
				m.begin(m.find(g).unwrap(), 1.0, p);
				next += 1;
			}
			let mut p = Pose::default();
			m.apply(DT, &mut p, State::Speaking, true);
			poses.push(p);
		}
		let worst = largest_step(&poses);
		assert!(worst <= steepest * 1.25 + 1e-3, "{worst} against {steepest} for a gesture alone");
	}

	fn largest_step(poses: &[Pose]) -> f32 {
		let mut worst = 0.0f32;
		for w in poses.windows(2) {
			let (mut a, mut b) = (w[0], w[1]);
			for key in 0..KEYS.len() {
				worst = worst.max((*slot(&mut b, key) - *slot(&mut a, key)).abs());
			}
		}
		worst
	}

	#[test]
	fn gestures_per_minute_stay_in_a_band_over_ten_minutes() {
		// Ten minutes of conversation: 20 s of talking, then listening and quiet; a sentence every 2.5 s
		// with movements its words call for; now and then a new mood, and a gesture asked for.
		let mut m = Motion::new(Library::builtin(), all, 11);
		let moods = ["happy", "neutral", "thinking", "happy", "surprised", "sad", "angry", "embarrassed"];
		let words = ["nod", "tilt", "shake", "brow_flash", "wave", "laugh", "nod", "look_down", "shrug", "nod"];
		let mut rng = 5u64;
		let mut roll = || {
			rng ^= rng << 13;
			rng ^= rng >> 7;
			rng ^= rng << 17;
			(rng % 1000) as f32 / 1000.0
		};
		let mut per_minute = Vec::new();
		let frames = (600.0 / DT).round() as usize;
		for i in 0..frames {
			let t = i as f32 * DT;
			let cycle = t % 30.0;
			let state = if cycle < 20.0 { State::Speaking } else if cycle < 25.0 { State::Listening } else { State::Idle };
			if state == State::Speaking && (t % 2.5) < DT {
				if roll() < 0.15 {
					let _ = m.set_emotion(moods[(roll() * moods.len() as f32) as usize % moods.len()], 1.0);
				}
				if roll() < 0.6 {
					let _ = m.suggest(words[(roll() * words.len() as f32) as usize % words.len()], 0.8);
				}
				if roll() < 0.08 {
					let _ = m.play(["wave", "nod", "bow", "hands_on_hips"][(roll() * 4.0) as usize % 4], 1.0);
				}
			}
			let mut p = Pose::default();
			m.apply(DT, &mut p, state, true);
			// At the end of each minute, the gestures started in it: all of them, and big ones not asked for.
			if (i + 1) % (60.0 / DT).round() as usize == 0 {
				let all_count = m.recent.len();
				let own_big = m.recent.iter().filter(|r| r.1 < ASKED && r.2).count();
				per_minute.push((all_count, own_big));
			}
		}
		assert_eq!(per_minute.len(), 10);
		for (minute, (all_count, own_big)) in per_minute.iter().enumerate() {
			assert!((3..=14).contains(all_count), "minute {minute}: {all_count} gestures ({per_minute:?})");
			assert!(*own_big <= BIG_PER_MINUTE, "minute {minute}: {own_big} big ones not asked for");
		}
	}

	#[test]
	fn the_mood_varies_its_gestures() {
		let mut m = Motion::new(Library::builtin(), all, 3);
		let (_, started) = run(&mut m, 600.0, State::Speaking);
		assert!(started.len() > 20, "{}", started.len());
		let repeats = started.windows(2).filter(|w| w[0] == w[1]).count() as f32 / (started.len() - 1) as f32;
		// Without freshness the neutral mood repeats its favourite about 44% of the time.
		assert!(repeats < 0.3, "{repeats}: {started:?}");
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
	fn hands_on_hips_needs_an_elbow_and_bends_it() {
		let no_elbows = |k: &str| !k.ends_with("_b");
		assert!(!Motion::new(Library::builtin(), no_elbows, 1).gestures().contains(&"hands_on_hips".to_string()));
		let one_arm = |k: &str| !k.starts_with("arm_left");
		assert!(Motion::new(Library::builtin(), one_arm, 1).gestures().contains(&"hands_on_hips".to_string()),
			"one hand on the hip");
		assert!(Motion::new(Library::builtin(), no_elbows, 1).gestures().contains(&"wave".to_string()),
			"a wave still swings an arm without an elbow");
		let mut m = Motion::new(Library::builtin(), all, 1);
		m.set_random(false);
		m.play("hands_on_hips", 1.0).unwrap();
		let (poses, _) = run(&mut m, 1.5, State::Idle);
		let held = poses.last().unwrap();
		assert!((held.arm_left - 0.6).abs() < 0.05 && (held.arm_left_b + 0.9).abs() < 0.05, "{held:?}");
		assert!((held.arm_right - 0.6).abs() < 0.05 && (held.arm_right_b + 0.9).abs() < 0.05);
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
