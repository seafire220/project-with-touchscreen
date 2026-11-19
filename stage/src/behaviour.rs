//! Behaviour: breathing, blinking, gaze, head and body movement, beats with
//! speech, and mouth smoothing. Pure logic with no graphics, so it is
//! unit-tested. The design is in docs/24-motion.md: the eyes lead and the
//! head follows, posture drifts instead of repeating, nods and brow lifts
//! land on stressed syllables, and every movement goes through a spring so
//! nothing jumps.

use std::f32::consts::TAU;

use crate::smooth::Spring;

/// What the character is doing in the conversation.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum State {
	Idle,
	Listening,
	Thinking,
	Speaking,
}

impl State {
	pub fn parse(s: &str) -> Option<State> {
		match s {
			"idle" => Some(State::Idle),
			"listening" => Some(State::Listening),
			"thinking" => Some(State::Thinking),
			"speaking" => Some(State::Speaking),
			_ => None,
		}
	}

	pub fn name(self) -> &'static str {
		match self {
			State::Idle => "idle",
			State::Listening => "listening",
			State::Thinking => "thinking",
			State::Speaking => "speaking",
		}
	}
}

/// One frame of character controls. Ranges are fixed so that any kind of
/// character (puppet, clips, sprite) can be driven by the same values; each
/// character's calibration turns them into its own parameter values.
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Pose {
	/// 0 closed to 1 fully open.
	pub mouth_open: f32,
	/// 0 eyes open to 1 eyes closed.
	pub blink: f32,
	/// -1 to 1.
	pub head_yaw: f32,
	pub head_pitch: f32,
	pub head_roll: f32,
	pub body_yaw: f32,
	pub body_pitch: f32,
	pub body_roll: f32,
	/// 0 to 1.
	pub breath: f32,
	/// -1 to 1: where the eyes look (right and up are positive).
	pub gaze_x: f32,
	pub gaze_y: f32,
	/// -1 lowered to 1 raised.
	pub brows: f32,
	/// -1 downturned to 1 smiling (the mouth's shape).
	pub smile: f32,
	/// -1 to 1: the whole arm, at the shoulder: in towards the body or out from it.
	/// Our own characters put named poses at fixed values (studio/refine.py):
	/// 0.5 the arm of a wave, 0.6 the arm of a hand on the hip, 1 out and up.
	pub arm_left: f32,
	pub arm_right: f32,
	/// -1 to 1: the forearm, at the elbow: -0.9 a hand on the hip, 0.85 up
	/// to wave. Moods and gestures move these; at rest they stay 0.
	pub arm_left_b: f32,
	pub arm_right_b: f32,
	/// -1 to 1: shoulders lowered or raised.
	pub shoulders: f32,
	/// 0 to 1: smiling eyes.
	pub eye_smile: f32,
	/// 0 to 1: blush.
	pub cheek: f32,
	/// -1 angry to 1 worried: the brows' shape.
	pub brow_form: f32,
	/// 0 to 1 each: the mouth shaped for a, i, u, e or o, for characters with a parameter for each
	/// vowel (set while speaking, by speech.rs).
	pub vowel_a: f32,
	pub vowel_i: f32,
	pub vowel_u: f32,
	pub vowel_e: f32,
	pub vowel_o: f32,
}

const BLINK_CLOSE: f32 = 0.07;
const BLINK_HOLD: f32 = 0.04;
const BLINK_OPEN: f32 = 0.11;
/// Gaps between blinks follow a log-normal spread, as people's do.
const BLINK_MEDIAN_GAP: f32 = 3.4;
const BLINK_SPREAD: f32 = 0.45;
const BLINK_MIN_GAP: f32 = 1.2;
const BLINK_MAX_GAP: f32 = 9.0;
/// Chance of a blink straight after a large gaze shift.
const BLINK_WITH_GAZE: f32 = 0.35;
const BREATH_PERIOD: f32 = 3.6;
const MOUTH_RISE: f32 = 0.035;
const MOUTH_FALL: f32 = 0.07;
/// Below this the mouth snaps shut, so it never hangs slightly open.
const MOUTH_SHUT: f32 = 0.02;
const SETTLE: f32 = 0.35;
/// Springs: the eyes jump, the head follows, posture drifts.
const GAZE_TIME: f32 = 0.045;
const HEAD_TIME: f32 = 0.22;
/// Fastest the head turns, in control units per second, however far it is told to look.
const HEAD_MAX_SPEED: f32 = 2.5;
const POSTURE_TIME: f32 = 1.4;
const BROW_TIME: f32 = 0.12;
const NOD_TIME: f32 = 0.09;
const SMILE_TIME: f32 = 0.6;
const ARM_TIME: f32 = 0.45;
/// Beats: a loudness rise this far above the recent level is a stressed syllable.
const BEAT_RISE: f32 = 0.18;
const BEAT_MIN_GAP: f32 = 0.28;
const BEAT_NOD: f32 = 0.09;
const BEAT_HOLD: f32 = 0.16;
const BROW_HOLD: f32 = 0.3;
const LOUDNESS_MEMORY: f32 = 0.25;
const ARM_ACCENT: f32 = 0.15;
const ARM_ACCENT_FADE: f32 = 0.5;
const ARM_LIMIT: f32 = 0.25;

