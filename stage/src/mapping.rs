//! Connects the stage's fixed controls (mouth, blink, head, body, breath) to
//! whatever parameter names a particular puppet uses.

use std::collections::HashMap;

use glam::Vec2;
use serde_json::Value;

use crate::behaviour::Pose;
use crate::puppet_info::{ParamInfo, PuppetInfo};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum Control {
	MouthOpen,
	BlinkLeft,
	BlinkRight,
	HeadYaw,
	HeadPitch,
	HeadRoll,
	BodyYaw,
	BodyPitch,
	BodyRoll,
	Breath,
}

impl Control {
	pub const ALL: [Control; 10] = [
		Control::MouthOpen,
		Control::BlinkLeft,
		Control::BlinkRight,
		Control::HeadYaw,
		Control::HeadPitch,
		Control::HeadRoll,
		Control::BodyYaw,
		Control::BodyPitch,
		Control::BodyRoll,
		Control::Breath,
	];

	pub fn key(self) -> &'static str {
		match self {
			Control::MouthOpen => "mouth_open",
			Control::BlinkLeft => "blink_left",
			Control::BlinkRight => "blink_right",
			Control::HeadYaw => "head_yaw",
			Control::HeadPitch => "head_pitch",
			Control::HeadRoll => "head_roll",
			Control::BodyYaw => "body_yaw",
			Control::BodyPitch => "body_pitch",
			Control::BodyRoll => "body_roll",
			Control::Breath => "breath",
		}
	}

	/// Controls that run from -1 to 1; the rest run from 0 to 1.
	fn bipolar(self) -> bool {
		!matches!(self, Control::MouthOpen | Control::BlinkLeft | Control::BlinkRight | Control::Breath)
	}

	fn value(self, pose: &Pose) -> f32 {
		match self {
			Control::MouthOpen => pose.mouth_open,
			Control::BlinkLeft | Control::BlinkRight => pose.blink,
			Control::HeadYaw => pose.head_yaw,
			Control::HeadPitch => pose.head_pitch,
			Control::HeadRoll => pose.head_roll,
			Control::BodyYaw => pose.body_yaw,
			Control::BodyPitch => pose.body_pitch,
			Control::BodyRoll => pose.body_roll,
			Control::Breath => pose.breath,
		}
	}

	/// Parameter names tried in order: (name, axis, inverted).
	/// The first group is the Inochi2D convention, the second the Live2D-style
	/// names some automatic riggers emit.
	fn candidates(self) -> &'static [(&'static str, usize, bool)] {
		match self {
			Control::MouthOpen => &[("Mouth:: Shape", 1, false), ("Mouth:: Open", 0, false), ("ParamMouthOpenY", 0, false)],
			Control::BlinkLeft => &[("Eye:: Left:: Blink", 0, false), ("ParamEyeLOpen", 0, true)],
			Control::BlinkRight => &[("Eye:: Right:: Blink", 0, false), ("ParamEyeROpen", 0, true)],
			Control::HeadYaw => &[("Head:: Yaw-Pitch", 0, false), ("ParamAngleX", 0, false)],
			Control::HeadPitch => &[("Head:: Yaw-Pitch", 1, false), ("ParamAngleY", 0, false)],
			Control::HeadRoll => &[("Head:: Roll", 0, false), ("ParamAngleZ", 0, false)],
			Control::BodyYaw => &[("Body:: Yaw-Pitch", 0, false), ("ParamBodyAngleX", 0, false)],
			Control::BodyPitch => &[("Body:: Yaw-Pitch", 1, false), ("ParamBodyAngleY", 0, false)],
			Control::BodyRoll => &[("Body:: Roll", 0, false), ("ParamBodyAngleZ", 0, false)],
			Control::Breath => &[("Breath", 0, false), ("ParamBreath", 0, false)],
		}
	}
}

