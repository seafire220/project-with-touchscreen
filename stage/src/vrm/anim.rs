//! Full-body animation for VRM avatars: the "full-body 3D" style (docs/30-vrm.md).
//!
//! VRM Animation clips (`.vrma`, glTF files with the `VRMC_vrm_animation` extension) move the
//! avatar's whole skeleton: an idle loop chosen by what the character is doing and its mood (`idle`,
//! `idle_happy`, `idle_listen`, `idle_talk` ...), and the gestures the motion system starts. The
//! motion system still decides which gesture plays, when, for how long, mirrored or not, and on which
//! parts of the body (motion.rs); here its timing is turned into the clip's frames. The stage's own
//! living motion goes on top: where the character looks, head turns and nods, body turns, shrugs, its
//! face, blinking and the mouth's shapes.
//!
//! A clip is kept as normalised humanoid rotations (rig.rs), so one made on any skeleton plays on
//! any avatar, and resampled to 30 frames a second. Only the bones a clip moves are kept, and a bone
//! that holds still keeps one value. Clips are loaded only for avatars set to this style.

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;

use glam::{Mat4, Quat, Vec3};
use serde_json::Value;

use super::gltf::Glb;
use super::model::{bone, Model, BONES};
use super::rig::{normalised_pose, Controls};
use crate::behaviour::State;
use crate::motion::CHANNELS;

/// Clip files larger than this are refused.
pub const MAX_FILE_BYTES: u64 = 16 << 20;
/// Clips longer than this are refused.
pub const MAX_SECONDS: f32 = 120.0;
/// Frames a second clips are kept at.
pub const RATE: f32 = 30.0;
/// The most memory all the clips of one avatar may take.
pub const MAX_TOTAL_BYTES: usize = 24 << 20;
/// Seconds to fade from one idle loop to the next.
const BASE_FADE: f32 = 0.7;

// Motion channels (motion.rs CHANNELS).
const HEAD: usize = 0;
const TORSO: usize = 1;
const EYES: usize = 2;
const EXPRESSION: usize = 4;
const ARM_LEFT: usize = 5;
const ARM_RIGHT: usize = 6;
/// The channels a clip can move: head, torso and the arms.
pub const BODY: u16 = 1 << HEAD | 1 << TORSO | 1 << ARM_LEFT | 1 << ARM_RIGHT;

/// Expressions a clip may not drive: blinking, looking and the mouth's shapes belong to the stage.
const FACE_OWN: [&str; 12] = ["blink", "blinkLeft", "blinkRight", "lookUp", "lookDown", "lookLeft", "lookRight", "aa", "ih", "ou", "ee", "oh"];

/// Is a clip of this name an idle loop (played round and round under everything else)?
pub fn is_loop_name(name: &str) -> bool {
	name == "idle" || name.starts_with("idle_")
}

/// Facts about the humanoid's 55 bones: each one's parent in VRM's standard hierarchy, an order with
/// parents first, its mirror image, and the motion channel it belongs to.
struct Bones {
	parent: [Option<usize>; 55],
	order: [usize; 55],
	mirror: [usize; 55],
	channel: [usize; 55],
}

fn bones() -> &'static Bones {
	static TABLES: OnceLock<Bones> = OnceLock::new();
	TABLES.get_or_init(|| {
		let mut parent = [None; 55];
		let mut mirror = [0usize; 55];
		let mut channel = [TORSO; 55];
		for (b, name) in BONES.iter().enumerate() {
			let (side, rest) = if let Some(r) = name.strip_prefix("left") {
				("left", r)
			} else if let Some(r) = name.strip_prefix("right") {
				("right", r)
			} else {
				("", *name)
			};
			let up: Option<String> = match (side, rest) {
				("", "hips") => None,
				("", "spine") => Some("hips".into()),
				("", "chest") => Some("spine".into()),
				("", "upperChest") => Some("chest".into()),
				("", "neck") => Some("upperChest".into()),
				("", "head") => Some("neck".into()),
				("", "jaw") | (_, "Eye") => Some("head".into()),
				(_, "Shoulder") => Some("upperChest".into()),
				(s, "UpperArm") => Some(format!("{s}Shoulder")),
				(s, "LowerArm") => Some(format!("{s}UpperArm")),
				(s, "Hand") => Some(format!("{s}LowerArm")),
				("", _) => None,
				(_, "UpperLeg") => Some("hips".into()),
				(s, "LowerLeg") => Some(format!("{s}UpperLeg")),
				(s, "Foot") => Some(format!("{s}LowerLeg")),
				(s, "Toes") => Some(format!("{s}Foot")),
				(s, r) if r.ends_with("Metacarpal") || r.ends_with("Proximal") && !r.starts_with("Thumb") => Some(format!("{s}Hand")),
				(s, "ThumbProximal") => Some(format!("{s}ThumbMetacarpal")),
				(s, "ThumbDistal") => Some(format!("{s}ThumbProximal")),
				(s, r) => match (r.strip_suffix("Intermediate"), r.strip_suffix("Distal")) {
					(Some(f), _) => Some(format!("{s}{f}Proximal")),
					(_, Some(f)) => Some(format!("{s}{f}Intermediate")),
					_ => None,
				},
			};
			parent[b] = up.map(|p| bone(&p));
			mirror[b] = match side {
				"left" => bone(&format!("right{rest}")),
				"right" => bone(&format!("left{rest}")),
				_ => b,
			};
			channel[b] = match (side, rest) {
				("", "neck" | "head" | "jaw") => HEAD,
				(_, "Eye") => EYES,
				("left", r) if !(r.contains("Leg") || r == "Foot" || r == "Toes") => ARM_LEFT,
				("right", r) if !(r.contains("Leg") || r == "Foot" || r == "Toes") => ARM_RIGHT,
				_ => TORSO,
			};
		}
		// Parents before children.
		let depth = |mut b: usize| {
			let mut d = 0;
			while let Some(p) = parent[b] {
				b = p;
				d += 1;
			}
			d
		};
		let mut order: [usize; 55] = std::array::from_fn(|i| i);
		order.sort_by_key(|b| depth(*b));
		Bones { parent, order, mirror, channel }
	})
}

/// A rotation seen in a mirror (left and right swapped).
fn mirrored(q: Quat) -> Quat {
	Quat::from_xyzw(q.x, -q.y, -q.z, q.w)
}

/// How far apart two rotations are, in degrees.
fn angle(a: Quat, b: Quat) -> f32 {
	let d = a.dot(b).abs().min(1.0);
	(2.0 * d.acos()).to_degrees()
}

