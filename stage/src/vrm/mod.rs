//! VRM avatars (3D humanoid characters, `.vrm`): loaded, posed from the stage's controls and drawn
//! with OpenGL ES 3, beside the 2D formats (docs/30-vrm.md).
//!
//! A VRM avatar offers the stage the same parameter names a Live2D-format model does (ParamAngleX,
//! ParamEyeLOpen, ParamArmLA and the rest), plus one per expression ("Expr:happy"), so the whole
//! animation system - moods, gestures, idle life, speech, the movement settings page - drives it
//! unchanged. Underneath, those become bone turns on the avatar's humanoid skeleton and expression
//! weights.

pub mod anim;
pub mod gltf;
pub mod model;
pub mod render;
pub mod rig;
pub mod spring;

use std::path::Path;

use glam::{Quat, Vec2, Vec3};
use serde_json::{json, Value};

use crate::live2d::{Blend, Expression as StageExpression};
use crate::puppet_info::{ParamInfo, PuppetInfo};
use anim::{Animator, Scene};
use gltf::Glb;
use model::{AlphaMode, ColorKind, Model, Override};
use rig::{normalised_pose, Controls, Rig};
use spring::Springs;

/// Files larger than this are refused before reading (the stage reads the file itself first, to
/// tell the formats apart, and checks the same limit there).
#[cfg_attr(not(test), allow(dead_code))]
pub const MAX_FILE_BYTES: u64 = 256 << 20;

/// How much memory the device has for pictures: the largest texture side kept.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Profile {
	/// 1 GB boards: textures up to 1024 pixels a side.
	L1,
	/// 2 GB and more: up to 2048.
	L2,
}

impl Profile {
	pub fn texture_side(self) -> u32 {
		match self {
			Profile::L1 => 1024,
			Profile::L2 => 2048,
		}
	}

	/// L2 on a computer with 1.5 GB or more, L1 below that (or if it cannot be told).
	pub fn auto() -> Profile {
		let total_kb = std::fs::read_to_string("/proc/meminfo")
			.ok()
			.and_then(|m| m.lines().find(|l| l.starts_with("MemTotal:")).and_then(|l| l.split_whitespace().nth(1)?.parse::<u64>().ok()))
			.unwrap_or(0);
		if total_kb >= 1_500_000 {
			Profile::L2
		} else {
			Profile::L1
		}
	}
}

/// Does this file look like a VRM avatar?
pub fn looks_like_vrm(bytes: &[u8]) -> bool {
	if !gltf::is_glb(bytes) {
		return false;
	}
	let len = u32::from_le_bytes([bytes[12], bytes[13], bytes[14], bytes[15]]) as usize;
	let json = &bytes[20..(20 + len).min(bytes.len())];
	json.windows(10).any(|w| w == b"\"VRMC_vrm\"") || json.windows(5).any(|w| w == b"\"VRM\"")
}

/// The parameters a VRM avatar offers, as Live2D names them: (name, min, max, default).
const PARAMS: [(&str, f32, f32, f32); 30] = [
	("ParamAngleX", -30.0, 30.0, 0.0),
	("ParamAngleY", -30.0, 30.0, 0.0),
	("ParamAngleZ", -30.0, 30.0, 0.0),
	("ParamBodyAngleX", -10.0, 10.0, 0.0),
	("ParamBodyAngleY", -10.0, 10.0, 0.0),
	("ParamBodyAngleZ", -10.0, 10.0, 0.0),
	("ParamBreath", 0.0, 1.0, 0.0),
	("ParamEyeBallX", -1.0, 1.0, 0.0),
	("ParamEyeBallY", -1.0, 1.0, 0.0),
	("ParamEyeLOpen", 0.0, 1.0, 1.0),
	("ParamEyeROpen", 0.0, 1.0, 1.0),
	("ParamEyeLSmile", 0.0, 1.0, 0.0),
	("ParamEyeRSmile", 0.0, 1.0, 0.0),
	("ParamMouthOpenY", 0.0, 1.0, 0.0),
	("ParamMouthForm", -1.0, 1.0, 0.0),
	("ParamA", 0.0, 1.0, 0.0),
	("ParamI", 0.0, 1.0, 0.0),
	("ParamU", 0.0, 1.0, 0.0),
	("ParamE", 0.0, 1.0, 0.0),
	("ParamO", 0.0, 1.0, 0.0),
	("ParamBrowLY", -1.0, 1.0, 0.0),
	("ParamBrowRY", -1.0, 1.0, 0.0),
	("ParamBrowLForm", -1.0, 1.0, 0.0),
	("ParamBrowRForm", -1.0, 1.0, 0.0),
	("ParamCheek", 0.0, 1.0, 0.0),
	("ParamArmLA", -10.0, 10.0, 0.0),
	("ParamArmRA", -10.0, 10.0, 0.0),
	("ParamArmLB", -10.0, 10.0, 0.0),
	("ParamArmRB", -10.0, 10.0, 0.0),
	("ParamShoulderY", -10.0, 10.0, 0.0),
];

