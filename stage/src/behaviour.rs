//! Idle behaviour: breathing, blinking, small head and body movement, and
//! mouth smoothing. Pure logic with no graphics, so it is unit-tested.

use std::f32::consts::TAU;

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
/// character (puppet, clips, sprite) can be driven by the same values.
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
}

const BLINK_CLOSE: f32 = 0.07;
const BLINK_HOLD: f32 = 0.04;
const BLINK_OPEN: f32 = 0.11;
const BLINK_MIN_GAP: f32 = 2.2;
const BLINK_MAX_GAP: f32 = 6.0;
const BREATH_PERIOD: f32 = 3.6;
const MOUTH_RISE: f32 = 0.035;
const MOUTH_FALL: f32 = 0.07;
/// Below this the mouth snaps shut, so it never hangs slightly open.
const MOUTH_SHUT: f32 = 0.02;
const SETTLE: f32 = 0.35;

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
	/// When false the character holds still: no sway, breathing or automatic blinks.
	idle_motion: bool,
}

impl Behaviour {
	pub fn new(seed: u64) -> Self {
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

	fn random_gap(&mut self) -> f32 {
		BLINK_MIN_GAP + self.next_random() * (BLINK_MAX_GAP - BLINK_MIN_GAP)
	}

	fn blink_value(&mut self) -> f32 {
		if self.blink_started.is_none() && self.idle_motion && self.t >= self.next_blink {
			self.blink_started = Some(self.t);
		}
		let Some(start) = self.blink_started else {
			return 0.0;
		};
		let e = self.t - start;
		if e < BLINK_CLOSE {
			e / BLINK_CLOSE
		} else if e < BLINK_CLOSE + BLINK_HOLD {
			1.0
		} else if e < BLINK_CLOSE + BLINK_HOLD + BLINK_OPEN {
			1.0 - (e - BLINK_CLOSE - BLINK_HOLD) / BLINK_OPEN
		} else {
			self.blink_started = None;
			self.next_blink = self.t + self.random_gap();
			0.0
		}
	}

	/// Advance by `dt` seconds and return the controls for this frame.
	pub fn update(&mut self, dt: f32) -> Pose {
		let dt = dt.clamp(0.0, 0.25);
		self.t += dt;
		let t = self.t;

		// State-dependent targets.
		let (mut energy, tilt, state_look) = match self.state {
			State::Idle => (1.0, 0.0, (0.0, 0.0)),
			State::Listening => (0.55, 0.14, (0.0, 0.05)),
			State::Thinking => (0.8, -0.08, (0.28, -0.22)),
			State::Speaking => (1.25, 0.0, (0.0, 0.0)),
		};
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

		let e = self.energy;
		// A slight nod with the voice while speaking; part of idle movement.
		let speak_bob = if self.idle_motion && self.state == State::Speaking { self.mouth * 0.06 } else { 0.0 };
		let pose = Pose {
			mouth_open: self.mouth,
			blink: self.blink_value(),
			head_yaw: e * (0.18 * (t * 0.55).sin() + 0.07 * (t * 1.31 + 1.7).sin()) + self.look.0 * 0.6,
			head_pitch: e * (0.10 * (t * 0.43 + 0.6).sin() + 0.04 * (t * 1.07).sin()) + self.look.1 * 0.6 - speak_bob,
			head_roll: e * 0.08 * (t * 0.37 + 2.1).sin() + self.tilt,
			body_yaw: e * 0.10 * (t * 0.31 + 0.9).sin(),
			body_pitch: e * 0.04 * (t * 0.47 + 1.3).sin(),
			body_roll: e * 0.05 * (t * 0.29).sin(),
			breath: if self.idle_motion { 0.5 - 0.5 * (TAU * t / BREATH_PERIOD).cos() } else { 0.0 },
		};
		Pose {
			head_yaw: pose.head_yaw.clamp(-1.0, 1.0),
			head_pitch: pose.head_pitch.clamp(-1.0, 1.0),
			head_roll: pose.head_roll.clamp(-1.0, 1.0),
			..pose
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
			for v in [p.head_yaw, p.head_pitch, p.head_roll, p.body_yaw, p.body_pitch, p.body_roll] {
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
		assert!(poses.iter().all(|p| p.blink == 0.0 && p.breath == 0.0 && p.head_yaw == 0.0 && p.body_roll == 0.0));
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
}