/// One clip: what it does to each bone it moves, frame by frame.
#[derive(Clone, Debug)]
pub struct Clip {
	pub name: String,
	/// Seconds from the first frame to the last.
	pub duration: f32,
	frames: usize,
	/// Each bone it moves: the bone, where its frames start in `rotations`, and how many (1: it holds still).
	tracks: Vec<(usize, usize, usize)>,
	rotations: Vec<Quat>,
	/// Where the hips are, from where they stand at rest, in hips heights (empty if they stay).
	hips: Vec<Vec3>,
	/// Expressions it shows, by name, frame by frame.
	expressions: Vec<(String, Vec<f32>)>,
	/// Motion channels it moves a little, and a lot (bits as in motion.rs), and when it moves most.
	pub touches: u16,
	pub holds: u16,
	pub stroke: f32,
	/// Played round and round (an idle loop), its last frame joined to its first.
	pub looped: bool,
	/// Anything odd about the file, worth telling the owner.
	pub warnings: Vec<String>,
}

/// A glTF animation sampler: key times and values.
struct Sampler {
	times: Vec<f32>,
	values: Vec<f32>,
	components: usize,
	step: bool,
	cubic: bool,
}

impl Sampler {
	fn value(&self, k: usize) -> &[f32] {
		let i = if self.cubic { k * 3 + 1 } else { k };
		&self.values[i * self.components..(i + 1) * self.components]
	}

	/// The keys either side of time `t`, and how far between them.
	fn keys_at(&self, t: f32) -> (usize, usize, f32) {
		let n = self.times.len();
		if n == 0 || t <= self.times[0] {
			return (0, 0, 0.0);
		}
		if t >= self.times[n - 1] {
			return (n - 1, n - 1, 0.0);
		}
		let j = self.times.partition_point(|x| *x <= t).min(n - 1);
		let i = j - 1;
		let span = self.times[j] - self.times[i];
		let u = if self.step || span <= 0.0 { 0.0 } else { ((t - self.times[i]) / span).clamp(0.0, 1.0) };
		(i, j, u)
	}

	fn quat(&self, k: usize) -> Quat {
		let v = self.value(k);
		let q = Quat::from_xyzw(v[0], v[1], v[2], v[3]);
		if q.is_finite() && q.length_squared() > 1e-8 { q.normalize() } else { Quat::IDENTITY }
	}

	fn rotation_at(&self, t: f32) -> Quat {
		let (i, j, u) = self.keys_at(t);
		self.quat(i).slerp(self.quat(j), u)
	}

	fn vec3_at(&self, t: f32) -> Vec3 {
		let (i, j, u) = self.keys_at(t);
		let a = self.value(i);
		let b = self.value(j);
		let v = |k: usize| a.get(k).copied().unwrap_or(0.0) * (1.0 - u) + b.get(k).copied().unwrap_or(0.0) * u;
		Vec3::new(v(0), v(1), v(2))
	}
}

fn read_sampler(glb: &Glb, s: &Value) -> Result<Sampler, String> {
	let input = s.get("input").and_then(Value::as_u64).ok_or("an animation sampler has no times")? as usize;
	let output = s.get("output").and_then(Value::as_u64).ok_or("an animation sampler has no values")? as usize;
	let (times, _) = glb.floats(input)?;
	let (values, components) = glb.floats(output)?;
	let interpolation = s.get("interpolation").and_then(Value::as_str).unwrap_or("LINEAR");
	let cubic = interpolation == "CUBICSPLINE";
	let per_key = if cubic { 3 } else { 1 };
	if times.is_empty() || values.len() < times.len() * per_key * components {
		return Err("an animation sampler has fewer values than times".into());
	}
	if times.iter().any(|t| !t.is_finite()) || times.windows(2).any(|w| w[1] < w[0]) {
		return Err("an animation's times do not go forward".into());
	}
	if values.iter().any(|v| !v.is_finite()) {
		return Err("an animation has values that are not numbers".into());
	}
	Ok(Sampler { times, values, components, step: interpolation == "STEP", cubic })
}

/// A node's own place at rest: translation, rotation, scale.
fn node_rest(node: &Value) -> (Vec3, Quat, Vec3) {
	let floats = |key: &str, n: usize| -> Option<Vec<f32>> {
		let a = node.get(key)?.as_array()?;
		let v: Vec<f32> = a.iter().filter_map(|x| x.as_f64().map(|f| f as f32)).collect();
		(v.len() == n && v.iter().all(|x| x.is_finite())).then_some(v)
	};
	if let Some(m) = floats("matrix", 16) {
		let (s, r, t) = Mat4::from_cols_slice(&m).to_scale_rotation_translation();
		return (t, if r.is_finite() { r.normalize() } else { Quat::IDENTITY }, s);
	}
	let t = floats("translation", 3).map(|v| Vec3::new(v[0], v[1], v[2])).unwrap_or(Vec3::ZERO);
	let r = floats("rotation", 4)
		.map(|v| Quat::from_xyzw(v[0], v[1], v[2], v[3]))
		.filter(|q| q.length_squared() > 1e-8)
		.map(Quat::normalize)
		.unwrap_or(Quat::IDENTITY);
	let s = floats("scale", 3).map(|v| Vec3::new(v[0], v[1], v[2])).unwrap_or(Vec3::ONE);
	(t, r, s)
}

impl Clip {
	/// Read a clip file; its name is the file's (without `.vrma`).
	pub fn load(path: &Path) -> Result<Clip, String> {
		let size = std::fs::metadata(path).map_err(|e| format!("cannot read {}: {e}", path.display()))?.len();
		if size > MAX_FILE_BYTES {
			return Err(format!("{} is too large ({} MB; at most {} MB)", path.display(), size >> 20, MAX_FILE_BYTES >> 20));
		}
		let bytes = std::fs::read(path).map_err(|e| format!("cannot read {}: {e}", path.display()))?;
		let name = path.file_stem().and_then(|s| s.to_str()).unwrap_or("clip");
		Clip::from_bytes(name, bytes).map_err(|e| format!("{}: {e}", path.display()))
	}

