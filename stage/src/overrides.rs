//! Direct control of named puppet parameters, on top of the built-in
//! behaviour. Used for expressions (blush, a smile) and by preview tools.
//!
//! An override eases in, holds its value, and eases out when cleared. While
//! it is present it replaces whatever the behaviour would have set.

use std::collections::HashMap;

use glam::Vec2;

use crate::puppet_info::ParamInfo;

struct Entry {
	value: Vec2,
	target: Vec2,
	weight: f32,
	leaving: bool,
	ease: f32,
}

pub struct Overrides {
	limits: HashMap<String, ([f32; 2], [f32; 2], [f32; 2])>,
	entries: HashMap<String, Entry>,
}

impl Overrides {
	pub fn new(params: &[ParamInfo]) -> Self {
		let limits = params.iter().map(|p| (p.name.clone(), (p.min, p.max, p.defaults))).collect();
		Self { limits, entries: HashMap::new() }
	}

	/// Set a parameter. Returns false if the puppet has no such parameter.
	pub fn set(&mut self, name: &str, value: [f32; 2], ease: f32) -> bool {
		let Some((min, max, defaults)) = self.limits.get(name) else {
			return false;
		};
		let target = Vec2::new(value[0].clamp(min[0], max[0]), value[1].clamp(min[1], max[1]));
		let ease = ease.max(0.0);
		match self.entries.get_mut(name) {
			Some(e) => {
				e.target = target;
				e.leaving = false;
				e.ease = ease;
			}
			None => {
				// Start from the target so that only the weight eases in.
				let _ = defaults;
				self.entries.insert(name.to_string(), Entry { value: target, target, weight: 0.0, leaving: false, ease });
			}
		}
		true
	}

	/// Let a parameter return to what the behaviour gives it.
	pub fn clear(&mut self, name: &str, ease: f32) {
		if let Some(e) = self.entries.get_mut(name) {
			e.leaving = true;
			e.ease = ease.max(0.0);
		}
	}

	pub fn clear_all(&mut self, ease: f32) {
		for e in self.entries.values_mut() {
			e.leaving = true;
			e.ease = ease.max(0.0);
		}
	}

	#[cfg(test)]
	pub fn is_empty(&self) -> bool {
		self.entries.is_empty()
	}

	/// Advance by `dt` and merge into the values the behaviour produced.
	pub fn apply(&mut self, dt: f32, values: &mut Vec<(String, Vec2)>) {
		if self.entries.is_empty() {
			return;
		}
		for e in self.entries.values_mut() {
			let step = if e.ease <= 0.0 { 1.0 } else { (dt / e.ease).min(1.0) };
			e.weight = if e.leaving { (e.weight - step).max(0.0) } else { (e.weight + step).min(1.0) };
			e.value += (e.target - e.value) * if e.ease <= 0.0 { 1.0 } else { (dt / (e.ease * 0.5)).min(1.0) };
		}
		self.entries.retain(|_, e| !(e.leaving && e.weight <= 0.0));
		for (name, e) in &self.entries {
			let w = e.weight * e.weight * (3.0 - 2.0 * e.weight);
			match values.iter_mut().find(|(n, _)| n == name) {
				Some((_, v)) => *v += (e.value - *v) * w,
				None => {
					let d = self.limits.get(name).map(|l| Vec2::new(l.2[0], l.2[1])).unwrap_or(Vec2::ZERO);
					values.push((name.clone(), d + (e.value - d) * w));
				}
			}
		}
	}
}

#[cfg(test)]
mod tests {
	use super::*;

	fn params() -> Vec<ParamInfo> {
		vec![
			ParamInfo { name: "Cheek".into(), is_vec2: false, min: [0.0, 0.0], max: [1.0, 0.0], defaults: [0.0, 0.0] },
			ParamInfo { name: "Angle".into(), is_vec2: false, min: [-30.0, 0.0], max: [30.0, 0.0], defaults: [0.0, 0.0] },
		]
	}

	fn value(values: &[(String, Vec2)], name: &str) -> Option<f32> {
		values.iter().find(|(n, _)| n == name).map(|(_, v)| v.x)
	}

	#[test]
	fn unknown_parameters_are_refused() {
		let mut o = Overrides::new(&params());
		assert!(!o.set("Nose", [1.0, 0.0], 0.0));
		assert!(o.is_empty());
	}

	#[test]
	fn a_set_value_is_applied_at_once_without_easing_and_clamped() {
		let mut o = Overrides::new(&params());
		assert!(o.set("Angle", [90.0, 0.0], 0.0));
		let mut values = vec![("Angle".to_string(), Vec2::new(-5.0, 0.0))];
		o.apply(0.016, &mut values);
		assert_eq!(value(&values, "Angle"), Some(30.0));
	}

	#[test]
	fn an_unmapped_parameter_is_added_and_eases_in_from_its_default() {
		let mut o = Overrides::new(&params());
		o.set("Cheek", [1.0, 0.0], 0.4);
		let mut seen = Vec::new();
		for _ in 0..30 {
			let mut values = Vec::new();
			o.apply(0.02, &mut values);
			seen.push(value(&values, "Cheek").unwrap());
		}
		assert!(seen[0] > 0.0 && seen[0] < 0.1, "starts gently: {}", seen[0]);
		assert!(seen.windows(2).all(|w| w[1] >= w[0]), "rises steadily");
		assert_eq!(*seen.last().unwrap(), 1.0);
	}

	#[test]
	fn clearing_returns_to_the_behaviour_value_and_forgets_the_override() {
		let mut o = Overrides::new(&params());
		o.set("Angle", [20.0, 0.0], 0.0);
		let mut values = vec![("Angle".to_string(), Vec2::new(4.0, 0.0))];
		o.apply(0.02, &mut values);
		assert_eq!(value(&values, "Angle"), Some(20.0));
		o.clear("Angle", 0.2);
		let mut last = 20.0;
		for _ in 0..20 {
			let mut values = vec![("Angle".to_string(), Vec2::new(4.0, 0.0))];
			o.apply(0.02, &mut values);
			let v = value(&values, "Angle").unwrap();
			assert!(v <= last + 1e-4);
			last = v;
		}
		assert_eq!(last, 4.0);
		assert!(o.is_empty());
	}
}
