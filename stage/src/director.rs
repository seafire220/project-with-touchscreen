//! The director: what the character feels like doing, between and around the conversation
//! (docs/26-animation-director.md, step 4).
//!
//! It keeps four slow **drives**, each from 0 to 1:
//! - **attention**: how much it is with you; high while you talk or it talks, fading when alone;
//! - **boredom**: grows through a quiet spell, gone the moment you speak or press the button;
//! - **sleepiness**: from the time of day (sleepy at night), and higher after a long quiet spell;
//! - **energy**: livelier in the morning, calmer in the evening, low when sleepy.
//!
//! From them it chooses the idle actions the character makes when nobody is talking (a look around,
//! a stretch, gazing out of the window, a yawn, nodding off), how lively its idle motion is, and how
//! drowsy it looks. After a long quiet spell at night it dozes: eyes closed, slow breathing, head
//! dropped; it wakes with a small start when spoken to or when the button is pressed. Someone coming
//! back after a long gap is greeted with raised brows and a smile.
//!
//! The time of day comes from the core (`{"clock": 21.5}`, local hours); without it, the director
//! assumes early afternoon.

use crate::behaviour::State;

/// A quiet spell this long (seconds) makes the character fully bored.
const BORED_AFTER: f32 = 600.0;
/// After this long without anyone, a returning person is greeted.
const RETURN_AFTER: f32 = 900.0;
/// At night, after this long without anyone, it may doze off.
const DOZE_AFTER: f32 = 480.0;
/// How sleepy it must be to doze.
const DOZE_SLEEPINESS: f32 = 0.6;
/// Assumed hour without a clock.
const DEFAULT_HOUR: f32 = 14.0;

/// Listening: the person's voice level (0 to 1) that counts as speech, and the level it must fall
/// below to count as a pause.
const VOICE_ON: f32 = 0.15;
const VOICE_OFF: f32 = 0.08;
/// A nod (or raised brows, or a tilt) may come in a pause this long, after this much speech, and no
/// sooner than this after the last.
const NOD_PAUSE: f32 = 0.25;
const NOD_AFTER: f32 = 0.8;
const NOD_GAP: f32 = 2.5;
/// How likely a pause brings a response (scaled by how expressive the character is).
const NOD_CHANCE: f32 = 0.55;
/// The person starting to speak after this much quiet makes it look up at them.
const ONSET_QUIET: f32 = 1.5;
/// Without a level for this long, the person is taken as quiet (no microphone, or it stopped).
const HEARD_STALE: f32 = 0.5;

/// How sleepy the hour makes the character, by hour of the day (straight lines between these points).
const SLEEPY_BY_HOUR: [(f32, f32); 8] =
	[(0.0, 0.85), (5.0, 0.75), (7.0, 0.3), (8.5, 0.0), (21.0, 0.0), (22.5, 0.45), (23.5, 0.75), (24.0, 0.85)];
/// How lively the hour makes it.
const ENERGY_BY_HOUR: [(f32, f32); 8] =
	[(0.0, 0.6), (6.0, 0.7), (8.0, 1.1), (11.0, 1.05), (14.0, 1.0), (18.0, 0.95), (21.0, 0.85), (24.0, 0.6)];

fn by_hour(table: &[(f32, f32)], hour: f32) -> f32 {
	let h = hour.rem_euclid(24.0);
	for w in table.windows(2) {
		let ((h0, v0), (h1, v1)) = (w[0], w[1]);
		if h <= h1 {
			return v0 + (v1 - v0) * ((h - h0) / (h1 - h0).max(1e-6)).clamp(0.0, 1.0);
		}
	}
	table.last().map(|p| p.1).unwrap_or(0.0)
}

fn ease(value: &mut f32, target: f32, dt: f32, seconds: f32) {
	*value += (target - *value) * (1.0 - (-dt / seconds.max(1e-3)).exp());
}