	pub fn from_bytes(name: &str, bytes: Vec<u8>) -> Result<Clip, String> {
		let glb = Glb::parse(bytes)?;
		let ext = glb
			.json
			.pointer("/extensions/VRMC_vrm_animation")
			.ok_or("it is not a VRM Animation file (no VRMC_vrm_animation)")?
			.clone();
		let nodes = glb.get("nodes");
		let n = nodes.len();
		if n == 0 || n > 4096 {
			return Err("its skeleton is missing or far too large".into());
		}
		let rest: Vec<(Vec3, Quat, Vec3)> = nodes.iter().map(node_rest).collect();
		let mut parent: Vec<Option<usize>> = vec![None; n];
		for (i, node) in nodes.iter().enumerate() {
			for c in node.get("children").and_then(Value::as_array).map(|a| a.as_slice()).unwrap_or(&[]) {
				if let Some(c) = c.as_u64().map(|c| c as usize).filter(|c| *c < n && *c != i) {
					if parent[c].is_none() {
						parent[c] = Some(i);
					}
				}
			}
		}
		// Every node's place at rest, parents first (a loop in the hierarchy is refused).
		let mut world = vec![Mat4::IDENTITY; n];
		let mut world_rot = vec![Quat::IDENTITY; n];
		let mut done = vec![false; n];
		for start in 0..n {
			let mut chain = vec![start];
			while let Some(p) = parent[*chain.last().unwrap()] {
				if done[p] {
					break;
				}
				if chain.contains(&p) || chain.len() > n {
					return Err("its skeleton's hierarchy goes round in a loop".into());
				}
				chain.push(p);
			}
			for &i in chain.iter().rev() {
				if done[i] {
					continue;
				}
				let (t, r, s) = rest[i];
				let (pw, pr) = parent[i].map(|p| (world[p], world_rot[p])).unwrap_or((Mat4::IDENTITY, Quat::IDENTITY));
				world[i] = pw * Mat4::from_scale_rotation_translation(s, r, t);
				world_rot[i] = (pr * r).normalize();
				done[i] = true;
			}
		}
		// Which node is which humanoid bone.
		let mut bone_node: [Option<usize>; 55] = [None; 55];
		if let Some(map) = ext.pointer("/humanoid/humanBones").and_then(Value::as_object) {
			for (name, v) in map {
				let Some(b) = BONES.iter().position(|x| x == name) else { continue };
				if let Some(node) = v.get("node").and_then(Value::as_u64).map(|x| x as usize).filter(|x| *x < n) {
					bone_node[b] = Some(node);
				}
			}
		}
		let hips_node = bone_node[bone("hips")].ok_or("its skeleton has no hips bone")?;
		let position = |b: &str| bone_node[bone(b)].map(|i| world[i].transform_point3(Vec3::ZERO));
		let mut warnings = Vec::new();
		// Facing: VRM's skeletons face +z, the avatar's left towards +x. One facing the other way
		// (left towards -x) is turned round.
		let flip = match (position("leftUpperArm"), position("rightUpperArm")) {
			(Some(l), Some(r)) => l.x < r.x,
			_ => match (position("leftUpperLeg"), position("rightUpperLeg")) {
				(Some(l), Some(r)) => l.x < r.x,
				_ => false,
			},
		};
		// The rest pose should be a T-pose: arms out sideways.
		if let (Some(a), Some(b)) = (position("leftUpperArm"), position("leftLowerArm")) {
			let d = (b - a).normalize_or_zero();
			if d.y.abs() > 0.5 {
				warnings.push("its skeleton is not in a T-pose at rest, so it may play wrongly".into());
			}
		}

		let anim = glb.get("animations").first().ok_or("it has no animation")?;
		let samplers = anim.get("samplers").and_then(Value::as_array).map(|a| a.as_slice()).unwrap_or(&[]);
		let channels = anim.get("channels").and_then(Value::as_array).map(|a| a.as_slice()).unwrap_or(&[]);
		let mut rotation: HashMap<usize, Sampler> = HashMap::new();
		let mut translation: HashMap<usize, Sampler> = HashMap::new();
		for ch in channels {
			let Some(node) = ch.pointer("/target/node").and_then(Value::as_u64).map(|x| x as usize).filter(|x| *x < n) else { continue };
			let path = ch.pointer("/target/path").and_then(Value::as_str).unwrap_or("");
			let Some(s) = ch.get("sampler").and_then(Value::as_u64).and_then(|i| samplers.get(i as usize)) else { continue };
			match path {
				"rotation" => {
					let s = read_sampler(&glb, s)?;
					if s.components != 4 {
						return Err("a rotation in its animation is not four numbers".into());
					}
					rotation.insert(node, s);
				}
				"translation" => {
					let s = read_sampler(&glb, s)?;
					if s.components != 3 {
						return Err("a translation in its animation is not three numbers".into());
					}
					translation.insert(node, s);
				}
				_ => {}
			}
		}
		// Expressions: each a node whose x position is how much it shows.
		let mut expression_nodes: Vec<(String, usize)> = Vec::new();
		for group in ["preset", "custom"] {
			if let Some(map) = ext.pointer(&format!("/expressions/{group}")).and_then(Value::as_object) {
				for (name, v) in map {
					if FACE_OWN.contains(&name.as_str()) || name.len() > 64 {
						continue;
					}
					if let Some(node) = v.get("node").and_then(Value::as_u64).map(|x| x as usize).filter(|x| *x < n) {
						if translation.contains_key(&node) {
							expression_nodes.push((name.clone(), node));
						}
					}
				}
			}
		}
		let used = bone_node
			.iter()
			.flatten()
			.filter_map(|i| rotation.get(i))
			.chain(translation.get(&hips_node))
			.chain(expression_nodes.iter().filter_map(|(_, i)| translation.get(i)));
		let (mut start, mut end) = (f32::MAX, f32::MIN);
		for s in used {
			start = start.min(s.times[0]);
			end = end.max(*s.times.last().unwrap());
		}
		if start > end {
			return Err("its animation moves none of the humanoid's bones".into());
		}
		let duration = end - start;
		if duration > MAX_SECONDS {
			return Err(format!("it is {duration:.0} seconds long; at most {MAX_SECONDS:.0}"));
		}
		let frames = (duration * RATE).floor() as usize + 1;
		let time = |k: usize| start + (k as f32 / RATE).min(duration);

		// Bone turns, as normalised humanoid rotations: n = P x q x W^-1, where P is the parent's turn
		// at rest and W the bone's own (world) turn at rest.
		let mut tracks = Vec::new();
		let mut rotations = Vec::new();
		for b in 0..55 {
			let Some(node) = bone_node[b] else { continue };
			if BONES[b].ends_with("Eye") {
				continue;
			}
			let Some(s) = rotation.get(&node) else { continue };
			let p = parent[node].map(|p| world_rot[p]).unwrap_or(Quat::IDENTITY);
			let w_inv = world_rot[node].inverse();
			let mut frames_b: Vec<Quat> = (0..frames)
				.map(|k| {
					let q = (p * s.rotation_at(time(k)) * w_inv).normalize();
					let q = if flip { Quat::from_xyzw(-q.x, q.y, -q.z, q.w) } else { q };
					if q.w < 0.0 { -q } else { q }
				})
				.collect();
			let first = frames_b[0];
			if frames_b.iter().all(|q| angle(*q, first) < 0.1) {
				if angle(first, Quat::IDENTITY) < 0.1 {
					continue;
				}
				frames_b.truncate(1);
			}
			tracks.push((b, rotations.len(), frames_b.len()));
			rotations.extend(frames_b);
		}
		// The hips: where they are from where they stand at rest, in hips heights.
		let mut hips = Vec::new();
		if let Some(s) = translation.get(&hips_node) {
			let pw = parent[hips_node].map(|p| world[p]).unwrap_or(Mat4::IDENTITY);
			let at_rest = pw.transform_point3(rest[hips_node].0);
			let feet = ["leftFoot", "rightFoot"].iter().filter_map(|b| position(b)).map(|p| p.y).fold(f32::MAX, f32::min);
			let mut height = if feet < f32::MAX { at_rest.y - feet } else { at_rest.y };
			if height < 0.05 {
				height = at_rest.y.abs();
			}
			if height < 0.05 {
				height = 1.0;
			}
			hips = (0..frames)
				.map(|k| {
					let d = (pw.transform_point3(s.vec3_at(time(k))) - at_rest) / height;
					if flip { Vec3::new(-d.x, d.y, -d.z) } else { d }
				})
				.collect();
			if hips.iter().all(|d| d.length() < 1e-4) {
				hips.clear();
			}
		}
		let expressions = expression_nodes
			.into_iter()
			.map(|(name, node)| {
				let s = &translation[&node];
				let w: Vec<f32> = (0..frames).map(|k| s.vec3_at(time(k)).x.clamp(0.0, 1.0)).collect();
				(name, w)
			})
			.filter(|(_, w)| w.iter().any(|x| *x > 0.001))
			.collect();
		let mut clip = Clip {
			name: name.to_string(),
			duration: (frames - 1) as f32 / RATE,
			frames,
			tracks,
			rotations,
			hips,
			expressions,
			touches: 0,
			holds: 0,
			stroke: 0.0,
			looped: false,
			warnings,
		};
		if is_loop_name(name) {
			clip.close_loop();
		}
		clip.measure();
		Ok(clip)
	}