pub struct Behaviour {
	t: f32,
	rng: u64,
	state: State,
	mouth_target: f32,
	mouth: f32,
	next_blink: f32,
	blink_started: Option<f32>,
	look_target: (f32, f32),
	/// Smoothed offsets that change with the conversation state.
	look: (f32, f32),
	tilt: f32,
	energy: f32,
	/// When false the character holds still: no sway, breathing, gaze shifts,
	/// beats or automatic blinks.
	idle_motion: bool,
	gaze: (Spring, Spring),
	gaze_target: (f32, f32),
	next_gaze: f32,
	posture: [Spring; 3],
	posture_target: [f32; 3],
	next_posture: f32,
	head: [Spring; 3],
	nod: Spring,
	nod_until: f32,
	nod_depth: f32,
	brows: Spring,
	brow_lift: f32,
	brow_until: f32,
	smile: Spring,
	arms: [Spring; 2],
	arm_accent: [f32; 2],
	next_arm: usize,
	loudness: f32,
	last_beat: f32,
	/// From the mood: how lively idle motion is, and how strong the beats.
	style_energy: f32,
	style_beats: f32,
	/// 0 awake to 1 asleep (from the director): heavy eyelids, slow breathing, the head dropping.
	drowsy: f32,
	/// Whether the eyes can rest half closed. Characters made from a picture swap an open eye for a
	/// closed one, which half way shows both; theirs blink longer and more often when drowsy instead.
	smooth_eyelids: bool,
	breath_phase: f32,
	/// Leaning in a little while listening.
	lean: Spring,
}

impl Behaviour {
	pub fn new(seed: u64) -> Self {
		let spring = |time| Spring::new(0.0, time);
		let mut b = Self {
			t: 0.0,
			rng: seed.max(1),
			state: State::Idle,
			mouth_target: 0.0,
			mouth: 0.0,
			next_blink: 0.0,
			blink_started: None,
			look_target: (0.0, 0.0),
			look: (0.0, 0.0),
			tilt: 0.0,
			energy: 1.0,
			idle_motion: true,
			gaze: (spring(GAZE_TIME), spring(GAZE_TIME)),
			gaze_target: (0.0, 0.0),
			next_gaze: 1.0,
			posture: [spring(POSTURE_TIME), spring(POSTURE_TIME), spring(POSTURE_TIME)],
			posture_target: [0.0; 3],
			next_posture: 2.0,
			head: [
				spring(HEAD_TIME).with_max_speed(HEAD_MAX_SPEED),
				spring(HEAD_TIME).with_max_speed(HEAD_MAX_SPEED),
				spring(HEAD_TIME).with_max_speed(HEAD_MAX_SPEED),
			],
			nod: spring(NOD_TIME),
			nod_until: 0.0,
			nod_depth: 0.0,
			brows: spring(BROW_TIME),
			brow_lift: 0.0,
			brow_until: 0.0,
			smile: spring(SMILE_TIME),
			arms: [spring(ARM_TIME), spring(ARM_TIME)],
			arm_accent: [0.0; 2],
			next_arm: 0,
			loudness: 0.0,
			last_beat: -1.0,
			style_energy: 1.0,
			style_beats: 1.0,
			drowsy: 0.0,
			smooth_eyelids: true,
			breath_phase: 0.0,
			lean: spring(0.8),
		};
		b.next_blink = b.random_gap();
		b
	}

	pub fn state(&self) -> State {
		self.state
	}