/// What the director wants from the rest of the stage this frame.
#[derive(Clone, Debug, PartialEq)]
pub struct Direction {
	/// How drowsy the character looks, 0 awake to 1 asleep.
	pub drowsy: f32,
	/// How lively its idle motion is, against usual.
	pub liveliness: f32,
	/// Gaps between its own gestures, against usual (2 is half as often).
	pub pace: f32,
	/// No gestures of its own: asleep, or responding to the person in their pauses instead.
	pub resting: bool,
	/// Idle actions to choose from while nobody is talking, and their weights.
	pub idle: Vec<(&'static str, f32)>,
	/// How much the mood's own gestures count among them.
	pub mood_share: f32,
	/// Reactions to play now (looking up as the person starts to speak).
	pub reactions: Vec<&'static str>,
	/// Responses to the person as they speak (a nod in their pause), with a strength.
	pub responses: Vec<(&'static str, f32)>,
}

pub struct Director {
	t: f32,
	/// (stage time when the clock was set, local hour then)
	clock: Option<(f32, f32)>,
	state: State,
	/// When someone last spoke, was spoken to, or pressed the button.
	last_contact: f32,
	pub attention: f32,
	pub boredom: f32,
	pub sleepiness: f32,
	pub energy: f32,
	drowsy: f32,
	pub dozing: bool,
	/// The character's temperament: how lively and how expressive (1 usual), from its settings.
	temper_energy: f32,
	temper_expression: f32,
	/// The person's voice, while listening: its level, when last heard, and how they are speaking.
	heard: f32,
	heard_at: f32,
	talking: bool,
	talk_run: f32,
	quiet_run: f32,
	responded: bool,
	last_response: f32,
	last_look_up: f32,
	/// How animated the person sounds, from their loudness while they speak.
	their_energy: f32,
	rng: u64,
}

impl Default for Director {
	fn default() -> Self {
		Self::new()
	}
}

impl Director {
	pub fn new() -> Self {
		Self {
			t: 0.0,
			clock: None,
			state: State::Idle,
			last_contact: 0.0,
			attention: 0.3,
			boredom: 0.0,
			sleepiness: 0.0,
			energy: 1.0,
			drowsy: 0.0,
			dozing: false,
			temper_energy: 1.0,
			temper_expression: 1.0,
			heard: 0.0,
			heard_at: f32::NEG_INFINITY,
			talking: false,
			talk_run: 0.0,
			quiet_run: 0.0,
			responded: true,
			last_response: f32::NEG_INFINITY,
			last_look_up: f32::NEG_INFINITY,
			their_energy: 0.3,
			rng: 0x9E37_79B9_7F4A_7C15,
		}
	}

	fn random(&mut self) -> f32 {
		self.rng ^= self.rng << 13;
		self.rng ^= self.rng >> 7;
		self.rng ^= self.rng << 17;
		((self.rng >> 40) as f32) / ((1u64 << 24) as f32)
	}

	/// The local time of day, in hours.
	pub fn set_clock(&mut self, hour: f32) {
		self.clock = Some((self.t, hour.rem_euclid(24.0)));
		// The hour sets how sleepy it is at once, rather than over minutes, when the stage starts.
		if self.t < 5.0 {
			self.sleepiness = by_hour(&SLEEPY_BY_HOUR, hour);
		}
	}

	pub fn hour(&self) -> f32 {
		match self.clock {
			Some((at, hour)) => (hour + (self.t - at) / 3600.0).rem_euclid(24.0),
			None => DEFAULT_HOUR,
		}
	}

	/// The character's temperament: liveliness and expressiveness, 1 for usual (0.5 to 1.5).
	pub fn set_temperament(&mut self, energy: f32, expression: f32) {
		self.temper_energy = energy.clamp(0.4, 1.6);
		self.temper_expression = expression.clamp(0.4, 1.6);
	}

	pub fn expressiveness(&self) -> f32 {
		self.temper_expression
	}

	/// The conversation state changed. Returns reactions to play now.
	pub fn on_state(&mut self, state: State) -> Vec<&'static str> {
		let before = self.state;
		self.state = state;
		if state == State::Idle {
			return Vec::new();
		}
		let mut reactions = self.contact();
		// Spoken to: it looks up at you.
		if state == State::Listening && before != State::Listening && reactions.is_empty() {
			reactions.push("look_up");
			self.last_look_up = self.t;
		}
		if state == State::Listening {
			self.talking = false;
			self.quiet_run = 0.0;
			self.responded = true;
		}
		reactions
	}

	/// How loud the person speaking is (while listening), 0 to 1.
	pub fn hear(&mut self, level: f32) {
		self.heard = level.clamp(0.0, 1.0);
		self.heard_at = self.t;
	}

	/// Follow the person's voice while listening: look up as they start after a quiet spell, and
	/// respond in their pauses, now and then.
	fn listen(&mut self, dt: f32, reactions: &mut Vec<&'static str>, responses: &mut Vec<(&'static str, f32)>) {
		let fresh = self.t - self.heard_at < HEARD_STALE;
		let level = if fresh { self.heard } else { 0.0 };
		if self.talking {
			if level < VOICE_OFF {
				self.quiet_run += dt;
				if self.quiet_run >= 0.15 {
					self.talking = false;
				}
			} else {
				self.quiet_run = 0.0;
				self.talk_run += dt;
				ease(&mut self.their_energy, level, dt, 2.0);
			}
		} else if level > VOICE_ON {
			if self.quiet_run >= ONSET_QUIET && self.t - self.last_look_up > 3.0 {
				reactions.push("look_up");
				self.last_look_up = self.t;
			}
			self.talking = true;
			self.talk_run = 0.0;
			self.quiet_run = 0.0;
			self.responded = false;
			self.attention = 1.0;
		} else {
			self.quiet_run += dt;
		}
		let pause = !self.talking && self.quiet_run >= NOD_PAUSE;
		if pause && !self.responded && self.talk_run >= NOD_AFTER && self.t - self.last_response > NOD_GAP {
			self.responded = true;
			if self.random() < NOD_CHANCE * self.temper_expression {
				self.last_response = self.t;
				let pick = self.random();
				let strength = 0.35 + 0.3 * self.their_energy;
				responses.push(if pick < 0.6 {
					("nod", strength)
				} else if pick < 0.8 {
					("brow_flash", strength * 0.8)
				} else {
					("tilt", strength)
				});
			}
		}
	}