/// Names of an expression's parameter.
pub const EXPRESSION_PREFIX: &str = "Expr:";

/// How strongly a mood shows when the owner's feelings map picks one of these (a full-strength
/// "happy" closes many avatars' eyes for as long as the mood lasts).
fn mood_strength(preset: Option<&str>) -> f32 {
	match preset {
		Some("happy") => 0.55,
		Some("angry") => 0.75,
		Some("sad") => 0.8,
		Some("surprised") => 0.65,
		_ => 1.0,
	}
}

/// Speech always shows: an expression may quieten the mouth, never silence it.
const MOUTH_OVERRIDE_CAP: f32 = 0.5;

/// Parts of a VRoid Studio face (the source of most avatars) the device uses for smiles and brows.
#[derive(Default, Debug)]
struct Face {
	smile: Vec<(usize, usize)>,
	frown: Vec<(usize, usize)>,
	eye_smile: [Vec<(usize, usize)>; 2],
	brow_up: Vec<(usize, usize)>,
	brow_down: Vec<(usize, usize)>,
	brow_sad: Vec<(usize, usize)>,
	cheek: Option<usize>,
	cheek_morphs: Vec<(usize, usize)>,
}

pub struct VrmPuppet {
	pub info: PuppetInfo,
	pub expressions: Vec<StageExpression>,
	pub warnings: Vec<String>,
	pub model: Model,
	pub rig: Rig,
	springs: Option<Springs>,
	/// The file, kept until the textures are on the graphics chip.
	glb: Option<Glb>,
	pub profile: Profile,
	face: Face,
	/// Expression weights this frame.
	pub weights: Vec<f32>,
	/// Morph target weights per mesh, and whether they changed since they were last drawn.
	pub morphs: Vec<Vec<f32>>,
	pub morph_dirty: Vec<bool>,
	/// Material colours and texture placement this frame (expressions can change them).
	pub material_colors: Vec<[[f32; 4]; 5]>,
	pub material_uv: Vec<(Vec2, Vec2)>,
	/// Where the avatar's head and hips are at rest, for framing it.
	pub framing: Framing,
	/// Its points (each shared set once) and triangles, counted when it was read.
	pub size: (usize, usize),
	/// Full-body animation (clips on the whole skeleton), when the avatar is set to it.
	animator: Option<Animator>,
	/// The springs move every this many frames (2 at half rate, to save time), and the time since.
	pub spring_every: u32,
	spring_wait: u32,
	spring_dt: f32,
	/// The largest texture side drawn (the profile's, or 512 when the drawing is kept light).
	pub texture_side: u32,
	/// What the character is doing, for the animation.
	scene: Scene,
}

/// Points of the avatar at rest, in metres, for the camera.
#[derive(Clone, Copy, Debug, Default)]
pub struct Framing {
	pub top: f32,
	pub neck: f32,
	pub chest: f32,
	pub hips: f32,
	pub knees: f32,
	pub feet: f32,
	pub half_width: f32,
}

impl VrmPuppet {
	#[cfg_attr(not(test), allow(dead_code))]
	pub fn load(path: &Path, profile: Profile) -> Result<VrmPuppet, String> {
		let size = std::fs::metadata(path).map_err(|e| format!("cannot read {}: {e}", path.display()))?.len();
		if size > MAX_FILE_BYTES {
			return Err(format!("{} is too large ({size} bytes)", path.display()));
		}
		let bytes = std::fs::read(path).map_err(|e| format!("cannot read {}: {e}", path.display()))?;
		Self::from_bytes(bytes, profile)
	}