	pub fn set_state(&mut self, state: State) {
		self.state = state;
		if state != State::Speaking {
			self.mouth_target = 0.0;
		}
		// A new state is a natural moment to look somewhere new.
		self.next_gaze = self.next_gaze.min(self.t + 0.15);
	}

	/// Loudness of the voice being played right now, 0 to 1.
	pub fn set_mouth(&mut self, level: f32) {
		self.mouth_target = level.clamp(0.0, 1.0);
	}

	/// Blink now, regardless of the automatic timing.
	pub fn blink_now(&mut self) {
		if self.blink_started.is_none() {
			self.blink_started = Some(self.t);
		}
	}

	/// Turn idle movement on or off. Mouth, commanded blinks and looking still work.
	pub fn set_idle_motion(&mut self, on: bool) {
		self.idle_motion = on;
	}

	/// How the current mood moves: idle liveliness and beat strength, 1 for usual.
	pub fn set_style(&mut self, energy: f32, beats: f32) {
		self.style_energy = energy.clamp(0.0, 2.0);
		self.style_beats = beats.clamp(0.0, 2.0);
	}

	/// How drowsy the character is, 0 awake to 1 asleep.
	pub fn set_drowsy(&mut self, drowsy: f32) {
		self.drowsy = drowsy.clamp(0.0, 1.0);
	}

	/// Whether the eyes can rest half closed (see `smooth_eyelids`).
	pub fn set_smooth_eyelids(&mut self, smooth: bool) {
		self.smooth_eyelids = smooth;
	}

	/// Where the character should look, each axis -1 to 1.
	pub fn set_look(&mut self, x: f32, y: f32) {
		self.look_target = (x.clamp(-1.0, 1.0), y.clamp(-1.0, 1.0));
	}

	fn next_random(&mut self) -> f32 {
		// xorshift64*, deterministic for a given seed
		self.rng ^= self.rng >> 12;
		self.rng ^= self.rng << 25;
		self.rng ^= self.rng >> 27;
		let v = self.rng.wrapping_mul(0x2545_F491_4F6C_DD1D);
		((v >> 40) as f32) / ((1u64 << 24) as f32)
	}

	/// A random number between lo and hi.
	fn between(&mut self, lo: f32, hi: f32) -> f32 {
		lo + self.next_random() * (hi - lo)
	}

	/// A normally distributed number (Box-Muller).
	fn normal(&mut self) -> f32 {
		let u = self.next_random().max(1e-6);
		let v = self.next_random();
		(-2.0 * u.ln()).sqrt() * (TAU * v).cos()
	}

	fn random_gap(&mut self) -> f32 {
		// Drowsy eyes blink more often.
		let often = 1.0 - 0.5 * self.drowsy;
		(BLINK_MEDIAN_GAP * often * (BLINK_SPREAD * self.normal()).exp()).clamp(BLINK_MIN_GAP * often, BLINK_MAX_GAP)
	}

	fn blink_value(&mut self) -> f32 {
		if self.blink_started.is_none() && self.idle_motion && self.t >= self.next_blink {
			self.blink_started = Some(self.t);
		}
		let Some(start) = self.blink_started else {
			return 0.0;
		};
		// Sleepy eyes blink slowly, and stay shut a while.
		let slow = 1.0 + self.drowsy;
		let (close, hold, open) = (BLINK_CLOSE * slow, BLINK_HOLD * (1.0 + 6.0 * self.drowsy), BLINK_OPEN * slow);
		let e = self.t - start;
		if e < close {
			e / close
		} else if e < close + hold {
			1.0
		} else if e < close + hold + open {
			1.0 - (e - close - hold) / open
		} else {
			self.blink_started = None;
			self.next_blink = self.t + self.random_gap();
			0.0
		}
	}

	/// Pick where the eyes go next, by what the character is doing.
	fn shift_gaze(&mut self) {
		let (x, y, wait) = match self.state {
			State::Idle => (self.between(-0.45, 0.45), self.between(-0.15, 0.25), self.between(1.2, 4.0)),
			State::Listening => (self.between(-0.12, 0.12), self.between(-0.03, 0.13), self.between(1.5, 4.5)),
			State::Thinking => {
				let side = if self.next_random() < 0.5 { -1.0 } else { 1.0 };
				(side * self.between(0.35, 0.6), self.between(0.25, 0.5), self.between(1.0, 2.5))
			}
			State::Speaking => {
				if self.next_random() < 0.7 {
					(self.between(-0.1, 0.1), self.between(-0.05, 0.08), self.between(0.8, 2.5))
				} else {
					(self.between(-0.4, 0.4), self.between(-0.1, 0.2), self.between(0.4, 1.0))
				}
			}
		};
		let jump = (x - self.gaze_target.0).hypot(y - self.gaze_target.1);
		self.gaze_target = (x, y);
		self.next_gaze = self.t + wait;
		// The eyes often blink as they move a long way.
		if jump > 0.3 && self.next_random() < BLINK_WITH_GAZE {
			self.blink_now();
		}
	}