	/// Whether the person's voice is reaching the character (a microphone is listening).
	fn hearing(&self) -> bool {
		self.state == State::Listening && self.t - self.heard_at < 2.0
	}

	/// Someone is there (the button was pressed, or they spoke). Returns reactions to play now.
	pub fn poke(&mut self) -> Vec<&'static str> {
		self.contact()
	}

	fn contact(&mut self) -> Vec<&'static str> {
		let mut reactions = Vec::new();
		if self.dozing {
			self.dozing = false;
			reactions.push("wake");
		}
		if self.t - self.last_contact > RETURN_AFTER {
			reactions.push("greet");
		}
		self.last_contact = self.t;
		self.attention = self.attention.max(0.9);
		reactions
	}

	/// Advance by `dt` seconds.
	pub fn update(&mut self, dt: f32) -> Direction {
		self.t += dt;
		let hour = self.hour();
		let alone = self.state == State::Idle;
		if !alone {
			self.last_contact = self.t;
		}
		let quiet = self.t - self.last_contact;
		let (mut reactions, mut responses) = (Vec::new(), Vec::new());
		if self.state == State::Listening {
			self.listen(dt, &mut reactions, &mut responses);
		}

		// Attention: up quickly when talking, down slowly when alone.
		match self.state {
			State::Listening | State::Speaking => ease(&mut self.attention, 1.0, dt, 0.5),
			State::Thinking => ease(&mut self.attention, 0.8, dt, 0.5),
			State::Idle => ease(&mut self.attention, 0.15, dt, 90.0),
		}
		// Boredom grows through a quiet spell; any contact ends it.
		if alone {
			self.boredom = (self.boredom + dt / BORED_AFTER).min(1.0);
		} else {
			ease(&mut self.boredom, 0.0, dt, 2.0);
		}
		// Sleepiness follows the hour, more so after a long quiet spell, less while talking.
		let sleepy = (by_hour(&SLEEPY_BY_HOUR, hour) * (0.85 + 0.3 * self.boredom) - 0.3 * (self.attention - 0.15).max(0.0))
			.clamp(0.0, 1.0);
		ease(&mut self.sleepiness, sleepy, dt, 60.0);
		let lively = by_hour(&ENERGY_BY_HOUR, hour) * (1.0 - 0.5 * self.sleepiness) * (0.9 + 0.2 * self.attention);
		ease(&mut self.energy, lively * self.temper_energy, dt, 10.0);

		// Dozing: only alone, at night, after a long quiet spell.
		if alone && !self.dozing && self.sleepiness > DOZE_SLEEPINESS && quiet > DOZE_AFTER {
			self.dozing = true;
		}
		let drowsy_target = if self.dozing {
			1.0
		} else if alone {
			0.45 * (self.sleepiness - 0.2).max(0.0)
		} else {
			0.15 * (self.sleepiness - 0.2).max(0.0)
		};
		// Eyes close slowly, open quickly.
		let speed = if drowsy_target > self.drowsy { 4.0 } else { 0.3 };
		ease(&mut self.drowsy, drowsy_target, dt, speed);

		let (b, s, a, e) = (self.boredom, self.sleepiness, self.attention, self.energy);
		let morning = by_hour(&[(0.0, 0.0), (6.0, 0.0), (7.5, 1.0), (10.0, 1.0), (11.5, 0.0), (24.0, 0.0)], hour);
		let alert = 1.0 - 0.7 * s;
		let idle = if self.dozing {
			Vec::new()
		} else {
			// Sleepy, it looks about less and yawns and nods off more.
			vec![
				("look_around", (1.5 + 1.0 * b) * (1.0 - 0.9 * s)),
				("look_out_window", (0.7 + 2.0 * b) * (1.0 - 0.6 * s)),
				("glance", 0.6 + 1.2 * a),
				("settle", 1.0),
				("hum_sway", 0.8 * e.min(1.2) * (1.0 - s) * self.temper_expression),
				("stretch", (0.3 + 1.2 * b + 0.8 * morning) * self.temper_expression * (1.0 - 0.5 * s)),
				("yawn", 3.5 * s + 0.2 * b),
				("nod_off", 5.0 * (s - 0.45).max(0.0)),
			]
		};
		// Bored: idle actions come more often; low energy or reserved: less often. While it hears the
		// person, its responses come in their pauses, not by chance.
		let pace = if alone {
			(1.2 - 0.4 * b) / (e * self.temper_expression).clamp(0.4, 1.5)
		} else if self.hearing() {
			4.0
		} else {
			1.0 / (e * self.temper_expression).clamp(0.5, 1.5)
		};
		// Listening, it matches the person's energy a little: livelier when they sound animated.
		let matching = if self.hearing() { 0.8 + 0.6 * self.their_energy } else { 1.0 };
		Direction {
			drowsy: self.drowsy,
			liveliness: e * (1.0 - 0.8 * self.drowsy) * matching,
			pace,
			resting: self.dozing || self.hearing(),
			idle,
			mood_share: 0.5 * alert,
			reactions,
			responses,
		}
	}
}