	/// Memory the clip takes, in bytes.
	pub fn bytes(&self) -> usize {
		self.rotations.len() * 16
			+ self.tracks.len() * 24
			+ self.hips.len() * 12
			+ self.expressions.iter().map(|(n, w)| n.len() + w.len() * 4).sum::<usize>()
	}

	/// An idle loop: join its last frame to its first, spreading the difference over the whole clip, so
	/// it plays round without a jump.
	fn close_loop(&mut self) {
		self.looped = true;
		if self.frames < 3 {
			return;
		}
		let last = (self.frames - 1) as f32;
		for &(_, start, count) in &self.tracks {
			if count < 3 {
				continue;
			}
			let r = &mut self.rotations[start..start + count];
			let gap = (r[count - 1] * r[0].inverse()).normalize();
			for (k, q) in r.iter_mut().enumerate() {
				*q = (Quat::IDENTITY.slerp(gap.inverse(), k as f32 / last) * *q).normalize();
			}
		}
		if self.hips.len() == self.frames {
			let drift = self.hips[self.frames - 1] - self.hips[0];
			for (k, d) in self.hips.iter_mut().enumerate() {
				*d -= drift * (k as f32 / last);
			}
		}
		for (_, w) in &mut self.expressions {
			let drift = w[w.len() - 1] - w[0];
			let n = w.len();
			for (k, x) in w.iter_mut().enumerate() {
				*x = (*x - drift * (k as f32 / (n - 1) as f32)).clamp(0.0, 1.0);
			}
		}
	}

	/// Which motion channels it moves a little and a lot (from its first frame), and when it moves most.
	fn measure(&mut self) {
		let t = bones();
		let mut peak = [0.0f32; CHANNELS.len()];
		let mut moved = vec![0.0f32; self.frames];
		for &(b, start, count) in &self.tracks {
			let c = t.channel[b];
			for k in 0..count {
				let a = angle(self.rotations[start + k], self.rotations[start]);
				peak[c] = peak[c].max(a);
				if count == self.frames {
					moved[k] += a;
				}
			}
		}
		if let Some(first) = self.hips.first().copied() {
			for (k, d) in self.hips.iter().enumerate() {
				// A hundredth of the hips' height (about a centimetre) counts as a degree.
				let a = (*d - first).length() * 100.0;
				peak[TORSO] = peak[TORSO].max(a);
				moved[k] += a;
			}
		}
		let (mut touches, mut holds) = (0u16, 0u16);
		for c in [HEAD, TORSO, ARM_LEFT, ARM_RIGHT] {
			let strong = match c {
				HEAD => 8.0,
				TORSO => 6.0,
				_ => 12.0,
			};
			if peak[c] >= 2.0 {
				touches |= 1 << c;
			}
			if peak[c] >= strong {
				holds |= 1 << c;
			}
		}
		if !self.expressions.is_empty() {
			touches |= 1 << EXPRESSION;
		}
		self.touches = touches;
		self.holds = holds;
		let top = moved.iter().copied().fold(0.0f32, f32::max);
		self.stroke = moved.iter().position(|m| top > 0.0 && *m >= 0.9 * top).map(|k| k as f32 / RATE).unwrap_or(0.0);
	}

	/// The frames either side of `t` seconds in, and how far between them.
	fn frame_at(&self, t: f32) -> (usize, usize, f32) {
		if self.frames < 2 {
			return (0, 0, 0.0);
		}
		let last = self.frames - 1;
		let t = if self.looped && self.duration > 0.0 { t.rem_euclid(self.duration) } else { t };
		let f = (t * RATE).clamp(0.0, last as f32);
		let i = (f.floor() as usize).min(last);
		let j = if i == last { if self.looped { 0 } else { last } } else { i + 1 };
		(i, j, f - i as f32)
	}

	fn rotation(&self, track: usize, (i, j, u): (usize, usize, f32)) -> Quat {
		let (_, start, count) = self.tracks[track];
		if count == 1 {
			return self.rotations[start];
		}
		self.rotations[start + i].slerp(self.rotations[start + j], u)
	}

	fn hips_at(&self, (i, j, u): (usize, usize, f32)) -> Vec3 {
		match self.hips.len() {
			0 => Vec3::ZERO,
			_ => self.hips[i].lerp(self.hips[j], u),
		}
	}

	/// The clip `t` seconds in: each bone it moves and its turn (mirrored or not), where the hips
	/// are, and each expression it shows.
	pub fn sample(&self, t: f32, mirror: bool, mut bone_turn: impl FnMut(usize, Quat), mut expression: impl FnMut(usize, f32)) -> Vec3 {
		let at = self.frame_at(t);
		let m = &bones().mirror;
		for k in 0..self.tracks.len() {
			let b = self.tracks[k].0;
			let q = self.rotation(k, at);
			if mirror {
				bone_turn(m[b], mirrored(q));
			} else {
				bone_turn(b, q);
			}
		}
		for (k, (_, w)) in self.expressions.iter().enumerate() {
			let (i, j, u) = at;
			expression(k, w[i] * (1.0 - u) + w[j] * u);
		}
		let h = self.hips_at(at);
		if mirror { Vec3::new(-h.x, h.y, h.z) } else { h }
	}