	/// A new resting posture every few seconds, so idle motion never repeats.
	fn shift_posture(&mut self) {
		self.posture_target = [self.between(-0.12, 0.12), self.between(-0.06, 0.06), self.between(-0.06, 0.06)];
		self.next_posture = self.t + self.between(2.5, 6.0);
	}

	/// Stressed syllables: a quick rise in loudness above its recent level.
	fn listen_for_beats(&mut self, dt: f32) {
		let level = self.mouth_target;
		let speaking = self.idle_motion && self.state == State::Speaking;
		if speaking && level - self.loudness > BEAT_RISE && self.t - self.last_beat > BEAT_MIN_GAP {
			let strength = level.clamp(0.3, 1.0) * self.style_beats;
			self.last_beat = self.t;
			self.nod_depth = BEAT_NOD * strength;
			self.nod_until = self.t + BEAT_HOLD;
			if strength > 0.55 {
				self.brow_lift = 0.5 * strength;
				self.brow_until = self.t + BROW_HOLD;
			}
			self.arm_accent[self.next_arm] = ARM_ACCENT * strength;
			self.next_arm = 1 - self.next_arm;
		}
		self.loudness += (level - self.loudness) * (1.0 - (-dt / LOUDNESS_MEMORY).exp());
	}

	/// Advance by `dt` seconds and return the controls for this frame.
	pub fn update(&mut self, dt: f32) -> Pose {
		let dt = dt.clamp(0.0, 0.25);
		self.t += dt;
		let t = self.t;

		// State-dependent targets.
		let (mut energy, tilt, state_look, state_brows, state_smile) = match self.state {
			State::Idle => (1.0, 0.0, (0.0, 0.0), 0.0, 0.05),
			State::Listening => (0.55, 0.14, (0.0, 0.05), 0.15, 0.12),
			State::Thinking => (0.8, -0.08, (0.28, -0.22), -0.1, 0.0),
			State::Speaking => (1.25, 0.0, (0.0, 0.0), 0.0, 0.08),
		};
		energy *= self.style_energy * (1.0 - 0.85 * self.drowsy);
		if !self.idle_motion {
			energy = 0.0;
			self.energy = 0.0;
		}
		let k = 1.0 - (-dt / SETTLE).exp();
		self.energy += (energy - self.energy) * k;
		self.tilt += (tilt - self.tilt) * k;
		let lx = (self.look_target.0 + state_look.0).clamp(-1.0, 1.0);
		let ly = (self.look_target.1 + state_look.1).clamp(-1.0, 1.0);
		self.look.0 += (lx - self.look.0) * k;
		self.look.1 += (ly - self.look.1) * k;

		// Mouth follows loudness quickly on the way up, more slowly on the way down.
		let tau = if self.mouth_target > self.mouth { MOUTH_RISE } else { MOUTH_FALL };
		self.mouth += (self.mouth_target - self.mouth) * (1.0 - (-dt / tau).exp());
		if self.mouth_target == 0.0 && self.mouth < MOUTH_SHUT {
			self.mouth = 0.0;
		}

		if self.idle_motion {
			// Eyes too heavy to wander.
			if t >= self.next_gaze && self.drowsy < 0.6 {
				self.shift_gaze();
			}
			if t >= self.next_posture {
				self.shift_posture();
			}
		} else {
			self.gaze_target = (0.0, 0.0);
			self.posture_target = [0.0; 3];
		}
		self.listen_for_beats(dt);

		// Eyes jump; the head follows part of the way.
		let gx = self.gaze.0.update((self.gaze_target.0 + 0.8 * self.look.0).clamp(-1.0, 1.0), dt);
		let gy = self.gaze.1.update((self.gaze_target.1 + 0.8 * self.look.1 - 0.2 * self.drowsy).clamp(-1.0, 1.0), dt);
		let posture: Vec<f32> = (0..3).map(|i| self.posture[i].update(self.posture_target[i] * self.energy, dt)).collect();
		let nod = self.nod.update(if t < self.nod_until { -self.nod_depth } else { 0.0 }, dt);

		let e = self.energy;
		let yaw = e * (0.12 * (t * 0.55).sin() + 0.05 * (t * 1.31 + 1.7).sin()) + posture[0] + self.look.0 * 0.6
			+ (gx - 0.8 * self.look.0) * 0.25;
		let pitch = e * (0.07 * (t * 0.43 + 0.6).sin() + 0.03 * (t * 1.07).sin()) + posture[1] + self.look.1 * 0.6
			+ (gy - 0.8 * self.look.1) * 0.2;
		let roll = e * 0.07 * (t * 0.37 + 2.1).sin() + posture[2] + self.tilt + 0.08 * self.drowsy;
		// A drowsy head drops.
		let pitch = pitch - 0.3 * self.drowsy;
		let head_yaw = self.head[0].update(yaw, dt);
		// Nods are quick and deliberate: on top of the smoothed head, with their own short spring.
		let head_pitch = self.head[1].update(pitch, dt) + nod;
		let head_roll = self.head[2].update(roll, dt);

		let brow_target = if self.idle_motion && t < self.brow_until { self.brow_lift } else { state_brows * e.min(1.0) };
		let brows = self.brows.update(brow_target, dt);
		let smile = self.smile.update(if self.idle_motion { state_smile * (1.0 - self.drowsy) } else { 0.0 }, dt);

		// Breathing slows as it gets drowsy (a phase, so the change never jumps).
		self.breath_phase += TAU * dt / (BREATH_PERIOD * (1.0 + 0.7 * self.drowsy));
		let breath = if self.idle_motion { 0.5 - 0.5 * self.breath_phase.cos() } else { 0.0 };
		let lean = self.lean.update(if self.idle_motion && self.state == State::Listening { 0.07 } else { 0.0 }, dt);
		let fade = (-dt / ARM_ACCENT_FADE).exp();
		for accent in &mut self.arm_accent {
			*accent *= fade;
		}
		let arm_left = self.arms[0].update(
			(e * 0.05 * (t * 0.4 + 0.3).sin() + 0.02 * e * breath + self.arm_accent[0]).clamp(-ARM_LIMIT, ARM_LIMIT),
			dt,
		);
		let arm_right = self.arms[1].update(
			(e * 0.05 * (t * 0.37 + 2.0).sin() + 0.02 * e * breath + self.arm_accent[1]).clamp(-ARM_LIMIT, ARM_LIMIT),
			dt,
		);

		// Heavy eyelids: as far closed as it is drowsy, at least; eyes that cannot rest half closed stay
		// open until it is nearly asleep, then close.
		let heavy = if !self.idle_motion {
			0.0
		} else if self.smooth_eyelids {
			self.drowsy
		} else {
			((self.drowsy - 0.85) / 0.05).clamp(0.0, 1.0)
		};
		let blink = self.blink_value().max(heavy);
		Pose {
			mouth_open: self.mouth,
			blink,
			head_yaw: head_yaw.clamp(-1.0, 1.0),
			head_pitch: head_pitch.clamp(-1.0, 1.0),
			head_roll: head_roll.clamp(-1.0, 1.0),
			body_yaw: e * 0.10 * (t * 0.31 + 0.9).sin() + 0.2 * posture[0],
			body_pitch: e * 0.04 * (t * 0.47 + 1.3).sin() + lean,
			body_roll: e * 0.05 * (t * 0.29).sin(),
			breath,
			gaze_x: gx,
			gaze_y: gy,
			brows: brows.clamp(-1.0, 1.0),
			smile: smile.clamp(-1.0, 1.0),
			arm_left,
			arm_right,
			arm_left_b: 0.0,
			arm_right_b: 0.0,
			shoulders: if self.idle_motion { 0.15 * breath } else { 0.0 },
			// Moods and gestures move these (motion.rs).
			eye_smile: 0.0,
			cheek: 0.0,
			brow_form: 0.0,
			// The speech module (speech.rs) shapes these while speaking.
			vowel_a: 0.0,
			vowel_i: 0.0,
			vowel_u: 0.0,
			vowel_e: 0.0,
			vowel_o: 0.0,
		}
	}
}