	pub fn from_bytes(bytes: Vec<u8>, profile: Profile) -> Result<VrmPuppet, String> {
		let glb = Glb::parse(bytes)?;
		let model = Model::read(&glb)?;
		let rig = Rig::new(&model);
		let mut params: Vec<ParamInfo> = PARAMS
			.iter()
			.map(|(name, min, max, default)| ParamInfo {
				name: name.to_string(),
				is_vec2: false,
				min: [*min, 0.0],
				max: [*max, 0.0],
				defaults: [*default, 0.0],
			})
			.collect();
		let mut expressions = Vec::new();
		for e in &model.expressions {
			let name = format!("{EXPRESSION_PREFIX}{}", e.name);
			params.push(ParamInfo { name: name.clone(), is_vec2: false, min: [0.0, 0.0], max: [1.0, 0.0], defaults: [0.0, 0.0] });
			expressions.push(StageExpression { name: e.name.clone(), params: vec![(name, 1.0, Blend::Add)] });
		}
		let info = PuppetInfo {
			name: Some(model.meta.name.clone()).filter(|n| !n.is_empty()),
			params,
			bounds: None,
			part_count: model.meshes.iter().map(|m| m.primitives.len()).sum(),
			node_types: Vec::new(),
			expressions: model.expressions.iter().map(|e| e.name.clone()).collect(),
		};
		let face = find_face(&model);
		let morphs: Vec<Vec<f32>> = model.meshes.iter().map(|m| vec![0.0; m.target_count()]).collect();
		let morph_dirty = vec![true; morphs.len()];
		let material_colors = model.materials.iter().map(base_colors).collect();
		let material_uv = vec![(Vec2::ONE, Vec2::ZERO); model.materials.len()];
		let warnings = model.warnings.clone();
		let mut puppet = VrmPuppet {
			info,
			expressions,
			warnings,
			weights: vec![0.0; model.expressions.len()],
			rig,
			springs: None,
			glb: Some(glb),
			profile,
			face,
			morphs,
			morph_dirty,
			material_colors,
			material_uv,
			framing: Framing::default(),
			size: (
				model.meshes.iter().map(|x| x.points.iter().map(|p| p.positions.len()).sum::<usize>()).sum(),
				model.meshes.iter().map(|x| x.primitives.iter().map(|p| p.indices.len() / 3).sum::<usize>()).sum(),
			),
			animator: None,
			spring_every: 1,
			spring_wait: 0,
			spring_dt: 0.0,
			texture_side: profile.texture_side(),
			scene: Scene::default(),
			model,
		};
		// Pose it at rest once, then let the hair and clothes settle from there.
		puppet.update(&[], 0.0);
		puppet.framing = puppet.measure();
		puppet.springs = Some(Springs::new(&puppet.model, &puppet.rig));
		for _ in 0..30 {
			puppet.update(&[], 1.0 / 30.0);
		}
		Ok(puppet)
	}

	/// No swinging hair or clothes (for comparisons).
	pub fn drop_physics(&mut self) {
		self.springs = None;
	}

	/// Keep the drawing light, for a slow or small device: small textures and springs at half rate (the
	/// renderer leaves out outlines too).
	pub fn lite(&mut self) {
		self.texture_side = self.texture_side.min(512);
		self.spring_every = 2;
	}

	/// The hips' height above the feet at rest, in metres.
	pub fn hips_height(&self) -> f32 {
		(self.framing.hips - self.framing.feet - 0.05).max(0.2)
	}

	/// Play these clips on the whole skeleton (the full-body style).
	pub fn animate(&mut self, clips: Vec<anim::Clip>) {
		self.animator = Some(Animator::new(clips, &self.model, self.hips_height()));
	}

	/// Add a clip to play (starting the full-body player for it if needed, to try a clip).
	pub fn add_clip(&mut self, clip: anim::Clip) {
		match &mut self.animator {
			Some(a) => a.add(clip, &self.model),
			None => self.animator = Some(Animator::new(vec![clip], &self.model, self.hips_height())),
		}
	}

	pub fn animator(&self) -> Option<&Animator> {
		self.animator.as_ref()
	}

	/// What the character is doing now, for the next frame's animation.
	pub fn set_scene(&mut self, scene: Scene) {
		self.scene = scene;
	}

	/// The file's bytes, while textures are still to be made from it.
	pub fn take_file(&mut self) -> Option<Glb> {
		self.glb.take()
	}