#[derive(Clone, Debug, PartialEq)]
pub struct Target {
	pub param: String,
	pub axis: usize,
	/// Parameter value when the control is at its lowest.
	pub lo: f32,
	/// Parameter value when the control is at its highest.
	pub hi: f32,
}

pub struct Mapper {
	targets: Vec<(Control, Target)>,
	values: HashMap<String, [f32; 2]>,
}

fn find<'a>(info: &'a PuppetInfo, name: &str) -> Option<&'a ParamInfo> {
	info.params.iter().find(|p| p.name.eq_ignore_ascii_case(name))
}

impl Mapper {
	/// Map controls by recognising conventional parameter names.
	pub fn auto(info: &PuppetInfo) -> Self {
		let mut targets = Vec::new();
		for control in Control::ALL {
			for (name, axis, inverted) in control.candidates() {
				if let Some(p) = find(info, name) {
					let (lo, hi) = if *inverted { (p.max[*axis], p.min[*axis]) } else { (p.min[*axis], p.max[*axis]) };
					targets.push((control, Target { param: p.name.clone(), axis: *axis, lo, hi }));
					break;
				}
			}
		}
		Self::from_targets(info, targets)
	}

	fn from_targets(info: &PuppetInfo, targets: Vec<(Control, Target)>) -> Self {
		let mut values = HashMap::new();
		for (_, t) in &targets {
			let defaults = find(info, &t.param).map(|p| p.defaults).unwrap_or([0.0, 0.0]);
			values.insert(t.param.clone(), defaults);
		}
		Self { targets, values }
	}

	/// Apply a mapping file on top of the automatic mapping. Format:
	/// `{"mouth_open": {"param": "Name", "axis": "y", "min": 0, "max": 1, "invert": false}, ...}`.
	/// A control set to `null` is switched off.
	pub fn with_overrides(info: &PuppetInfo, overrides: &Value) -> Result<Self, String> {
		let mut targets = Self::auto(info).targets;
		let Some(map) = overrides.as_object() else {
			return Err("mapping file must be a JSON object".into());
		};
		for (key, spec) in map {
			let Some(control) = Control::ALL.into_iter().find(|c| c.key() == key) else {
				return Err(format!("unknown control '{key}' in mapping file"));
			};
			targets.retain(|(c, _)| *c != control);
			if spec.is_null() {
				continue;
			}
			let name = spec.get("param").and_then(Value::as_str).ok_or(format!("'{key}' needs a \"param\" name"))?;
			let p = find(info, name).ok_or(format!("puppet has no parameter named '{name}'"))?;
			let axis = match spec.get("axis").and_then(Value::as_str).unwrap_or("x") {
				"x" => 0,
				"y" => 1,
				other => return Err(format!("axis must be \"x\" or \"y\", not '{other}'")),
			};
			let mut lo = spec.get("min").and_then(Value::as_f64).map(|v| v as f32).unwrap_or(p.min[axis]);
			let mut hi = spec.get("max").and_then(Value::as_f64).map(|v| v as f32).unwrap_or(p.max[axis]);
			if spec.get("invert").and_then(Value::as_bool).unwrap_or(false) {
				std::mem::swap(&mut lo, &mut hi);
			}
			targets.push((control, Target { param: p.name.clone(), axis, lo, hi }));
		}
		Ok(Self::from_targets(info, targets))
	}

	pub fn targets(&self) -> &[(Control, Target)] {
		&self.targets
	}

	/// Compute parameter values for a pose. Returns (parameter name, value).
	pub fn resolve(&mut self, pose: &Pose) -> Vec<(String, Vec2)> {
		for (control, t) in &self.targets {
			let v = control.value(pose);
			let u = if control.bipolar() { (v + 1.0) * 0.5 } else { v }.clamp(0.0, 1.0);
			if let Some(slot) = self.values.get_mut(&t.param) {
				slot[t.axis] = t.lo + u * (t.hi - t.lo);
			}
		}
		let mut out: Vec<(String, Vec2)> = self
			.values
			.iter()
			.map(|(name, v)| (name.clone(), Vec2::new(v[0], v[1])))
			.collect();
		out.sort_by(|a, b| a.0.cmp(&b.0));
		out
	}
}

