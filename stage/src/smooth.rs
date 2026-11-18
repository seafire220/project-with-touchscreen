//! Smoothing for character controls.
//!
//! `Spring` follows a moving target the way a relaxed body part does: it
//! starts gently, does not overshoot, and settles in about its `time`. It is
//! the critically damped spring often called "smooth damp" (Game
//! Programming Gems 4, ch. 1.10), stable at any frame time.
//!
//! `OneEuro` cleans a noisy signal (loudness, recorded or tracked motion):
//! a low-pass filter whose cut-off rises with speed, so slow changes are
//! smoothed and fast ones are not delayed (Casiez, Roussel and Vogel, CHI
//! 2012).

use std::f32::consts::TAU;

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Spring {
	pub value: f32,
	pub velocity: f32,
	/// Roughly the time to cover most of the way to a new target, in seconds.
	pub time: f32,
	/// Largest speed, in units per second (infinite for none).
	pub max_speed: f32,
}

impl Spring {
	pub fn new(value: f32, time: f32) -> Self {
		Self { value, velocity: 0.0, time: time.max(1e-4), max_speed: f32::INFINITY }
	}

	pub fn with_max_speed(mut self, max_speed: f32) -> Self {
		self.max_speed = max_speed;
		self
	}

	/// Move towards `target` by `dt` seconds and return the new value.
	pub fn update(&mut self, target: f32, dt: f32) -> f32 {
		if dt <= 0.0 {
			return self.value;
		}
		let omega = 2.0 / self.time;
		let x = omega * dt;
		let decay = 1.0 / (1.0 + x + 0.48 * x * x + 0.235 * x * x * x);
		let max_change = self.max_speed * self.time;
		let change = (self.value - target).clamp(-max_change, max_change);
		let goal = self.value - change;
		let temp = (self.velocity + omega * change) * dt;
		self.velocity = (self.velocity - omega * temp) * decay;
		let mut out = goal + (change + temp) * decay;
		// Never pass the target.
		if (target - self.value > 0.0) == (out > target) {
			out = target;
			self.velocity = 0.0;
		}
		self.value = out;
		out
	}
}

// Not used by the stage yet: it is for noisy inputs, such as recorded or
// tracked motion (docs/24-motion.md).
#[allow(dead_code)]
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct OneEuro {
	/// Cut-off at rest, in hertz: lower removes more jitter from slow motion.
	pub min_cutoff: f32,
	/// How fast the cut-off rises with speed: higher removes more lag from fast motion.
	pub beta: f32,
	/// Cut-off for the speed estimate, in hertz.
	pub d_cutoff: f32,
	last: Option<f32>,
	speed: f32,
}

#[allow(dead_code)]
fn alpha(cutoff: f32, dt: f32) -> f32 {
	let tau = 1.0 / (TAU * cutoff);
	1.0 / (1.0 + tau / dt)
}

#[allow(dead_code)]
impl OneEuro {
	pub fn new(min_cutoff: f32, beta: f32) -> Self {
		Self { min_cutoff, beta, d_cutoff: 1.0, last: None, speed: 0.0 }
	}

	pub fn update(&mut self, x: f32, dt: f32) -> f32 {
		let Some(last) = self.last else {
			self.last = Some(x);
			return x;
		};
		if dt <= 0.0 {
			return last;
		}
		let speed = (x - last) / dt;
		self.speed += alpha(self.d_cutoff, dt) * (speed - self.speed);
		let cutoff = self.min_cutoff + self.beta * self.speed.abs();
		let out = last + alpha(cutoff, dt) * (x - last);
		self.last = Some(out);
		out
	}
}

#[cfg(test)]
mod tests {
	use super::*;

	const DT: f32 = 1.0 / 60.0;

	#[test]
	fn a_spring_settles_without_overshoot_in_about_its_time() {
		let mut s = Spring::new(0.0, 0.3);
		let mut values = Vec::new();
		for _ in 0..120 {
			values.push(s.update(1.0, DT));
		}
		assert!(values.iter().all(|v| *v <= 1.0 + 1e-6), "never past the target");
		assert!(values.windows(2).all(|w| w[1] >= w[0] - 1e-6), "never turns back");
		let at = |seconds: f32| values[(seconds / DT) as usize - 1];
		assert!(at(0.05) < 0.1, "starts gently: {}", at(0.05));
		assert!(at(0.3) > 0.5 && at(0.3) < 0.9, "most of the way in its time: {}", at(0.3));
		assert!(at(1.0) > 0.98 && at(1.9) > 0.999, "settles: {} {}", at(1.0), at(1.9));
	}

	#[test]
	fn a_spring_is_steady_at_any_frame_time() {
		let mut fine = Spring::new(0.0, 0.2);
		let mut coarse = Spring::new(0.0, 0.2);
		for _ in 0..60 {
			fine.update(1.0, 1.0 / 120.0);
		}
		for _ in 0..5 {
			coarse.update(1.0, 0.1);
		}
		assert!((fine.value - coarse.value).abs() < 0.03, "{} {}", fine.value, coarse.value);
	}

	#[test]
	fn a_spring_respects_its_speed_limit() {
		let mut s = Spring::new(0.0, 0.05).with_max_speed(2.0);
		let mut last = 0.0;
		for _ in 0..30 {
			let v = s.update(10.0, DT);
			assert!((v - last) / DT <= 2.0 * 1.05, "{}", (v - last) / DT);
			last = v;
		}
	}

	#[test]
	fn one_euro_smooths_jitter_but_follows_fast_moves() {
		// Jitter of +-0.05 around 0.5: the output wanders much less.
		let mut f = OneEuro::new(1.0, 5.0);
		let mut spread: f32 = 0.0;
		for i in 0..300 {
			let noisy = 0.5 + if i % 2 == 0 { 0.05 } else { -0.05 };
			let v = f.update(noisy, DT);
			if i > 60 {
				spread = spread.max((v - 0.5).abs());
			}
		}
		assert!(spread < 0.02, "{spread}");
		// A quick jump of 0.5 is followed within a tenth of a second.
		let mut g = OneEuro::new(1.0, 5.0);
		for _ in 0..30 {
			g.update(0.0, DT);
		}
		let mut v = 0.0;
		for _ in 0..6 {
			v = g.update(0.5, DT);
		}
		assert!(v > 0.35, "{v}");
	}
}