	pub fn features(&self) -> Value {
		let m = &self.model;
		json!({
			"vrm": if m.version == 1 { "1.0" } else { "0.x" },
			"bones": m.humanoid.iter().filter(|b| b.is_some()).count(),
			"nodes": m.nodes.len(),
			"meshes": m.meshes.len(),
			"materials": m.materials.len(),
			"morph_targets": m.meshes.iter().map(|x| x.points.iter().map(|p| p.targets.len()).sum::<usize>()).sum::<usize>(),
			"points": self.size.0,
			"triangles": self.size.1,
			"expressions": m.expressions.iter().map(|e| e.name.clone()).collect::<Vec<_>>(),
			"look_at": m.look_at.as_ref().map(|l| if l.bones { "bones" } else { "expressions" }),
			"spring_joints": self.springs.as_ref().map(|s| s.joint_count()).unwrap_or(0),
			"constraints": m.constraints.len(),
			"textures": m.texture_images.len(),
			"texture_side": self.profile.texture_side(),
			"meta": {"name": m.meta.name, "authors": m.meta.authors,
			         "licence": m.meta.fields.iter().map(|(k, v)| (k.clone(), json!(v))).collect::<serde_json::Map<String, Value>>()},
		})
	}

	/// Where the avatar's parts are at rest (relaxed arms), for framing.
	fn measure(&self) -> Framing {
		let m = &self.model;
		let at = |name: &str| m.bone(name).map(|n| self.rig.world_position(n));
		let head = at("head").unwrap_or(Vec3::new(0.0, 1.5, 0.0));
		let hips = at("hips").unwrap_or(Vec3::new(0.0, 0.9, 0.0));
		let neck = at("neck").map(|p| p.y).unwrap_or(head.y - 0.08);
		let chest = at("upperChest").or(at("chest")).map(|p| p.y).unwrap_or((neck + hips.y) * 0.5);
		let knees = match (at("leftLowerLeg"), at("rightLowerLeg")) {
			(Some(a), Some(b)) => (a.y + b.y) * 0.5,
			_ => hips.y * 0.5,
		};
		let feet = match (at("leftFoot"), at("rightFoot")) {
			(Some(a), Some(b)) => a.y.min(b.y) - 0.05,
			_ => 0.0,
		};
		// Half the width across the shoulders (the upper arms' starts).
		let half_width = ["leftUpperArm", "rightUpperArm"].iter().filter_map(|b| at(b)).map(|p| p.x.abs()).fold(0.12f32, f32::max);
		// The top of the head: the highest point of the meshes at rest.
		let mut top = head.y + 0.15;
		for (s, skin) in m.skins.iter().enumerate() {
			let _ = skin;
			for mesh_node in m.nodes.iter().filter(|n| n.skin == Some(s)) {
				let Some(mesh) = mesh_node.mesh.and_then(|i| m.meshes.get(i)) else { continue };
				for p in &mesh.points {
					for (k, pos) in p.positions.iter().enumerate().step_by(7) {
						let Some(w) = p.weights.get(k) else { continue };
						let j = p.joints[k];
						let mat = self.rig.skins[s].get(j[0] as usize).copied().unwrap_or_default() * w[0]
							+ self.rig.skins[s].get(j[1] as usize).copied().unwrap_or_default() * w[1]
							+ self.rig.skins[s].get(j[2] as usize).copied().unwrap_or_default() * w[2]
							+ self.rig.skins[s].get(j[3] as usize).copied().unwrap_or_default() * w[3];
						let q = mat.transform_point3(*pos);
						// Only near the head's middle: a raised accessory (a wing, a robot arm) is not the top.
						if q.is_finite() && q.x.abs() < (head.y - neck).abs() * 3.0 + 0.1 {
							top = top.max(q.y);
						}
					}
				}
			}
		}
		Framing { top, neck, chest, hips: hips.y, knees, feet, half_width }
	}