	/// The expressions it shows, by name.
	pub fn expression_names(&self) -> impl Iterator<Item = &str> {
		self.expressions.iter().map(|(n, _)| n.as_str())
	}
}

/// Every `.vrma` clip in these folders, a later folder's clip replacing an earlier one of the same name;
/// with the problems found (files that could not be read, or that did not fit).
pub fn load_folders(folders: &[PathBuf]) -> (Vec<Clip>, Vec<String>) {
	let mut files: Vec<(String, PathBuf)> = Vec::new();
	for folder in folders {
		let Ok(entries) = std::fs::read_dir(folder) else { continue };
		let mut found: Vec<PathBuf> = entries
			.flatten()
			.map(|e| e.path())
			.filter(|p| p.extension().and_then(|e| e.to_str()).map(|e| e.eq_ignore_ascii_case("vrma")).unwrap_or(false))
			.collect();
		found.sort();
		for path in found {
			let Some(name) = path.file_stem().and_then(|s| s.to_str()).map(clip_name) else { continue };
			if name.is_empty() {
				continue;
			}
			files.retain(|(n, _)| *n != name);
			files.push((name, path));
		}
	}
	let mut clips: Vec<Clip> = Vec::new();
	let mut problems = Vec::new();
	let mut total = 0;
	for (name, path) in files {
		match Clip::load(&path) {
			Ok(mut clip) => {
				clip.name = name;
				if total + clip.bytes() > MAX_TOTAL_BYTES {
					problems.push(format!("{}: left out; the animations would take too much memory", path.display()));
					continue;
				}
				total += clip.bytes();
				for w in &clip.warnings {
					problems.push(format!("{}: {w}", path.display()));
				}
				clips.push(clip);
			}
			Err(e) => problems.push(e),
		}
	}
	(clips, problems)
}

/// A clip's name from its file's: lower-case letters and _, as the motion library names things.
pub fn clip_name(stem: &str) -> String {
	let mut out: String = stem
		.chars()
		.map(|c| if c.is_ascii_alphabetic() { c.to_ascii_lowercase() } else { '_' })
		.take(40)
		.collect();
	while out.ends_with('_') && out.len() > 1 && !stem.ends_with('_') {
		out.pop();
	}
	if out.chars().all(|c| c == '_') && !stem.starts_with('_') {
		out.clear();
	}
	out
}

/// What the motion system is playing from clips this frame (motion.rs `external_layers`).
#[derive(Clone, Debug, Default)]
pub struct Layer {
	pub name: String,
	/// Seconds into the clip.
	pub at: f32,
	pub mirrored: bool,
	/// How much it shows on each motion channel (faded where it was cut short or let a channel go).
	pub weights: [f32; CHANNELS.len()],
}

/// What the character is doing, for choosing its idle loop and playing its gestures.
#[derive(Clone, Debug)]
pub struct Scene {
	pub state: State,
	pub mood: String,
	/// Dozing.
	pub resting: bool,
	pub layers: Vec<Layer>,
	/// How much gestures without clips hold each arm (left, right): the arms then follow the controls.
	pub arm_hold: [f32; 2],
}

impl Default for Scene {
	fn default() -> Self {
		Scene { state: State::Idle, mood: "neutral".into(), resting: false, layers: Vec::new(), arm_hold: [0.0; 2] }
	}
}

struct Base {
	clip: usize,
	t: f32,
	weight: f32,
}

/// The full-body player for one avatar.
pub struct Animator {
	clips: Vec<Clip>,
	by_name: HashMap<String, usize>,
	/// Each clip's expressions, as the avatar's expression numbers.
	clip_expressions: Vec<Vec<Option<usize>>>,
	/// Idle loops playing, the wanted one last (others fading out).
	base: Vec<Base>,
	/// The avatar's hips height at rest, in metres.
	hips_height: f32,
	/// Expression weights the clips add this frame, one per avatar expression.
	pub expressions: Vec<f32>,
	/// How far the clips move the hips this frame, in metres.
	pub hips_offset: Vec3,
}

/// Turns the stage's controls add on top of clips: head, neck, body and shoulders.
const ADDED: [&str; 7] = ["neck", "head", "spine", "chest", "upperChest", "leftShoulder", "rightShoulder"];

/// Fade a one-off clip in and out (its first and last frames need not match what the body is doing).
fn envelope(duration: f32, at: f32) -> f32 {
	let fade_in = (duration * 0.25).min(0.3).max(1e-3);
	let fade_out = (duration * 0.3).min(0.45).max(1e-3);
	let s = |x: f32| {
		let x = x.clamp(0.0, 1.0);
		x * x * (3.0 - 2.0 * x)
	};
	s(at / fade_in) * s((duration - at) / fade_out)
}

impl Animator {
	pub fn new(clips: Vec<Clip>, model: &Model, hips_height: f32) -> Animator {
		let mut a = Animator {
			clips: Vec::new(),
			by_name: HashMap::new(),
			clip_expressions: Vec::new(),
			base: Vec::new(),
			hips_height: hips_height.max(0.1),
			expressions: vec![0.0; model.expressions.len()],
			hips_offset: Vec3::ZERO,
		};
		for clip in clips {
			a.add(clip, model);
		}
		a
	}

	/// Add a clip, or replace the one of the same name.
	pub fn add(&mut self, mut clip: Clip, model: &Model) {
		if is_loop_name(&clip.name) && !clip.looped {
			clip.close_loop();
			clip.measure();
		}
		let expressions = clip.expression_names().map(|n| model.expression(n)).collect();
		match self.by_name.get(&clip.name) {
			Some(&i) => {
				self.clips[i] = clip;
				self.clip_expressions[i] = expressions;
			}
			None => {
				self.by_name.insert(clip.name.clone(), self.clips.len());
				self.clips.push(clip);
				self.clip_expressions.push(expressions);
			}
		}
	}

	pub fn clips(&self) -> &[Clip] {
		&self.clips
	}

	pub fn has_loop(&self, name: &str) -> bool {
		self.by_name.get(name).is_some_and(|&i| self.clips[i].looped)
	}

	/// Clips played once (gestures and idle actions), for the motion system.
	pub fn one_offs(&self) -> impl Iterator<Item = &Clip> {
		self.clips.iter().filter(|c| !c.looped)
	}

	pub fn bytes(&self) -> usize {
		self.clips.iter().map(Clip::bytes).sum()
	}