#[cfg(test)]
mod tests {
	use super::*;
	use crate::behaviour::Behaviour;
	use crate::motion::{Library, Motion};

	const DT: f32 = 0.1;

	fn pass(d: &mut Director, seconds: f32) -> Direction {
		let mut last = d.update(DT);
		for _ in 1..(seconds / DT) as usize {
			last = d.update(DT);
		}
		last
	}

	#[test]
	fn the_hour_sets_sleepiness_and_energy() {
		assert_eq!(by_hour(&SLEEPY_BY_HOUR, 14.0), 0.0);
		assert!(by_hour(&SLEEPY_BY_HOUR, 2.0) > 0.7);
		assert!(by_hour(&SLEEPY_BY_HOUR, 23.0) > 0.5);
		assert!(by_hour(&ENERGY_BY_HOUR, 9.0) > by_hour(&ENERGY_BY_HOUR, 20.0));
		let mut d = Director::new();
		d.set_clock(23.9);
		pass(&mut d, 600.0);
		assert!(d.hour() < 1.0, "the clock runs on past midnight: {}", d.hour());
	}

	#[test]
	fn boredom_grows_alone_and_contact_ends_it() {
		let mut d = Director::new();
		pass(&mut d, 300.0);
		assert!((d.boredom - 0.5).abs() < 0.02, "{}", d.boredom);
		d.on_state(State::Listening);
		pass(&mut d, 10.0);
		assert!(d.boredom < 0.01 && d.attention > 0.95);
		d.on_state(State::Idle);
		pass(&mut d, 120.0);
		assert!(d.attention < 0.6, "attention fades when alone: {}", d.attention);
	}