	/// Pose the avatar from the stage's parameter values, and move its hair and clothes on by `dt`.
	pub fn update(&mut self, values: &[(String, Vec2)], dt: f32) {
		let mut c = Controls::rest();
		let mut expr = vec![0.0f32; self.model.expressions.len()];
		for (name, v) in values {
			let x = v.x;
			match name.as_str() {
				"ParamAngleX" => c.head.x = x,
				"ParamAngleY" => c.head.y = x,
				"ParamAngleZ" => c.head.z = x,
				"ParamBodyAngleX" => c.body.x = x,
				"ParamBodyAngleY" => c.body.y = x,
				"ParamBodyAngleZ" => c.body.z = x,
				"ParamBreath" => c.breath = x,
				"ParamEyeBallX" => c.gaze.x = x,
				"ParamEyeBallY" => c.gaze.y = x,
				"ParamEyeLOpen" => c.eye_open[0] = x,
				"ParamEyeROpen" => c.eye_open[1] = x,
				"ParamEyeLSmile" => c.eye_smile[0] = x,
				"ParamEyeRSmile" => c.eye_smile[1] = x,
				"ParamMouthOpenY" => c.mouth_open = x,
				"ParamMouthForm" => c.mouth_form = x,
				"ParamA" => c.vowels[0] = x,
				"ParamI" => c.vowels[1] = x,
				"ParamU" => c.vowels[2] = x,
				"ParamE" => c.vowels[3] = x,
				"ParamO" => c.vowels[4] = x,
				"ParamBrowLY" => c.brows[0] = x,
				"ParamBrowRY" => c.brows[1] = x,
				"ParamBrowLForm" => c.brow_form[0] = x,
				"ParamBrowRForm" => c.brow_form[1] = x,
				"ParamCheek" => c.cheek = x,
				"ParamArmLA" => c.arm_a[0] = x / 10.0,
				"ParamArmRA" => c.arm_a[1] = x / 10.0,
				"ParamArmLB" => c.arm_b[0] = x / 10.0,
				"ParamArmRB" => c.arm_b[1] = x / 10.0,
				"ParamShoulderY" => c.shoulders = x / 10.0,
				other => {
					if let Some(e) = other.strip_prefix(EXPRESSION_PREFIX).and_then(|e| self.model.expression(e)) {
						expr[e] += x;
					}
				}
			}
		}
		let mut q = match &mut self.animator {
			Some(a) => {
				let q = a.pose(&self.model, &c, &self.scene, dt);
				for (e, w) in expr.iter_mut().zip(&a.expressions) {
					*e += w;
				}
				self.rig.hips_offset = a.hips_offset;
				q
			}
			None => normalised_pose(&self.model, &c),
		};
		let look_weights = self.look_at(&c, &mut q);
		self.rig.pose(&self.model, &q);
		self.rig.constrain(&self.model);
		if let Some(springs) = &mut self.springs {
			self.spring_dt += dt;
			self.spring_wait += 1;
			if self.spring_wait >= self.spring_every {
				springs.update(&self.model, &mut self.rig, self.spring_dt);
				self.spring_wait = 0;
				self.spring_dt = 0.0;
			} else {
				springs.hold(&self.model, &mut self.rig);
			}
		}
		self.rig.skin(&self.model);
		self.face(&c, &expr, look_weights);
	}

	/// Eyes: turn the eye bones, or say how much each look expression shows.
	fn look_at(&self, c: &Controls, q: &mut [Quat; 55]) -> [f32; 4] {
		let Some(l) = &self.model.look_at else {
			return [0.0; 4];
		};
		let yaw = c.gaze.x.clamp(-1.0, 1.0) * 25.0;
		let pitch = c.gaze.y.clamp(-1.0, 1.0) * 20.0;
		let vertical = if pitch >= 0.0 { l.vertical_up.map(pitch) } else { -l.vertical_down.map(pitch) };
		if l.bones {
			for (i, eye) in ["leftEye", "rightEye"].iter().enumerate() {
				// Towards +x is outwards for the left eye and inwards for the right.
				let outward = (yaw > 0.0) == (i == 0);
				let h = if outward { l.horizontal_outer.map(yaw) } else { l.horizontal_inner.map(yaw) } * yaw.signum();
				q[model::bone(eye)] = Quat::from_rotation_y(h.to_radians()) * Quat::from_rotation_x((-vertical).to_radians());
			}
			[0.0; 4]
		} else {
			let h = l.horizontal_outer.map(yaw);
			// (left, right, up, down): looking towards +x is the avatar looking to its left.
			[if yaw > 0.0 { h } else { 0.0 }, if yaw < 0.0 { h } else { 0.0 }, vertical.max(0.0), (-vertical).max(0.0)]
		}
	}