	/// The idle loop for what the character is doing and its mood, falling back to plainer ones.
	fn choose(&self, s: &Scene) -> Option<usize> {
		let mood = format!("idle_{}", s.mood);
		let mut names: Vec<&str> = Vec::new();
		if s.resting {
			names.push("idle_sleep");
		}
		match s.state {
			State::Thinking => names.push("idle_think"),
			State::Listening => names.push("idle_listen"),
			State::Speaking if matches!(s.mood.as_str(), "neutral" | "happy") => names.push("idle_talk"),
			State::Speaking => {
				names.push(&mood);
				names.push("idle_talk");
			}
			State::Idle => {}
		}
		names.push(&mood);
		if s.mood == "thinking" {
			names.push("idle_think");
		}
		names.push("idle");
		names.iter().find_map(|n| self.by_name.get(*n).copied().filter(|i| self.clips[*i].looped))
	}

	/// The normalised pose this frame: the idle loop (or, without one, the controls' own pose), the
	/// stage's head, body and shoulder turns on top, the arms following the controls where gestures
	/// without clips hold them, then the gestures playing from clips.
	pub fn pose(&mut self, model: &Model, c: &Controls, scene: &Scene, dt: f32) -> [Quat; 55] {
		let t = bones();
		// The clips breathe and sway the body themselves: the controls' breathing is left out, and
		// their body turns count for less.
		let mut own = *c;
		own.breath = 0.0;
		own.body *= 0.6;
		let controls = normalised_pose(model, &own);
		let want = self.choose(scene);
		if self.base.last().map(|b| Some(b.clip)) != Some(want) {
			if let Some(clip) = want {
				// Back to a loop that is still fading out: carry on from where it is.
				match self.base.iter().position(|b| b.clip == clip) {
					Some(i) => {
						let b = self.base.remove(i);
						self.base.push(b);
					}
					None => self.base.push(Base { clip, t: 0.0, weight: 0.0 }),
				}
			}
		}
		let step = dt / BASE_FADE;
		let last = self.base.len().saturating_sub(1);
		for (i, b) in self.base.iter_mut().enumerate() {
			let target = if i == last && Some(b.clip) == want { 1.0 } else { 0.0 };
			b.weight += (target - b.weight).clamp(-step, step);
			b.t += dt;
		}
		self.base.retain(|b| b.weight > 0.0 || Some(b.clip) == want);

		let total: f32 = self.base.iter().map(|b| b.weight).sum::<f32>().min(1.0);
		// Without a loop (or while the first fades in), the controls' own pose, breathing and all.
		let mut q = if total < 1.0 { normalised_pose(model, c) } else { controls };
		let mut hips = Vec3::ZERO;
		for e in self.expressions.iter_mut() {
			*e = 0.0;
		}
		if total > 0.0 {
			// Each loop's share: a running weighted average of rotations.
			let mut acc = 1.0 - total;
			for b in &self.base {
				if b.weight <= 0.0 {
					continue;
				}
				acc += b.weight;
				let share = b.weight / acc;
				let clip = &self.clips[b.clip];
				let mut pose = [Quat::IDENTITY; 55];
				let names = &self.clip_expressions[b.clip];
				let expressions = &mut self.expressions;
				let h = clip.sample(b.t, false, |bone, r| pose[bone] = r, |k, w| {
					if let Some(e) = names[k] {
						expressions[e] += w * b.weight;
					}
				});
				for (dst, src) in q.iter_mut().zip(pose.iter()) {
					*dst = dst.slerp(*src, share);
				}
				hips = hips.lerp(h, share);
			}
			// The stage's turns on top of the loop.
			for name in ADDED {
				let b = bone(name);
				q[b] = (Quat::IDENTITY.slerp(controls[b], total) * q[b]).normalize();
			}
			// The arms follow the controls while gestures without clips move them.
			for (side, hold) in [ARM_LEFT, ARM_RIGHT].into_iter().zip(scene.arm_hold) {
				let w = (hold * total).clamp(0.0, 1.0);
				if w <= 0.0 {
					continue;
				}
				for b in 0..55 {
					if t.channel[b] == side && !BONES[b].ends_with("Shoulder") {
						q[b] = q[b].slerp(controls[b], w);
					}
				}
			}
		}

		// Gestures from clips: the arms take the clip's pose; the head and body add its movement (from
		// its first frame) to theirs, so breathing, looking and nods carry on through a bow.
		for layer in &scene.layers {
			let Some(&ci) = self.by_name.get(&layer.name) else { continue };
			let clip = &self.clips[ci];
			let env = envelope(clip.duration.max(0.5), layer.at);
			if env <= 0.0 {
				continue;
			}
			let mut first = [Quat::IDENTITY; 55];
			let start = clip.sample(0.0, layer.mirrored, |bone, r| first[bone] = r, |_, _| {});
			let mut now = [Quat::IDENTITY; 55];
			let mut moved = 0u64;
			let names = &self.clip_expressions[ci];
			let expressions = &mut self.expressions;
			let h = clip.sample(
				layer.at,
				layer.mirrored,
				|bone, r| {
					now[bone] = r;
					moved |= 1 << bone;
				},
				|k, w| {
					if let Some(e) = names[k] {
						expressions[e] += w * layer.weights[EXPRESSION] * env;
					}
				},
			);
			for b in 0..55 {
				if moved & (1 << b) == 0 {
					continue;
				}
				let ch = t.channel[b];
				let w = (layer.weights[ch] * env).clamp(0.0, 1.0);
				if w <= 0.0 {
					continue;
				}
				if ch == ARM_LEFT || ch == ARM_RIGHT {
					q[b] = q[b].slerp(now[b], w);
				} else {
					let change = (now[b] * first[b].inverse()).normalize();
					q[b] = (Quat::IDENTITY.slerp(change, w) * q[b]).normalize();
				}
			}
			hips += (h - start) * (layer.weights[TORSO] * env).clamp(0.0, 1.0);
		}

		// The hips: kept near where they stand (a clip that walks away stays in place on the screen).
		let mut offset = hips * self.hips_height;
		let side = Vec3::new(offset.x, 0.0, offset.z);
		let limit = 0.35 * self.hips_height;
		if side.length() > limit {
			let s = side.normalize() * limit;
			offset.x = s.x;
			offset.z = s.z;
		}
		offset.y = offset.y.clamp(-0.6 * self.hips_height, 0.25 * self.hips_height);
		self.hips_offset = offset;
		for e in self.expressions.iter_mut() {
			*e = e.clamp(0.0, 1.0);
		}
		fold_missing(model, &mut q);
		q
	}
}

/// Bones the avatar does not have pass their turns on to the bones below them (an avatar without
/// an upper chest bends its neck and shoulders by the upper chest's turn too).
pub fn fold_missing(model: &Model, q: &mut [Quat; 55]) {
	let t = bones();
	for &b in &t.order {
		if model.humanoid[b].is_some() || q[b] == Quat::IDENTITY {
			continue;
		}
		for child in 0..55 {
			if t.parent[child] == Some(b) {
				q[child] = (q[b] * q[child]).normalize();
			}
		}
		q[b] = Quat::IDENTITY;
	}
}