#[cfg(test)]
mod tests {
	use super::*;

	fn param(name: &str, is_vec2: bool, min: [f32; 2], max: [f32; 2], defaults: [f32; 2]) -> ParamInfo {
		ParamInfo { name: name.into(), is_vec2, min, max, defaults }
	}

	fn inochi() -> PuppetInfo {
		PuppetInfo {
			params: vec![
				param("Mouth:: Shape", true, [0.0, 0.0], [1.0, 1.0], [1.0, 1.0]),
				param("Eye:: Left:: Blink", false, [0.0, 0.0], [1.0, 1.0], [0.0, 0.0]),
				param("Head:: Yaw-Pitch", true, [-1.0, -1.0], [1.0, 1.0], [0.0, 0.0]),
				param("Breath", false, [0.0, 0.0], [1.0, 1.0], [0.0, 0.0]),
			],
			..Default::default()
		}
	}

	fn value(out: &[(String, Vec2)], name: &str) -> Vec2 {
		out.iter().find(|(n, _)| n == name).unwrap().1
	}

	#[test]
	fn maps_inochi_names_and_keeps_the_other_axis_at_its_default() {
		let mut m = Mapper::auto(&inochi());
		let out = m.resolve(&Pose { mouth_open: 0.25, head_yaw: -1.0, head_pitch: 0.5, ..Default::default() });
		// x of Mouth:: Shape is not driven, so it stays at the default 1.0
		assert_eq!(value(&out, "Mouth:: Shape"), Vec2::new(1.0, 0.25));
		assert_eq!(value(&out, "Head:: Yaw-Pitch"), Vec2::new(-1.0, 0.5));
		assert!(m.targets().iter().all(|(c, _)| *c != Control::BlinkRight));
	}

	#[test]
	fn live2d_style_eye_open_is_inverted_and_angles_use_the_file_range() {
		let info = PuppetInfo {
			params: vec![
				param("ParamEyeLOpen", false, [0.0, 0.0], [1.0, 0.0], [1.0, 0.0]),
				param("ParamAngleX", false, [-30.0, 0.0], [30.0, 0.0], [0.0, 0.0]),
			],
			..Default::default()
		};
		let mut m = Mapper::auto(&info);
		let out = m.resolve(&Pose { blink: 1.0, head_yaw: 0.5, ..Default::default() });
		assert_eq!(value(&out, "ParamEyeLOpen").x, 0.0); // closed
		assert_eq!(value(&out, "ParamAngleX").x, 15.0);
	}

	#[test]
	fn overrides_replace_disable_and_validate() {
		let info = inochi();
		let spec: Value = serde_json::from_str(
			r#"{"mouth_open": {"param": "Breath", "axis": "x", "invert": true}, "head_yaw": null}"#,
		)
		.unwrap();
		let mut m = Mapper::with_overrides(&info, &spec).unwrap();
		assert!(m.targets().iter().all(|(c, _)| *c != Control::HeadYaw));
		let out = m.resolve(&Pose { mouth_open: 1.0, breath: 0.0, ..Default::default() });
		// Breath is driven by two controls here; the later one (mouth, inverted) wins: 1 -> 0
		assert_eq!(value(&out, "Breath").x, 0.0);
		let bad: Value = serde_json::from_str(r#"{"mouth_open": {"param": "Nope"}}"#).unwrap();
		assert!(Mapper::with_overrides(&info, &bad).is_err());
		let unknown: Value = serde_json::from_str(r#"{"tail": null}"#).unwrap();
		assert!(Mapper::with_overrides(&info, &unknown).is_err());
	}
}