#[cfg(test)]
mod tests {
	use super::*;

	fn run(b: &mut Behaviour, seconds: f32) -> Vec<Pose> {
		let dt = 1.0 / 60.0;
		(0..(seconds / dt) as usize).map(|_| b.update(dt)).collect()
	}

	#[test]
	fn values_stay_in_range() {
		let mut b = Behaviour::new(7);
		b.set_state(State::Speaking);
		b.set_mouth(1.0);
		b.set_look(1.0, -1.0);
		for p in run(&mut b, 30.0) {
			for v in [p.mouth_open, p.blink, p.breath] {
				assert!((0.0..=1.0).contains(&v), "{v}");
			}
			for v in [p.head_yaw, p.head_pitch, p.head_roll, p.body_yaw, p.body_pitch, p.body_roll, p.gaze_x, p.gaze_y,
				p.brows, p.smile, p.arm_left, p.arm_right, p.shoulders] {
				assert!((-1.0..=1.0).contains(&v), "{v}");
			}
		}
	}

	#[test]
	fn blinks_happen_at_a_natural_rate() {
		let mut b = Behaviour::new(42);
		let poses = run(&mut b, 60.0);
		let mut blinks = 0;
		let mut closed = false;
		for p in &poses {
			if p.blink > 0.99 && !closed {
				blinks += 1;
				closed = true;
			}
			if p.blink < 0.01 {
				closed = false;
			}
		}
		// Gaps are 2.2 to 6 s, so a minute holds roughly 10 to 26 blinks.
		assert!((9..=27).contains(&blinks), "{blinks} blinks in a minute");
	}