#[cfg(test)]
pub(crate) mod tests {
	use super::*;
	use crate::vrm::gltf::tests::build;
	use serde_json::json;

	/// A VRM Animation file: a small humanoid skeleton (facing +z, or -z), whose rest pose has its own
	/// turns (as VRM 1.0 allows), and keys for some bones, the hips and an expression.
	pub fn sample_vrma(facing_back: bool, keys: &[(&str, &[(f32, Quat)])], hips: &[(f32, Vec3)], happy: &[(f32, f32)]) -> Vec<u8> {
		let s = if facing_back { -1.0 } else { 1.0 };
		// name, parent, translation (metres), rest rotation
		let skeleton: Vec<(&str, Option<usize>, Vec3, Quat)> = vec![
			("hips", None, Vec3::new(0.0, 0.9, 0.0), Quat::IDENTITY),
			("spine", Some(0), Vec3::new(0.0, 0.1, 0.0), Quat::from_rotation_x(0.2)),
			("chest", Some(1), Vec3::new(0.0, 0.15, 0.0), Quat::from_rotation_x(-0.2)),
			("neck", Some(2), Vec3::new(0.0, 0.25, 0.0), Quat::IDENTITY),
			("head", Some(3), Vec3::new(0.0, 0.1, 0.0), Quat::from_rotation_y(0.3)),
			("leftUpperArm", Some(2), Vec3::new(s * 0.18, 0.2, 0.0), Quat::from_rotation_z(0.5)),
			("leftLowerArm", Some(5), Vec3::new(s * 0.25, 0.0, 0.0), Quat::IDENTITY),
			("leftHand", Some(6), Vec3::new(s * 0.22, 0.0, 0.0), Quat::IDENTITY),
			("rightUpperArm", Some(2), Vec3::new(-s * 0.18, 0.2, 0.0), Quat::IDENTITY),
			("rightLowerArm", Some(8), Vec3::new(-s * 0.25, 0.0, 0.0), Quat::IDENTITY),
			("rightHand", Some(9), Vec3::new(-s * 0.22, 0.0, 0.0), Quat::IDENTITY),
			("leftUpperLeg", Some(0), Vec3::new(s * 0.09, -0.05, 0.0), Quat::IDENTITY),
			("leftLowerLeg", Some(11), Vec3::new(0.0, -0.4, 0.0), Quat::IDENTITY),
			("leftFoot", Some(12), Vec3::new(0.0, -0.4, 0.0), Quat::IDENTITY),
			("rightUpperLeg", Some(0), Vec3::new(-s * 0.09, -0.05, 0.0), Quat::IDENTITY),
			("rightLowerLeg", Some(14), Vec3::new(0.0, -0.4, 0.0), Quat::IDENTITY),
			("rightFoot", Some(15), Vec3::new(0.0, -0.4, 0.0), Quat::IDENTITY),
		];
		// The rest rotation of the upper arm is undone by its child so the arm still points sideways:
		// what matters is that the bones' own axes differ from the world's.
		let mut nodes: Vec<Value> = skeleton
			.iter()
			.map(|(name, _, t, r)| json!({"name": name, "translation": [t.x, t.y, t.z], "rotation": [r.x, r.y, r.z, r.w]}))
			.collect();
		for (i, (_, parent, _, _)) in skeleton.iter().enumerate() {
			if let Some(p) = parent {
				let children = nodes[*p].get("children").cloned().unwrap_or(json!([]));
				let mut list = children.as_array().unwrap().clone();
				list.push(json!(i));
				nodes[*p]["children"] = json!(list);
			}
		}
		// Translations are in the parent's space: undo the parents' rest turns so the joints sit in a T-pose.
		let mut world_rot = vec![Quat::IDENTITY; skeleton.len()];
		for (i, (_, parent, t, r)) in skeleton.iter().enumerate() {
			let pr = parent.map(|p| world_rot[p]).unwrap_or(Quat::IDENTITY);
			world_rot[i] = pr * *r;
			let local = pr.inverse() * *t;
			nodes[i]["translation"] = json!([local.x, local.y, local.z]);
		}
		nodes.push(json!({"name": "happy", "translation": [0.0, 0.0, 0.0]}));
		let happy_node = nodes.len() - 1;
		let mut bin: Vec<u8> = Vec::new();
		let mut views = Vec::new();
		let mut accessors = Vec::new();
		let mut add = |data: Vec<f32>, kind: &str, count: usize, views: &mut Vec<Value>, accessors: &mut Vec<Value>, bin: &mut Vec<u8>| {
			let offset = bin.len();
			for v in &data {
				bin.extend_from_slice(&v.to_le_bytes());
			}
			views.push(json!({"buffer": 0, "byteOffset": offset, "byteLength": data.len() * 4}));
			accessors.push(json!({"bufferView": views.len() - 1, "componentType": 5126, "count": count, "type": kind}));
			accessors.len() - 1
		};
		let mut samplers = Vec::new();
		let mut channels = Vec::new();
		for (name, frames) in keys {
			let node = skeleton.iter().position(|b| b.0 == *name).unwrap();
			// Keys are given as world-aligned turns (normalised); store them as the node's own rotation:
			// q = P^-1 x n x W, with P the parent's rest turn and W the node's.
			let p = skeleton[node].1.map(|p| world_rot[p]).unwrap_or(Quat::IDENTITY);
			let w = world_rot[node];
			let times: Vec<f32> = frames.iter().map(|f| f.0).collect();
			let mut values = Vec::new();
			for (_, n) in frames.iter() {
				let n = if facing_back { Quat::from_xyzw(-n.x, n.y, -n.z, n.w) } else { *n };
				let q = p.inverse() * n * w;
				values.extend_from_slice(&[q.x, q.y, q.z, q.w]);
			}
			let input = add(times, "SCALAR", frames.len(), &mut views, &mut accessors, &mut bin);
			let output = add(values, "VEC4", frames.len(), &mut views, &mut accessors, &mut bin);
			samplers.push(json!({"input": input, "output": output, "interpolation": "LINEAR"}));
			channels.push(json!({"sampler": samplers.len() - 1, "target": {"node": node, "path": "rotation"}}));
		}
		if !hips.is_empty() {
			let times: Vec<f32> = hips.iter().map(|f| f.0).collect();
			let values: Vec<f32> = hips.iter().flat_map(|(_, d)| [s * d.x, 0.9 + d.y, s * d.z]).collect();
			let input = add(times, "SCALAR", hips.len(), &mut views, &mut accessors, &mut bin);
			let output = add(values, "VEC3", hips.len(), &mut views, &mut accessors, &mut bin);
			samplers.push(json!({"input": input, "output": output}));
			channels.push(json!({"sampler": samplers.len() - 1, "target": {"node": 0, "path": "translation"}}));
		}
		if !happy.is_empty() {
			let times: Vec<f32> = happy.iter().map(|f| f.0).collect();
			let values: Vec<f32> = happy.iter().flat_map(|(_, w)| [*w, 0.0, 0.0]).collect();
			let input = add(times, "SCALAR", happy.len(), &mut views, &mut accessors, &mut bin);
			let output = add(values, "VEC3", happy.len(), &mut views, &mut accessors, &mut bin);
			samplers.push(json!({"input": input, "output": output}));
			channels.push(json!({"sampler": samplers.len() - 1, "target": {"node": happy_node, "path": "translation"}}));
		}
		let bones: serde_json::Map<String, Value> =
			skeleton.iter().enumerate().map(|(i, b)| (b.0.to_string(), json!({"node": i}))).collect();
		let doc = json!({
			"asset": {"version": "2.0"},
			"scenes": [{"nodes": [0, happy_node]}],
			"nodes": nodes,
			"animations": [{"samplers": samplers, "channels": channels}],
			"accessors": accessors,
			"bufferViews": views,
			"buffers": [{"byteLength": bin.len()}],
			"extensions": {"VRMC_vrm_animation": {
				"specVersion": "1.0",
				"humanoid": {"humanBones": bones},
				"expressions": {"preset": {"happy": {"node": happy_node}, "blink": {"node": happy_node}}}
			}}
		});
		build(&doc, &bin)
	}