	/// Expression weights from the controls and the expression parameters, then morph weights
	/// and material changes from those.
	fn face(&mut self, c: &Controls, expr: &[f32], look: [f32; 4]) {
		let m = &self.model;
		let mut w: Vec<f32> = expr
			.iter()
			.zip(&m.expressions)
			.map(|(v, e)| v.clamp(0.0, 1.0) * mood_strength(e.preset))
			.collect();
		let find = |name: &str| m.expression(name);
		let add = |w: &mut Vec<f32>, e: Option<usize>, v: f32| {
			if let Some(i) = e {
				w[i] += v;
			}
		};
		// Blinking: each eye if the avatar can, else both together.
		let (bl, br) = ((1.0 - c.eye_open[0]).clamp(0.0, 1.0), (1.0 - c.eye_open[1]).clamp(0.0, 1.0));
		match (find("blinkLeft"), find("blinkRight"), find("blink")) {
			(Some(l), Some(r), _) => {
				add(&mut w, Some(l), bl);
				add(&mut w, Some(r), br);
			}
			(_, _, b) => add(&mut w, b, (bl + br) * 0.5),
		}
		// The mouth: vowel shapes while speaking, else open as wide as asked.
		let vowels = ["aa", "ih", "ou", "ee", "oh"];
		if c.vowels.iter().sum::<f32>() > 0.01 {
			for (v, name) in c.vowels.iter().zip(vowels) {
				add(&mut w, find(name).or(find("aa")), *v);
			}
		} else {
			add(&mut w, find("aa"), c.mouth_open);
		}
		// Eyes looking, by expression.
		for (v, name) in look.iter().zip(["lookLeft", "lookRight", "lookUp", "lookDown"]) {
			add(&mut w, find(name), *v);
		}
		// Smiles, brows and blushes: a VRoid face's own parts; otherwise a little of the moods.
		let mut direct: Vec<((usize, usize), f32)> = Vec::new();
		let f = &self.face;
		let smile = c.mouth_form.max(0.0);
		let frown = (-c.mouth_form).max(0.0);
		if !f.smile.is_empty() {
			direct.extend(f.smile.iter().map(|k| (*k, smile)));
			direct.extend(f.frown.iter().map(|k| (*k, frown)));
		} else {
			add(&mut w, find("relaxed").or(find("happy")), smile * 0.5);
			add(&mut w, find("sad"), frown * 0.3);
		}
		for (i, eye) in f.eye_smile.iter().enumerate() {
			direct.extend(eye.iter().map(|k| (*k, c.eye_smile[i])));
		}
		if f.eye_smile[0].is_empty() {
			add(&mut w, find("happy"), (c.eye_smile[0] + c.eye_smile[1]) * 0.15);
		}
		let brows = (c.brows[0] + c.brows[1]) * 0.5;
		let form = (c.brow_form[0] + c.brow_form[1]) * 0.5;
		direct.extend(f.brow_up.iter().map(|k| (*k, brows.max(0.0))));
		direct.extend(f.brow_down.iter().map(|k| (*k, (-brows).max(0.0).max(form.max(0.0)))));
		direct.extend(f.brow_sad.iter().map(|k| (*k, (-form).max(0.0))));
		add(&mut w, f.cheek, c.cheek);
		direct.extend(f.cheek_morphs.iter().map(|k| (*k, c.cheek)));

		for (v, e) in w.iter_mut().zip(&m.expressions) {
			*v = v.clamp(0.0, 1.0);
			if e.binary {
				*v = if *v > 0.5 { 1.0 } else { 0.0 };
			}
		}
		// Expressions that cover blinking, looking or the mouth (a laughing face with its eyes shut).
		let (mut ob, mut ol, mut om) = (0.0f32, 0.0f32, 0.0f32);
		for (v, e) in w.iter().zip(&m.expressions) {
			if *v <= 0.0 || matches!(e.preset, Some("blink" | "blinkLeft" | "blinkRight" | "lookUp" | "lookDown" | "lookLeft" | "lookRight" | "aa" | "ih" | "ou" | "ee" | "oh")) {
				continue;
			}
			let level = |o: Override| match o {
				Override::Block => 1.0,
				Override::Blend => *v,
				Override::None => 0.0,
			};
			ob = ob.max(level(e.override_blink));
			ol = ol.max(level(e.override_look_at));
			om = om.max(level(e.override_mouth));
		}
		om = om.min(MOUTH_OVERRIDE_CAP);
		for (v, e) in w.iter_mut().zip(&m.expressions) {
			match e.preset {
				Some("blink" | "blinkLeft" | "blinkRight") => *v *= 1.0 - ob,
				Some("lookUp" | "lookDown" | "lookLeft" | "lookRight") => *v *= 1.0 - ol,
				Some("aa" | "ih" | "ou" | "ee" | "oh") => *v *= 1.0 - om,
				_ => {}
			}
		}
		// Morph weights, and which meshes changed.
		let mut next: Vec<Vec<f32>> = self.morphs.iter().map(|v| vec![0.0; v.len()]).collect();
		for (v, e) in w.iter().zip(&m.expressions) {
			if *v <= 0.0 {
				continue;
			}
			for &(mesh, t, bw) in &e.morphs {
				if let Some(x) = next.get_mut(mesh).and_then(|n| n.get_mut(t)) {
					*x += v * bw;
				}
			}
		}
		for ((mesh, t), v) in direct {
			if let Some(x) = next.get_mut(mesh).and_then(|n| n.get_mut(t)) {
				*x += v;
			}
		}
		for (i, (now, before)) in next.iter_mut().zip(&self.morphs).enumerate() {
			for x in now.iter_mut() {
				*x = x.clamp(0.0, 1.0);
			}
			if now.iter().zip(before).any(|(a, b)| (a - b).abs() > 0.002) {
				self.morph_dirty[i] = true;
			}
		}
		for (i, now) in next.into_iter().enumerate() {
			if self.morph_dirty[i] {
				self.morphs[i] = now;
			}
		}
		// Colours and texture placement that expressions change.
		for (k, mat) in m.materials.iter().enumerate() {
			self.material_colors[k] = base_colors(mat);
			self.material_uv[k] = (Vec2::ONE, Vec2::ZERO);
		}
		for (v, e) in w.iter().zip(&m.expressions) {
			if *v <= 0.0 {
				continue;
			}
			for &(mat, kind, target) in &e.colors {
				let slot = &mut self.material_colors[mat][kind as usize];
				for ch in 0..4 {
					slot[ch] += (target[ch] - slot[ch]) * v;
				}
			}
			for &(mat, scale, offset) in &e.uv {
				let (s, o) = &mut self.material_uv[mat];
				*s += (scale - Vec2::ONE) * *v;
				*o += offset * *v;
			}
		}
		self.weights = w;
	}

}