	#[test]
	fn mouth_opens_fast_and_closes_within_a_quarter_second() {
		let mut b = Behaviour::new(1);
		b.set_state(State::Speaking);
		b.set_mouth(1.0);
		let open = run(&mut b, 0.12);
		assert!(open.last().unwrap().mouth_open > 0.9);
		b.set_mouth(0.0);
		let closing = run(&mut b, 0.25);
		assert!(closing.last().unwrap().mouth_open < 0.05);
		let closed = run(&mut b, 0.25);
		assert_eq!(closed.last().unwrap().mouth_open, 0.0);
	}

	#[test]
	fn leaving_speaking_closes_the_mouth() {
		let mut b = Behaviour::new(1);
		b.set_state(State::Speaking);
		b.set_mouth(0.8);
		run(&mut b, 0.2);
		b.set_state(State::Idle);
		assert_eq!(run(&mut b, 0.6).last().unwrap().mouth_open, 0.0);
	}

	#[test]
	fn same_seed_gives_same_motion() {
		let mut a = Behaviour::new(99);
		let mut b = Behaviour::new(99);
		assert_eq!(run(&mut a, 20.0), run(&mut b, 20.0));
	}

	#[test]
	fn holding_still_stops_idle_motion_but_not_commands() {
		let mut b = Behaviour::new(5);
		b.set_idle_motion(false);
		let poses = run(&mut b, 20.0);
		assert!(poses.iter().all(|p| p.blink == 0.0 && p.breath == 0.0 && p.head_yaw == 0.0 && p.body_roll == 0.0
			&& p.gaze_x == 0.0 && p.brows == 0.0 && p.smile == 0.0 && p.arm_left == 0.0 && p.shoulders == 0.0));
		b.blink_now();
		assert!(run(&mut b, 0.3).iter().any(|p| p.blink > 0.99));
		assert_eq!(run(&mut b, 1.0).last().unwrap().blink, 0.0);
	}

	#[test]
	fn breathing_cycles() {
		let mut b = Behaviour::new(3);
		let poses = run(&mut b, 8.0);
		let max = poses.iter().map(|p| p.breath).fold(0.0, f32::max);
		let min = poses.iter().map(|p| p.breath).fold(1.0, f32::min);
		assert!(max > 0.98 && min < 0.02);
	}

	/// Largest change between frames, per unit of time: nothing may jump.
	fn steepest(poses: &[Pose], get: impl Fn(&Pose) -> f32) -> f32 {
		poses.windows(2).map(|w| (get(&w[1]) - get(&w[0])).abs() * 60.0).fold(0.0, f32::max)
	}

