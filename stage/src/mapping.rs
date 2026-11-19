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
	GazeX,
	GazeY,
	BrowLeft,
	BrowRight,
	Smile,
	ArmLeft,
	ArmRight,
	ArmLeftB,
	ArmRightB,
	Shoulders,
	EyeSmileLeft,
	EyeSmileRight,
	Cheek,
	BrowFormLeft,
	BrowFormRight,
	VowelA,
	VowelI,
	VowelU,
	VowelE,
	VowelO,
}

impl Control {
	pub const ALL: [Control; 30] = [
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
		Control::GazeX,
		Control::GazeY,
		Control::BrowLeft,
		Control::BrowRight,
		Control::Smile,
		Control::ArmLeft,
		Control::ArmRight,
		Control::ArmLeftB,
		Control::ArmRightB,
		Control::Shoulders,
		Control::EyeSmileLeft,
		Control::EyeSmileRight,
		Control::Cheek,
		Control::BrowFormLeft,
		Control::BrowFormRight,
		Control::VowelA,
		Control::VowelI,
		Control::VowelU,
		Control::VowelE,
		Control::VowelO,
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
			Control::GazeX => "gaze_x",
			Control::GazeY => "gaze_y",
			Control::BrowLeft => "brow_left",
			Control::BrowRight => "brow_right",
			Control::Smile => "smile",
			Control::ArmLeft => "arm_left",
			Control::ArmRight => "arm_right",
			Control::ArmLeftB => "arm_left_b",
			Control::ArmRightB => "arm_right_b",
			Control::Shoulders => "shoulders",
			Control::EyeSmileLeft => "eye_smile_left",
			Control::EyeSmileRight => "eye_smile_right",
			Control::Cheek => "cheek",
			Control::BrowFormLeft => "brow_form_left",
			Control::BrowFormRight => "brow_form_right",
			Control::VowelA => "vowel_a",
			Control::VowelI => "vowel_i",
			Control::VowelU => "vowel_u",
			Control::VowelE => "vowel_e",
			Control::VowelO => "vowel_o",
		}
	}

	/// The pose field the control reads (motion clips are written in these).
	pub fn pose_key(self) -> &'static str {
		match self {
			Control::MouthOpen => "mouth_open",
			Control::BlinkLeft | Control::BlinkRight => "blink",
			Control::BrowLeft | Control::BrowRight => "brows",
			Control::EyeSmileLeft | Control::EyeSmileRight => "eye_smile",
			Control::BrowFormLeft | Control::BrowFormRight => "brow_form",
			other => other.key(),
		}
	}

	/// Controls that run from -1 to 1, with 0 at the parameter's default; the
	/// rest run from 0 to 1 across the parameter's range.
	fn bipolar(self) -> bool {
		!matches!(
			self,
			Control::MouthOpen
				| Control::BlinkLeft
				| Control::BlinkRight
				| Control::Breath
				| Control::EyeSmileLeft
				| Control::EyeSmileRight
				| Control::Cheek
				| Control::VowelA
				| Control::VowelI
				| Control::VowelU
				| Control::VowelE
				| Control::VowelO
		)
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
			Control::GazeX => pose.gaze_x,
			Control::GazeY => pose.gaze_y,
			Control::BrowLeft | Control::BrowRight => pose.brows,
			Control::Smile => pose.smile,
			Control::ArmLeft => pose.arm_left,
			Control::ArmRight => pose.arm_right,
			Control::ArmLeftB => pose.arm_left_b,
			Control::ArmRightB => pose.arm_right_b,
			Control::Shoulders => pose.shoulders,
			Control::EyeSmileLeft | Control::EyeSmileRight => pose.eye_smile,
			Control::Cheek => pose.cheek,
			Control::BrowFormLeft | Control::BrowFormRight => pose.brow_form,
			Control::VowelA => pose.vowel_a,
			Control::VowelI => pose.vowel_i,
			Control::VowelU => pose.vowel_u,
			Control::VowelE => pose.vowel_e,
			Control::VowelO => pose.vowel_o,
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
			// Live2D's standard parameter names (docs/24-motion.md).
			Control::GazeX => &[("ParamEyeBallX", 0, false)],
			Control::GazeY => &[("ParamEyeBallY", 0, false)],
			Control::BrowLeft => &[("ParamBrowLY", 0, false)],
			Control::BrowRight => &[("ParamBrowRY", 0, false)],
			Control::Smile => &[("ParamMouthForm", 0, false)],
			Control::ArmLeft => &[("ParamArmLA", 0, false)],
			Control::ArmRight => &[("ParamArmRA", 0, false)],
			Control::ArmLeftB => &[("ParamArmLB", 0, false)],
			Control::ArmRightB => &[("ParamArmRB", 0, false)],
			Control::Shoulders => &[("ParamShoulderY", 0, false)],
			Control::EyeSmileLeft => &[("ParamEyeLSmile", 0, false)],
			Control::EyeSmileRight => &[("ParamEyeRSmile", 0, false)],
			Control::Cheek => &[("ParamCheek", 0, false)],
			Control::BrowFormLeft => &[("ParamBrowLForm", 0, false)],
			Control::BrowFormRight => &[("ParamBrowRForm", 0, false)],
			// Models made for lip sync by vowel often have one parameter for each.
			Control::VowelA => &[("ParamA", 0, false), ("ParamMouthA", 0, false)],
			Control::VowelI => &[("ParamI", 0, false), ("ParamMouthI", 0, false)],
			Control::VowelU => &[("ParamU", 0, false), ("ParamMouthU", 0, false)],
			Control::VowelE => &[("ParamE", 0, false), ("ParamMouthE", 0, false)],
			Control::VowelO => &[("ParamO", 0, false), ("ParamMouthO", 0, false)],
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
	/// Parameter value when a control that runs from -1 to 1 is at 0: the
	/// parameter's default, so a model whose neutral pose is not the middle
	/// of its range still rests in it.
	pub mid: f32,
}