	#[test]
	fn it_dozes_only_at_night_after_a_long_quiet_spell_and_wakes_with_a_start() {
		let mut day = Director::new();
		day.set_clock(14.0);
		let dir = pass(&mut day, 1800.0);
		assert!(!day.dozing && dir.drowsy < 0.05, "never by day");
		assert!(dir.idle.iter().find(|a| a.0 == "yawn").unwrap().1 < 0.5, "and few yawns");

		let mut night = Director::new();
		night.set_clock(23.5);
		let early = pass(&mut night, 120.0);
		assert!(!night.dozing && early.drowsy > 0.1, "sleepy eyes first: {}", early.drowsy);
		assert!(early.idle.iter().find(|a| a.0 == "yawn").unwrap().1 > 1.5, "and yawns");
		let later = pass(&mut night, 600.0);
		assert!(night.dozing && later.resting && later.drowsy > 0.9, "then it dozes");
		assert!(later.idle.is_empty());
		assert_eq!(night.on_state(State::Listening), vec!["wake"], "spoken to, it wakes with a start");
		let awake = pass(&mut night, 1.5);
		assert!(!night.dozing && awake.drowsy < 0.15, "eyes open quickly: {}", awake.drowsy);
	}

	#[test]
	fn someone_coming_back_after_a_long_gap_is_greeted() {
		let mut d = Director::new();
		d.set_clock(10.0);
		assert_eq!(d.on_state(State::Listening), vec!["look_up"]);
		d.on_state(State::Idle);
		pass(&mut d, 60.0);
		assert_eq!(d.on_state(State::Listening), vec!["look_up"], "a minute is not a long gap");
		d.on_state(State::Idle);
		pass(&mut d, 1000.0);
		assert_eq!(d.poke(), vec!["greet"]);
		assert!(d.poke().is_empty(), "once");
	}

	#[test]
	fn the_mood_of_the_hour_shows_in_the_idle_actions() {
		let mut morning = Director::new();
		morning.set_clock(8.0);
		let m = pass(&mut morning, 60.0);
		let mut evening = Director::new();
		evening.set_clock(20.0);
		let e = pass(&mut evening, 60.0);
		let weight = |d: &Direction, name: &str| d.idle.iter().find(|a| a.0 == name).unwrap().1;
		assert!(weight(&m, "stretch") > weight(&e, "stretch"), "a morning stretch");
		assert!(m.liveliness > e.liveliness, "livelier in the morning");
		let mut bored = Director::new();
		let fresh = bored.update(DT);
		let later = pass(&mut bored, 600.0);
		assert!(weight(&later, "look_out_window") > 2.0 * weight(&fresh, "look_out_window"), "bored: gazing out");
		assert!(later.pace < fresh.pace, "and more often");
	}

	/// An hour alone, fast-forwarded as the stage runs it: (what started and when, closed eyes seen).
	fn an_hour_alone(hour: f32, seed: u64) -> (Vec<(f32, String)>, f32, bool) {
		let mut director = Director::new();
		director.set_clock(hour);
		let mut behaviour = Behaviour::new(seed);
		let mut motion = Motion::new(Library::builtin(), |_| true, seed);
		let dt = 1.0 / 30.0;
		let mut started = Vec::new();
		let mut most_closed = 0.0f32;
		let mut dozed = false;
		for i in 0..(3600.0 / dt) as usize {
			let d = director.update(dt);
			motion.set_idle(&d.idle, d.mood_share);
			motion.set_pace(d.pace);
			motion.set_resting(d.resting);
			let (energy, beats) = motion.style();
			behaviour.set_style(energy * d.liveliness, beats);
			behaviour.set_drowsy(d.drowsy);
			let mut pose = behaviour.update(dt);
			if let Some((name, _)) = motion.apply(dt, &mut pose, State::Idle, true) {
				started.push((i as f32 * dt, name));
			}
			if director.dozing {
				dozed = true;
				most_closed = most_closed.max(pose.blink);
			}
		}
		(started, most_closed, dozed)
	}