	#[test]
	fn the_eyes_move_around_and_the_head_follows_smoothly() {
		let mut b = Behaviour::new(11);
		let poses = run(&mut b, 30.0);
		let xs: Vec<f32> = poses.iter().map(|p| p.gaze_x).collect();
		let spread = xs.iter().cloned().fold(f32::MIN, f32::max) - xs.iter().cloned().fold(f32::MAX, f32::min);
		assert!(spread > 0.3, "the eyes look around: {spread}");
		assert!(steepest(&poses, |p| p.head_yaw) < 1.5, "the head never jumps: {}", steepest(&poses, |p| p.head_yaw));
		assert!(steepest(&poses, |p| p.gaze_x) > steepest(&poses, |p| p.head_yaw), "eyes move faster than the head");
	}

	#[test]
	fn idle_motion_does_not_repeat() {
		let mut b = Behaviour::new(4);
		let poses = run(&mut b, 40.0);
		// The old motion was a fixed sum of sines; now posture drifts, so two
		// stretches 17 s apart (about one period of the slowest sine) differ.
		let a: Vec<f32> = poses[600..900].iter().map(|p| p.head_yaw).collect();
		let c: Vec<f32> = poses[1620..1920].iter().map(|p| p.head_yaw).collect();
		let diff = a.iter().zip(&c).map(|(x, y)| (x - y).abs()).fold(0.0, f32::max);
		assert!(diff > 0.03, "{diff}");
	}

	#[test]
	fn stressed_syllables_bring_nods_and_brow_lifts() {
		let mut b = Behaviour::new(2);
		b.set_state(State::Speaking);
		run(&mut b, 1.0);
		let before = run(&mut b, 0.5);
		// A loud syllable after quiet: a beat.
		b.set_mouth(0.9);
		let beat = run(&mut b, 0.3);
		let calm_pitch = before.iter().map(|p| p.head_pitch).fold(f32::MAX, f32::min);
		let nod_pitch = beat.iter().map(|p| p.head_pitch).fold(f32::MAX, f32::min);
		assert!(nod_pitch < calm_pitch - 0.02, "the head dips: {nod_pitch} vs {calm_pitch}");
		assert!(beat.iter().any(|p| p.brows > 0.2), "the brows lift on a strong beat");
		// Held loudness is not a new beat.
		let held = run(&mut b, 1.0);
		assert!(held.last().unwrap().brows < 0.1);
	}

	#[test]
	fn blink_gaps_vary_like_peoples() {
		let mut b = Behaviour::new(8);
		let gaps: Vec<f32> = (0..400).map(|_| b.random_gap()).collect();
		let mean = gaps.iter().sum::<f32>() / gaps.len() as f32;
		assert!((3.0..4.6).contains(&mean), "{mean}");
		assert!(gaps.iter().any(|g| *g < 2.2) && gaps.iter().any(|g| *g > 5.5), "short and long gaps both occur");
		assert!(gaps.iter().all(|g| (BLINK_MIN_GAP..=BLINK_MAX_GAP).contains(g)));
	}

	#[test]
	fn drowsy_eyes_droop_or_blink_slowly_by_the_kind_of_eyelid() {
		let mut smooth = Behaviour::new(5);
		smooth.set_drowsy(0.4);
		assert!(run(&mut smooth, 20.0).iter().all(|p| p.blink >= 0.4 - 1e-6), "a drawn eyelid rests half closed");
		let mut swapped = Behaviour::new(5);
		swapped.set_smooth_eyelids(false);
		let awake = run(&mut swapped, 60.0).iter().filter(|p| p.blink > 0.5).count();
		swapped.set_drowsy(0.4);
		let drowsy = run(&mut swapped, 60.0);
		// Half closed only in passing, as in any blink: never longer than a slow blink takes.
		let mut longest = 0;
		let mut run_length = 0;
		for p in &drowsy {
			run_length = if p.blink > 0.05 && p.blink < 0.95 { run_length + 1 } else { 0 };
			longest = longest.max(run_length);
		}
		assert!((longest as f32) / 60.0 < 0.2, "an eye that swaps drawings never rests half closed: {longest} frames");
		let closed = drowsy.iter().filter(|p| p.blink > 0.5).count();
		assert!(closed > awake * 2, "it blinks longer and more often instead: {closed} against {awake}");
		swapped.set_drowsy(0.97);
		assert!(run(&mut swapped, 2.0).last().unwrap().blink > 0.99, "asleep, shut");
	}
}