fn base_colors(m: &model::Material) -> [[f32; 4]; 5] {
	let mut c = [[0.0; 4]; 5];
	c[ColorKind::Base as usize] = m.base;
	c[ColorKind::Shade as usize] = [m.shade[0], m.shade[1], m.shade[2], 1.0];
	c[ColorKind::Emission as usize] = [m.emissive[0], m.emissive[1], m.emissive[2], 1.0];
	c[ColorKind::Rim as usize] = [m.rim[0], m.rim[1], m.rim[2], 1.0];
	c[ColorKind::Outline as usize] = [m.outline_color[0], m.outline_color[1], m.outline_color[2], 1.0];
	let _ = AlphaMode::Opaque;
	c
}

fn find_face(model: &Model) -> Face {
	let names = model::index_names(model);
	let get = |list: &[&str]| -> Vec<(usize, usize)> { list.iter().find_map(|n| names.get(*n).cloned()).unwrap_or_default() };
	let mut face = Face {
		smile: get(&["Fcl_MTH_Fun", "Fcl_MTH_Joy"]),
		frown: get(&["Fcl_MTH_Sorrow"]),
		eye_smile: [get(&["Fcl_EYE_Joy_L"]), get(&["Fcl_EYE_Joy_R"])],
		brow_up: get(&["Fcl_BRW_Surprised"]),
		brow_down: get(&["Fcl_BRW_Angry"]),
		brow_sad: get(&["Fcl_BRW_Sorrow"]),
		cheek: None,
		cheek_morphs: Vec::new(),
	};
	if face.eye_smile[0].is_empty() || face.eye_smile[1].is_empty() {
		let both = get(&["Fcl_EYE_Joy"]);
		if !both.is_empty() {
			face.eye_smile = [both.clone(), Vec::new()];
		}
	}
	// A blush: an expression or a morph named for one.
	let is_blush = |n: &str| {
		let n = n.to_lowercase();
		["blush", "cheek", "shy", "照れ", "頬", "ほほ"].iter().any(|w| n.contains(w))
	};
	face.cheek = model.expressions.iter().position(|e| e.preset.is_none() && is_blush(&e.name));
	if face.cheek.is_none() {
		if let Some((name, _)) = names.iter().find(|(n, _)| is_blush(n)) {
			face.cheek_morphs = names[name].clone();
		}
	}
	face
}

#[cfg(test)]
mod tests;