	fn deg(d: f32) -> f32 {
		d.to_radians()
	}

	fn turns(clip: &Clip, t: f32, mirror: bool) -> ([Quat; 55], Vec3, Vec<f32>) {
		let mut q = [Quat::IDENTITY; 55];
		let mut e = vec![0.0; clip.expressions.len()];
		let h = clip.sample(t, mirror, |b, r| q[b] = r, |k, w| e[k] = w);
		(q, h, e)
	}

	#[test]
	fn reads_a_clip_as_normalised_turns_whatever_the_skeletons_own_axes() {
		let lower = Quat::from_rotation_z(deg(-75.0));
		let nod = Quat::from_rotation_x(deg(20.0));
		for facing_back in [false, true] {
			let file = sample_vrma(
				facing_back,
				&[("leftUpperArm", &[(0.0, Quat::IDENTITY), (1.0, lower)]), ("head", &[(0.0, Quat::IDENTITY), (0.5, nod), (1.0, Quat::IDENTITY)])],
				&[(0.0, Vec3::ZERO), (1.0, Vec3::new(0.085, -0.0425, 0.0))],
				&[(0.0, 0.0), (1.0, 1.0)],
			);
			let clip = Clip::from_bytes("wave", file).unwrap();
			assert!((clip.duration - 1.0).abs() < 1e-4);
			assert_eq!(clip.frames, 31);
			let (q, hips, e) = turns(&clip, 1.0, false);
			assert!(angle(q[bone("leftUpperArm")], lower) < 0.5, "facing back {facing_back}: {:?}", q[bone("leftUpperArm")]);
			let (q, _, _) = turns(&clip, 0.5, false);
			assert!(angle(q[bone("head")], nod) < 0.5);
			// Bones that keep their rest pose have no track, even with rest turns of their own.
			assert!(!clip.tracks.iter().any(|t| t.0 == bone("spine") || t.0 == bone("chest")));
			// The hips (0.85 m high) moved a tenth of their height sideways and dropped by a twentieth.
			assert!((hips - Vec3::new(0.1, -0.05, 0.0)).length() < 1e-3, "{hips}");
			// Only the expressions a clip may drive: happy, not blink.
			assert_eq!(clip.expression_names().collect::<Vec<_>>(), vec!["happy"]);
			assert!((e[0] - 1.0).abs() < 1e-4);
			assert!(clip.holds & (1 << ARM_LEFT) != 0 && clip.holds & (1 << HEAD) != 0);
			assert!(clip.holds & (1 << ARM_RIGHT) == 0);
		}
	}

	#[test]
	fn mirrors_and_loops() {
		let raise = Quat::from_rotation_z(deg(-30.0)) * Quat::from_rotation_y(deg(10.0));
		let file = sample_vrma(false, &[("rightUpperArm", &[(0.0, Quat::IDENTITY), (2.0, raise)])], &[], &[]);
		let clip = Clip::from_bytes("shrug", file.clone()).unwrap();
		let (q, _, _) = turns(&clip, 2.0, true);
		let left = q[bone("leftUpperArm")];
		// Mirrored: the left arm does what the right did, seen in a mirror.
		let v = Vec3::new(1.0, 0.0, 0.0);
		let (a, b) = (left * v, raise * Vec3::new(-1.0, 0.0, 0.0));
		assert!((a - Vec3::new(-b.x, b.y, b.z)).length() < 1e-3, "{a} {b}");
		// A loop joins its end to its start, keeping what happens between.
		let drift = Quat::from_rotation_z(deg(-4.0));
		let file = sample_vrma(false, &[("rightUpperArm", &[(0.0, Quat::IDENTITY), (1.0, raise), (2.0, drift)])], &[], &[]);
		let looped = Clip::from_bytes("idle_happy", file).unwrap();
		assert!(looped.looped);
		let (start, _, _) = turns(&looped, 0.0, false);
		let (end, _, _) = turns(&looped, looped.duration - 1e-3, false);
		assert!(angle(start[bone("rightUpperArm")], end[bone("rightUpperArm")]) < 0.5);
		let (middle, _, _) = turns(&looped, 1.0, false);
		assert!((angle(middle[bone("rightUpperArm")], Quat::IDENTITY) - angle(raise, Quat::IDENTITY)).abs() < 3.0);
		let (wrapped, _, _) = turns(&looped, looped.duration + 0.5, false);
		let (half, _, _) = turns(&looped, 0.5, false);
		assert!(angle(wrapped[bone("rightUpperArm")], half[bone("rightUpperArm")]) < 0.01);
	}

	#[test]
	fn refuses_files_that_are_not_clips() {
		assert!(Clip::from_bytes("x", b"not a glb".to_vec()).is_err());
		let doc = json!({"asset": {"version": "2.0"}, "nodes": [{"name": "hips"}], "buffers": [{"byteLength": 0}]});
		let err = Clip::from_bytes("x", build(&doc, &[])).unwrap_err();
		assert!(err.contains("VRM Animation"), "{err}");
		let file = sample_vrma(false, &[], &[], &[]);
		assert!(Clip::from_bytes("x", file).unwrap_err().contains("moves none"));
		assert_eq!(clip_name("Dance-01"), "dance");
		assert_eq!(clip_name("idle_happy"), "idle_happy");
		assert_eq!(clip_name("123"), "");
	}
}