	#[test]
	fn an_hour_alone_by_day_is_varied_and_calm() {
		let (started, _, dozed) = an_hour_alone(14.0, 3);
		assert!(!dozed);
		let names: std::collections::BTreeSet<&str> = started.iter().map(|s| s.1.as_str()).collect();
		assert!(names.len() >= 7, "many different things: {names:?}");
		for idle in ["look_around", "look_out_window", "glance", "settle", "stretch"] {
			assert!(names.contains(idle), "{idle} in {names:?}");
		}
		let per_minute = started.len() as f32 / 60.0;
		assert!((1.5..=5.0).contains(&per_minute), "{per_minute} a minute");
		let repeats = started.windows(2).filter(|w| w[0].1 == w[1].1).count() as f32 / started.len() as f32;
		assert!(repeats < 0.15, "{repeats}");
		let yawns = started.iter().filter(|s| s.1 == "yawn").count();
		assert!(yawns <= 6, "few yawns by day: {yawns}");
	}

	#[test]
	fn an_hour_alone_at_night_grows_sleepy_then_dozes() {
		let (mut sleepy, mut all) = (0, 0);
		for seed in [3, 5, 7, 11] {
			let (started, most_closed, dozed) = an_hour_alone(23.0, seed);
			let before = started.iter().filter(|s| s.0 < 480.0);
			sleepy += before.clone().filter(|s| s.1 == "yawn" || s.1 == "nod_off").count();
			all += before.count();
			assert!(dozed && most_closed > 0.9, "asleep, eyes closed: {most_closed}");
			let last = started.last().map(|s| s.0).unwrap_or(0.0);
			assert!(last < 900.0, "nothing more once it sleeps (last at {last} s)");
		}
		assert!(sleepy * 4 >= all, "a quarter or more of what it does first is yawning and nodding off: {sleepy} of {all}");
	}

	/// A person speaking in stretches with pauses, `level` loud, for `seconds`: the responses (and when).
	fn listen_to(d: &mut Director, level: f32, talk: f32, pause: f32, seconds: f32) -> (Vec<(f32, String)>, Vec<f32>) {
		let (mut responses, mut looks) = (Vec::new(), Vec::new());
		let mut t = 0.0;
		while t < seconds {
			let speaking = (t % (talk + pause)) < talk;
			d.hear(if speaking { level } else { 0.02 });
			let dir = d.update(DT);
			for (name, _) in dir.responses {
				// A response comes in a pause, never while they speak.
				assert!(!speaking, "{name} at {t} while they speak");
				responses.push((t, name.to_string()));
			}
			looks.extend(dir.reactions.iter().filter(|r| **r == "look_up").map(|_| t));
			t += DT;
		}
		(responses, looks)
	}

	#[test]
	fn it_nods_in_the_persons_pauses_now_and_then() {
		let mut d = Director::new();
		assert_eq!(d.on_state(State::Listening), vec!["look_up"], "it looks up as listening starts");
		pass(&mut d, 4.0);
		let (responses, looks) = listen_to(&mut d, 0.5, 2.0, 0.6, 60.0);
		assert!((5..=16).contains(&responses.len()), "{responses:?}");
		assert!(responses.windows(2).all(|w| w[1].0 - w[0].0 >= NOD_GAP), "spaced out: {responses:?}");
		assert!(responses.iter().filter(|r| r.1 == "nod").count() * 2 >= responses.len(), "mostly nods");
		assert_eq!(looks.len(), 1, "it looked up as they started after the quiet: {looks:?}");
		// Silence brings nothing.
		let mut quiet = Director::new();
		quiet.on_state(State::Listening);
		let (none, no_looks) = listen_to(&mut quiet, 0.02, 2.0, 0.6, 30.0);
		assert!(none.is_empty() && no_looks.is_empty());
	}

	#[test]
	fn listening_matches_the_persons_energy_and_quiets_its_own_gestures() {
		let lively = |level: f32| {
			let mut d = Director::new();
			d.on_state(State::Listening);
			listen_to(&mut d, level, 3.0, 0.5, 20.0);
			d.hear(level);
			d.update(DT)
		};
		let (animated, calm) = (lively(0.9), lively(0.2));
		assert!(animated.liveliness > calm.liveliness * 1.2, "{} against {}", animated.liveliness, calm.liveliness);
		assert!(animated.resting, "its own random nods give way to responses in the pauses");
		let mut deaf = Director::new();
		deaf.on_state(State::Listening);
		assert!(!pass(&mut deaf, 5.0).resting, "without a microphone, it still nods now and then by itself");
	}
}