impl Target {
	fn value(&self, u: f32, bipolar: bool) -> f32 {
		if !bipolar {
			return self.lo + u.clamp(0.0, 1.0) * (self.hi - self.lo);
		}
		let u = u.clamp(-1.0, 1.0);
		if u >= 0.0 {
			self.mid + u * (self.hi - self.mid)
		} else {
			self.mid - u * (self.lo - self.mid)
		}
	}
}

/// The default, kept inside the range (some files carry a default outside it).
fn neutral(p: &ParamInfo, axis: usize, lo: f32, hi: f32) -> f32 {
	p.defaults[axis].clamp(lo.min(hi), lo.max(hi))
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
					let mid = neutral(p, *axis, lo, hi);
					targets.push((control, Target { param: p.name.clone(), axis: *axis, lo, hi, mid }));
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
	/// `{"mouth_open": {"param": "Name", "axis": "y", "min": 0, "max": 1, "invert": false}, ...}`;
	/// controls that run from -1 to 1 also take `"rest"`, the value at 0
	/// (default: the parameter's default).
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
			let mid = match spec.get("rest").and_then(Value::as_f64) {
				Some(rest) => rest as f32,
				None => neutral(p, axis, lo, hi),
			};
			targets.push((control, Target { param: p.name.clone(), axis, lo, hi, mid }));
		}
		Ok(Self::from_targets(info, targets))
	}

	pub fn targets(&self) -> &[(Control, Target)] {
		&self.targets
	}

	/// Does a pose field reach one of the character's parameters?
	pub fn drives(&self, pose_key: &str) -> bool {
		self.targets.iter().any(|(c, _)| c.pose_key() == pose_key)
	}

	/// Compute parameter values for a pose. Returns (parameter name, value).
	pub fn resolve(&mut self, pose: &Pose) -> Vec<(String, Vec2)> {
		for (control, t) in &self.targets {
			let v = t.value(control.value(pose), control.bipolar());
			if let Some(slot) = self.values.get_mut(&t.param) {
				slot[t.axis] = v;
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
	fn standard_controls_rest_at_the_parameter_default() {
		let info = PuppetInfo {
			params: vec![
				param("ParamEyeBallX", false, [-1.0, 0.0], [1.0, 0.0], [0.0, 0.0]),
				param("ParamArmLA", false, [-30.0, 0.0], [30.0, 0.0], [0.0, 0.0]),
				// A model whose neutral mouth is not the middle of its range.
				param("ParamMouthForm", false, [-1.0, 0.0], [2.0, 0.0], [1.0, 0.0]),
				param("ParamShoulderY", false, [-10.0, 0.0], [10.0, 0.0], [0.0, 0.0]),
			],
			..Default::default()
		};
		let mut m = Mapper::auto(&info);
		let rest = m.resolve(&Pose::default());
		assert_eq!(value(&rest, "ParamMouthForm").x, 1.0, "at rest, the model's own neutral shape");
		assert_eq!(value(&rest, "ParamShoulderY").x, 0.0);
		let out = m.resolve(&Pose { gaze_x: 0.5, arm_left: -0.5, smile: 1.0, ..Default::default() });
		assert_eq!(value(&out, "ParamEyeBallX").x, 0.5);
		assert_eq!(value(&out, "ParamArmLA").x, -15.0);
		assert_eq!(value(&out, "ParamMouthForm").x, 2.0);
		let down = m.resolve(&Pose { smile: -0.5, ..Default::default() });
		assert_eq!(value(&down, "ParamMouthForm").x, 0.0, "halfway from neutral to the lowest value");
	}

	#[test]
	fn a_model_with_a_parameter_for_each_vowel_has_them_driven() {
		let info = PuppetInfo {
			params: ["ParamA", "ParamI", "ParamU", "ParamE", "ParamO", "ParamMouthOpenY"]
				.iter()
				.map(|n| param(n, false, [0.0, 0.0], [1.0, 0.0], [0.0, 0.0]))
				.collect(),
			..Default::default()
		};
		let mut m = Mapper::auto(&info);
		let out = m.resolve(&Pose { vowel_o: 0.7, mouth_open: 0.6, ..Default::default() });
		assert_eq!(value(&out, "ParamO").x, 0.7);
		assert_eq!(value(&out, "ParamA").x, 0.0);
		assert_eq!(value(&out, "ParamMouthOpenY").x, 0.6, "the mouth's opening is driven as well");
	}

	#[test]
	fn the_elbows_have_their_own_controls() {
		let info = PuppetInfo {
			params: vec![
				param("ParamArmRA", false, [-10.0, 0.0], [10.0, 0.0], [0.0, 0.0]),
				param("ParamArmRB", false, [-10.0, 0.0], [10.0, 0.0], [0.0, 0.0]),
			],
			..Default::default()
		};
		let mut m = Mapper::auto(&info);
		// A wave as the studio's characters hold it: the arm at 0.5, the forearm up at 0.85.
		let out = m.resolve(&Pose { arm_right: 0.5, arm_right_b: 0.85, ..Default::default() });
		assert_eq!(value(&out, "ParamArmRA").x, 5.0);
		assert!((value(&out, "ParamArmRB").x - 8.5).abs() < 1e-5);
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
