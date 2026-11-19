//! A VRM avatar as plain data: its node tree, skins, meshes (with their morph targets), materials,
//! the humanoid bone map, expressions, eye look-at, spring bones and constraints. Both VRM 1.0
//! (`VRMC_vrm`) and VRM 0.x (`VRM`) files are read into the same shape; 0.x names and units are
//! turned into 1.0 ones here.

use std::collections::HashMap;

use glam::{Mat4, Quat, Vec2, Vec3};
use serde_json::Value;

use super::gltf::Glb;

/// The humanoid bones VRM 1.0 names. The first fifteen are required.
pub const BONES: [&str; 55] = [
	"hips", "spine", "head", "leftUpperArm", "leftLowerArm", "leftHand", "rightUpperArm", "rightLowerArm", "rightHand",
	"leftUpperLeg", "leftLowerLeg", "leftFoot", "rightUpperLeg", "rightLowerLeg", "rightFoot",
	"chest", "upperChest", "neck", "leftEye", "rightEye", "jaw", "leftShoulder", "rightShoulder", "leftToes", "rightToes",
	"leftThumbMetacarpal", "leftThumbProximal", "leftThumbDistal", "leftIndexProximal", "leftIndexIntermediate",
	"leftIndexDistal", "leftMiddleProximal", "leftMiddleIntermediate", "leftMiddleDistal", "leftRingProximal",
	"leftRingIntermediate", "leftRingDistal", "leftLittleProximal", "leftLittleIntermediate", "leftLittleDistal",
	"rightThumbMetacarpal", "rightThumbProximal", "rightThumbDistal", "rightIndexProximal", "rightIndexIntermediate",
	"rightIndexDistal", "rightMiddleProximal", "rightMiddleIntermediate", "rightMiddleDistal", "rightRingProximal",
	"rightRingIntermediate", "rightRingDistal", "rightLittleProximal", "rightLittleIntermediate", "rightLittleDistal",
];
pub const REQUIRED_BONES: usize = 15;

pub fn bone(name: &str) -> usize {
	BONES.iter().position(|b| *b == name).expect("a known bone name")
}

/// VRM 0.x thumb names, and the VRM 1.0 names for the same bones.
fn bone_name_from_v0(name: &str) -> &str {
	match name {
		"leftThumbProximal" => "leftThumbMetacarpal",
		"leftThumbIntermediate" => "leftThumbProximal",
		"rightThumbProximal" => "rightThumbMetacarpal",
		"rightThumbIntermediate" => "rightThumbProximal",
		other => other,
	}
}

/// The expressions VRM 1.0 names, and the VRM 0.x preset each comes from.
pub const PRESETS: [(&str, &str); 18] = [
	("happy", "joy"),
	("angry", "angry"),
	("sad", "sorrow"),
	("relaxed", "fun"),
	("surprised", "surprised"),
	("aa", "a"),
	("ih", "i"),
	("ou", "u"),
	("ee", "e"),
	("oh", "o"),
	("blink", "blink"),
	("blinkLeft", "blink_l"),
	("blinkRight", "blink_r"),
	("lookUp", "lookup"),
	("lookDown", "lookdown"),
	("lookLeft", "lookleft"),
	("lookRight", "lookright"),
	("neutral", "neutral"),
];

#[derive(Clone, Debug)]
pub struct Node {
	#[allow(dead_code)]
	pub name: String,
	pub parent: Option<usize>,
	pub children: Vec<usize>,
	pub translation: Vec3,
	pub rotation: Quat,
	pub scale: Vec3,
	pub mesh: Option<usize>,
	pub skin: Option<usize>,
}

#[derive(Clone, Debug)]
pub struct Skin {
	pub joints: Vec<usize>,
	pub inverse_bind: Vec<Mat4>,
}

/// A morph target: how far it moves the points it moves (a face's targets each touch few).
#[derive(Clone, Debug, Default)]
pub struct Target {
	pub indices: Vec<u32>,
	pub deltas: Vec<Vec3>,
}

/// A set of points (with their normals, texture places, bone weights and face shapes). The parts of a
/// mesh that use the same data share one: VRoid Studio's exports give one set to dozens of parts.
#[derive(Clone, Debug, Default)]
pub struct Points {
	pub positions: Vec<Vec3>,
	pub normals: Vec<Vec3>,
	pub uvs: Vec<Vec2>,
	pub joints: Vec<[u16; 4]>,
	pub weights: Vec<[f32; 4]>,
	pub targets: Vec<Target>,
}

/// One part of a mesh: its triangles (into one of the mesh's sets of points) and its material.
#[derive(Clone, Debug)]
pub struct Primitive {
	pub points: usize,
	pub indices: Vec<u32>,
	pub material: Option<usize>,
}

#[derive(Clone, Debug)]
pub struct Mesh {
	#[allow(dead_code)]
	pub name: String,
	pub points: Vec<Points>,
	pub primitives: Vec<Primitive>,
	pub target_names: Vec<String>,
}

impl Mesh {
	/// How many face shapes its parts have, at most.
	pub fn target_count(&self) -> usize {
		self.points.iter().map(|p| p.targets.len()).max().unwrap_or(0)
	}
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum AlphaMode {
	Opaque,
	Mask(f32),
	Blend,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum OutlineMode {
	None,
	World,
	Screen,
}

/// A texture a material uses: the glTF texture, and an offset and scale for its coordinates.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct TexRef {
	pub texture: usize,
	pub offset: Vec2,
	pub scale: Vec2,
}

/// The parts of MToon (VRM's toon shading) the device draws. Colours are in display (sRGB) values.
#[derive(Clone, Debug)]
pub struct Material {
	pub name: String,
	pub base: [f32; 4],
	pub base_texture: Option<TexRef>,
	pub shade: [f32; 3],
	pub shade_texture: Option<TexRef>,
	pub shading_shift: f32,
	pub shading_toony: f32,
	pub emissive: [f32; 3],
	pub emissive_texture: Option<TexRef>,
	pub rim: [f32; 3],
	pub rim_power: f32,
	pub rim_lift: f32,
	pub rim_mix: f32,
	pub outline_mode: OutlineMode,
	pub outline_width: f32,
	pub outline_color: [f32; 3],
	pub outline_mix: f32,
	pub alpha: AlphaMode,
	pub double_sided: bool,
	pub zwrite: bool,
	pub queue: i32,
	pub unlit: bool,
	pub mtoon: bool,
}

impl Default for Material {
	fn default() -> Self {
		Material {
			name: String::new(),
			base: [1.0; 4],
			base_texture: None,
			shade: [0.7, 0.7, 0.7],
			shade_texture: None,
			shading_shift: 0.0,
			shading_toony: 0.9,
			emissive: [0.0; 3],
			emissive_texture: None,
			rim: [0.0; 3],
			rim_power: 5.0,
			rim_lift: 0.0,
			rim_mix: 1.0,
			outline_mode: OutlineMode::None,
			outline_width: 0.0,
			outline_color: [0.0; 3],
			outline_mix: 1.0,
			alpha: AlphaMode::Opaque,
			double_sided: false,
			zwrite: true,
			queue: 0,
			unlit: false,
			mtoon: false,
		}
	}
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Override {
	None,
	Block,
	Blend,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ColorKind {
	Base,
	Shade,
	Emission,
	Rim,
	Outline,
}

#[derive(Clone, Debug)]
pub struct Expression {
	pub name: String,
	/// The VRM 1.0 preset this is, if any.
	pub preset: Option<&'static str>,
	pub binary: bool,
	/// (mesh, target, weight 0..1)
	pub morphs: Vec<(usize, usize, f32)>,
	pub colors: Vec<(usize, ColorKind, [f32; 4])>,
	/// (material, scale, offset)
	pub uv: Vec<(usize, Vec2, Vec2)>,
	pub override_blink: Override,
	pub override_look_at: Override,
	pub override_mouth: Override,
}

#[derive(Clone, Copy, Debug)]
pub struct RangeMap {
	pub input_max: f32,
	pub output_scale: f32,
}

impl RangeMap {
	pub fn map(&self, degrees: f32) -> f32 {
		(degrees.abs().min(self.input_max) / self.input_max.max(1e-3)) * self.output_scale
	}
}

#[derive(Clone, Debug)]
pub struct LookAt {
	/// Eye bones turn (true), or the look expressions show (false).
	pub bones: bool,
	/// Where the eyes are, from the head bone (kept for looking at points, not used yet).
	#[allow(dead_code)]
	pub offset: Vec3,
	pub horizontal_inner: RangeMap,
	pub horizontal_outer: RangeMap,
	pub vertical_down: RangeMap,
	pub vertical_up: RangeMap,
}

#[derive(Clone, Copy, Debug)]
pub enum Tail {
	/// The joint's child node marks the end of the bone.
	Node(usize),
	/// A leaf: the end is this far from the joint, in its own space.
	Offset(Vec3),
}

#[derive(Clone, Debug)]
pub struct SpringJoint {
	pub node: usize,
	pub tail: Tail,
	pub hit_radius: f32,
	pub stiffness: f32,
	pub gravity_power: f32,
	pub gravity_dir: Vec3,
	pub drag: f32,
}

#[derive(Clone, Debug)]
pub struct Collider {
	pub node: usize,
	pub offset: Vec3,
	pub radius: f32,
	/// A capsule's other end (in the node's space); a sphere has none.
	pub tail: Option<Vec3>,
}

#[derive(Clone, Debug)]
pub struct Spring {
	pub joints: Vec<SpringJoint>,
	pub colliders: Vec<usize>,
	pub center: Option<usize>,
}

#[derive(Clone, Copy, Debug)]
pub enum Constraint {
	Rotation { source: usize, weight: f32 },
	Roll { source: usize, axis: Vec3, weight: f32 },
	Aim { source: usize, axis: Vec3, weight: f32 },
}

/// Who may use the avatar, as its maker set it (shown to the owner; the device does not enforce it).
#[derive(Clone, Debug, Default)]
pub struct Meta {
	pub name: String,
	pub authors: Vec<String>,
	pub fields: Vec<(String, String)>,
}

pub struct Model {
	/// 0 for VRM 0.x, 1 for VRM 1.0.
	pub version: u8,
	pub nodes: Vec<Node>,
	/// Parents before children.
	pub order: Vec<usize>,
	pub skins: Vec<Skin>,
	pub meshes: Vec<Mesh>,
	pub materials: Vec<Material>,
	/// glTF texture -> image.
	pub texture_images: Vec<Option<usize>>,
	pub humanoid: [Option<usize>; 55],
	pub expressions: Vec<Expression>,
	pub look_at: Option<LookAt>,
	pub springs: Vec<Spring>,
	pub colliders: Vec<Collider>,
	pub constraints: Vec<(usize, Constraint)>,
	pub meta: Meta,
	pub warnings: Vec<String>,
}

fn num(v: Option<&Value>, default: f32) -> f32 {
	v.and_then(Value::as_f64).map(|x| x as f32).unwrap_or(default)
}

fn vec3(v: Option<&Value>, default: Vec3) -> Vec3 {
	match v {
		Some(Value::Array(a)) if a.len() >= 3 => Vec3::new(num(a.first(), 0.0), num(a.get(1), 0.0), num(a.get(2), 0.0)),
		Some(Value::Object(o)) => Vec3::new(num(o.get("x"), 0.0), num(o.get("y"), 0.0), num(o.get("z"), 0.0)),
		_ => default,
	}
}

fn color(v: Option<&Value>, default: &[f32]) -> Vec<f32> {
	match v {
		Some(Value::Array(a)) => a.iter().map(|x| x.as_f64().unwrap_or(0.0) as f32).collect(),
		_ => default.to_vec(),
	}
}

/// Linear light to display values (glTF colour factors are linear; the device shades in display values).
fn srgb(c: f32) -> f32 {
	let c = c.clamp(0.0, 1.0);
	if c <= 0.0031308 {
		12.92 * c
	} else {
		1.055 * c.powf(1.0 / 2.4) - 0.055
	}
}

fn idx(v: Option<&Value>) -> Option<usize> {
	v.and_then(Value::as_i64).filter(|i| *i >= 0).map(|i| i as usize)
}

impl Model {
	pub fn read(glb: &Glb) -> Result<Model, String> {
		let ext = glb.json.get("extensions");
		let (version, vrm) = if let Some(v) = ext.and_then(|e| e.get("VRMC_vrm")) {
			(1u8, v)
		} else if let Some(v) = ext.and_then(|e| e.get("VRM")) {
			(0u8, v)
		} else {
			return Err("this glTF file is not a VRM avatar (it has no VRM information)".into());
		};
		let mut warnings = Vec::new();
		let nodes = read_nodes(glb)?;
		let order = topological(&nodes)?;
		let skins = read_skins(glb, nodes.len())?;
		let (meshes, mut mesh_warnings) = read_meshes(glb)?;
		warnings.append(&mut mesh_warnings);
		let materials = read_materials(glb, version, vrm);
		let texture_images = glb.get("textures").iter().map(|t| idx(t.get("source"))).collect();

		let mut humanoid = [None; 55];
		let bones = vrm.get("humanoid").and_then(|h| h.get("humanBones"));
		match (version, bones) {
			(1, Some(Value::Object(map))) => {
				for (name, b) in map {
					if let (Some(i), Some(node)) = (BONES.iter().position(|x| x == name), idx(b.get("node"))) {
						humanoid[i] = Some(node);
					}
				}
			}
			(0, Some(Value::Array(list))) => {
				for b in list {
					let name = bone_name_from_v0(b.get("bone").and_then(Value::as_str).unwrap_or(""));
					if let (Some(i), Some(node)) = (BONES.iter().position(|x| *x == name), idx(b.get("node"))) {
						humanoid[i] = Some(node);
					}
				}
			}
			_ => return Err("the avatar has no humanoid bone map".into()),
		}
		if let Some(missing) = (0..REQUIRED_BONES).find(|&i| humanoid[i].map_or(true, |n| n >= nodes.len())) {
			return Err(format!("the avatar has no '{}' bone, which VRM requires", BONES[missing]));
		}
		for h in humanoid.iter_mut() {
			if h.is_some_and(|n| n >= nodes.len()) {
				*h = None;
			}
		}

		let expressions = if version == 1 {
			read_expressions_v1(vrm, &nodes, meshes.len(), materials.len())
		} else {
			read_expressions_v0(vrm, &meshes, &materials)
		};
		let look_at = read_look_at(version, vrm);
		let (springs, colliders) = match version {
			1 => read_springs_v1(ext.and_then(|e| e.get("VRMC_springBone")), &nodes),
			_ => read_springs_v0(vrm.get("secondaryAnimation"), &nodes),
		};
		let constraints = read_constraints(glb, nodes.len());
		let meta = read_meta(version, vrm.get("meta"));
		Ok(Model {
			version,
			nodes,
			order,
			skins,
			meshes,
			materials,
			texture_images,
			humanoid,
			expressions,
			look_at,
			springs,
			colliders,
			constraints,
			meta,
			warnings,
		})
	}

	pub fn bone(&self, name: &str) -> Option<usize> {
		self.humanoid[bone(name)]
	}

	pub fn expression(&self, name: &str) -> Option<usize> {
		self.expressions.iter().position(|e| e.name == name)
	}

	/// The morph target with this name on any mesh: (mesh, target).
	#[allow(dead_code)]
	pub fn morphs_named(&self, name: &str) -> Vec<(usize, usize)> {
		let mut out = Vec::new();
		for (m, mesh) in self.meshes.iter().enumerate() {
			for (t, n) in mesh.target_names.iter().enumerate() {
				if n == name {
					out.push((m, t));
				}
			}
		}
		out
	}
}

fn read_nodes(glb: &Glb) -> Result<Vec<Node>, String> {
	let list = glb.get("nodes");
	if list.is_empty() || list.len() > 20_000 {
		return Err("the avatar has no nodes, or far too many".into());
	}
	let mut nodes: Vec<Node> = list
		.iter()
		.map(|n| {
			let (scale, rotation, translation) = match n.get("matrix").and_then(Value::as_array) {
				Some(m) if m.len() == 16 => {
					let cols: Vec<f32> = m.iter().map(|x| x.as_f64().unwrap_or(0.0) as f32).collect();
					Mat4::from_cols_slice(&cols).to_scale_rotation_translation()
				}
				_ => {
					let r = color(n.get("rotation"), &[0.0, 0.0, 0.0, 1.0]);
					let rotation = if r.len() == 4 { Quat::from_xyzw(r[0], r[1], r[2], r[3]).normalize() } else { Quat::IDENTITY };
					(vec3(n.get("scale"), Vec3::ONE), rotation, vec3(n.get("translation"), Vec3::ZERO))
				}
			};
			Node {
				name: n.get("name").and_then(Value::as_str).unwrap_or("").to_string(),
				parent: None,
				children: n
					.get("children")
					.and_then(Value::as_array)
					.map(|c| c.iter().filter_map(|x| x.as_u64()).map(|x| x as usize).collect())
					.unwrap_or_default(),
				translation,
				rotation: if rotation.is_finite() { rotation } else { Quat::IDENTITY },
				scale,
				mesh: idx(n.get("mesh")),
				skin: idx(n.get("skin")),
			}
		})
		.collect();
	let count = nodes.len();
	for i in 0..count {
		let children = nodes[i].children.clone();
		for c in children {
			if c >= count {
				return Err(format!("node {i} names a child that does not exist"));
			}
			if nodes[c].parent.is_some() {
				return Err(format!("node {c} has two parents"));
			}
			nodes[c].parent = Some(i);
		}
	}
	Ok(nodes)
}

fn topological(nodes: &[Node]) -> Result<Vec<usize>, String> {
	let mut order = Vec::with_capacity(nodes.len());
	let mut stack: Vec<usize> = (0..nodes.len()).filter(|&i| nodes[i].parent.is_none()).rev().collect();
	while let Some(n) = stack.pop() {
		order.push(n);
		for &c in nodes[n].children.iter().rev() {
			stack.push(c);
		}
	}
	if order.len() != nodes.len() {
		return Err("the avatar's node tree has a loop".into());
	}
	Ok(order)
}

fn read_skins(glb: &Glb, node_count: usize) -> Result<Vec<Skin>, String> {
	let mut skins = Vec::new();
	for (i, s) in glb.get("skins").iter().enumerate() {
		let joints: Vec<usize> = s
			.get("joints")
			.and_then(Value::as_array)
			.map(|j| j.iter().filter_map(|x| x.as_u64()).map(|x| x as usize).collect())
			.unwrap_or_default();
		if joints.iter().any(|&j| j >= node_count) {
			return Err(format!("skin {i} names a joint that does not exist"));
		}
		let inverse_bind = match idx(s.get("inverseBindMatrices")) {
			Some(a) => {
				let (m, n) = glb.floats(a)?;
				if n != 16 || m.len() / 16 < joints.len() {
					return Err(format!("skin {i} has too few bind matrices"));
				}
				m.chunks(16).take(joints.len()).map(Mat4::from_cols_slice).collect()
			}
			None => vec![Mat4::IDENTITY; joints.len()],
		};
		skins.push(Skin { joints, inverse_bind });
	}
	Ok(skins)
}

fn vec3s(data: &[f32]) -> Vec<Vec3> {
	data.chunks(3).map(|c| Vec3::new(c[0], c[1], c[2])).collect()
}

fn read_meshes(glb: &Glb) -> Result<(Vec<Mesh>, Vec<String>), String> {
	let mut meshes = Vec::new();
	let mut warnings = Vec::new();
	let mut total_points = 0usize;
	for (mi, m) in glb.get("meshes").iter().enumerate() {
		let mut primitives = Vec::new();
		let mut points: Vec<Points> = Vec::new();
		// The data each set of points was read from: parts naming the same data share the set.
		let mut sources: HashMap<Vec<Option<usize>>, usize> = HashMap::new();
		let mut missing_normals: Vec<bool> = Vec::new();
		let mut target_names: Vec<String> = m
			.get("extras")
			.and_then(|e| e.get("targetNames"))
			.and_then(Value::as_array)
			.map(|t| t.iter().map(|x| x.as_str().unwrap_or("").to_string()).collect())
			.unwrap_or_default();
		for (pi, p) in m.get("primitives").and_then(Value::as_array).map(Vec::as_slice).unwrap_or(&[]).iter().enumerate() {
			if p.get("mode").and_then(Value::as_u64).unwrap_or(4) != 4 {
				warnings.push(format!("mesh {mi} part {pi} is not made of triangles; it is not drawn"));
				continue;
			}
			let attrs = p.get("attributes").ok_or(format!("mesh {mi} part {pi} has no attributes"))?;
			let Some(pos) = idx(attrs.get("POSITION")) else {
				continue;
			};
			let targets_json = p.get("targets").and_then(Value::as_array).map(Vec::as_slice).unwrap_or(&[]);
			let mut key: Vec<Option<usize>> = ["POSITION", "NORMAL", "TEXCOORD_0", "JOINTS_0", "WEIGHTS_0"]
				.iter()
				.map(|a| idx(attrs.get(*a)))
				.collect();
			key.extend(targets_json.iter().map(|t| idx(t.get("POSITION"))));
			let set = match sources.get(&key) {
				Some(&set) => set,
				None => {
					let (pdata, _) = glb.floats(pos)?;
					let positions = vec3s(&pdata);
					let n = positions.len();
					total_points += n;
					if total_points > 4_000_000 {
						return Err("the avatar has far too many points to draw".into());
					}
					let normals = match idx(attrs.get("NORMAL")) {
						Some(a) => vec3s(&glb.floats(a)?.0),
						None => Vec::new(),
					};
					let uvs = match idx(attrs.get("TEXCOORD_0")) {
						Some(a) => glb.floats(a)?.0.chunks(2).map(|c| Vec2::new(c[0], c[1])).collect(),
						None => vec![Vec2::ZERO; n],
					};
					let (joints, weights) = match (idx(attrs.get("JOINTS_0")), idx(attrs.get("WEIGHTS_0"))) {
						(Some(j), Some(w)) => {
							let (jd, jn) = glb.uints(j)?;
							let (wd, wn) = glb.floats(w)?;
							if jn != 4 || wn != 4 {
								return Err(format!("mesh {mi} part {pi}: joints and weights must come in fours"));
							}
							let joints: Vec<[u16; 4]> =
								jd.chunks(4).map(|c| [c[0] as u16, c[1] as u16, c[2] as u16, c[3] as u16]).collect();
							let weights: Vec<[f32; 4]> = wd
								.chunks(4)
								.map(|c| {
									let sum = c[0] + c[1] + c[2] + c[3];
									if sum > 1e-6 {
										[c[0] / sum, c[1] / sum, c[2] / sum, c[3] / sum]
									} else {
										[1.0, 0.0, 0.0, 0.0]
									}
								})
								.collect();
							(joints, weights)
						}
						_ => (Vec::new(), Vec::new()),
					};
					if uvs.len() != n || (!normals.is_empty() && normals.len() != n) || (!joints.is_empty() && joints.len() != n) {
						return Err(format!("mesh {mi} part {pi}: its point data do not line up"));
					}
					let mut targets = Vec::new();
					for t in targets_json {
						let target = match idx(t.get("POSITION")) {
							Some(a) => match glb.sparse_vec3(a)? {
								Some((indices, values)) => Target { indices, deltas: values.into_iter().map(Vec3::from).collect() },
								None => {
									let (d, _) = glb.floats(a)?;
									let mut target = Target::default();
									for (i, c) in d.chunks(3).enumerate() {
										if c[0] != 0.0 || c[1] != 0.0 || c[2] != 0.0 {
											target.indices.push(i as u32);
											target.deltas.push(Vec3::new(c[0], c[1], c[2]));
										}
									}
									target
								}
							},
							None => Target::default(),
						};
						targets.push(target);
					}
					missing_normals.push(normals.is_empty());
					points.push(Points { positions, normals, uvs, joints, weights, targets });
					sources.insert(key, points.len() - 1);
					points.len() - 1
				}
			};
			let n = points[set].positions.len();
			let indices = match idx(p.get("indices")) {
				Some(a) => glb.uints(a)?.0,
				None => (0..n as u32).collect(),
			};
			if indices.iter().any(|&i| i as usize >= n) {
				return Err(format!("mesh {mi} part {pi} names a point that does not exist"));
			}
			if target_names.is_empty() {
				if let Some(names) = p.get("extras").and_then(|e| e.get("targetNames")).and_then(Value::as_array) {
					target_names = names.iter().map(|x| x.as_str().unwrap_or("").to_string()).collect();
				}
			}
			primitives.push(Primitive { points: set, indices, material: idx(p.get("material")) });
		}
		// Normals worked out from every part's triangles, for sets that came without them.
		for (set, missing) in missing_normals.iter().enumerate() {
			if *missing {
				let triangles: Vec<u32> =
					primitives.iter().filter(|p| p.points == set).flat_map(|p| p.indices.iter().copied()).collect();
				points[set].normals = flat_normals(&points[set].positions, &triangles);
			}
		}
		meshes.push(Mesh {
			name: m.get("name").and_then(Value::as_str).unwrap_or("").to_string(),
			points,
			primitives,
			target_names,
		});
	}
	Ok((meshes, warnings))
}

/// Normals for a mesh that came without them: each point gets the average of its triangles'.
fn flat_normals(positions: &[Vec3], indices: &[u32]) -> Vec<Vec3> {
	let mut normals = vec![Vec3::ZERO; positions.len()];
	for t in indices.chunks(3) {
		if t.len() < 3 {
			break;
		}
		let (a, b, c) = (positions[t[0] as usize], positions[t[1] as usize], positions[t[2] as usize]);
		let n = (b - a).cross(c - a);
		for &i in t {
			normals[i as usize] += n;
		}
	}
	normals.iter().map(|n| n.try_normalize().unwrap_or(Vec3::Y)).collect()
}

fn texref(v: Option<&Value>) -> Option<TexRef> {
	let v = v?;
	let texture = idx(v.get("index"))?;
	let t = v.get("extensions").and_then(|e| e.get("KHR_texture_transform"));
	let offset = t.and_then(|t| t.get("offset")).and_then(Value::as_array).map(|o| Vec2::new(num(o.first(), 0.0), num(o.get(1), 0.0)));
	let scale = t.and_then(|t| t.get("scale")).and_then(Value::as_array).map(|o| Vec2::new(num(o.first(), 1.0), num(o.get(1), 1.0)));
	Some(TexRef { texture, offset: offset.unwrap_or(Vec2::ZERO), scale: scale.unwrap_or(Vec2::ONE) })
}

fn read_materials(glb: &Glb, version: u8, vrm: &Value) -> Vec<Material> {
	let props = vrm.get("materialProperties").and_then(Value::as_array);
	glb.get("materials")
		.iter()
		.enumerate()
		.map(|(i, m)| {
			let mut out = Material { name: m.get("name").and_then(Value::as_str).unwrap_or("").to_string(), ..Default::default() };
			let pbr = m.get("pbrMetallicRoughness");
			let base = color(pbr.and_then(|p| p.get("baseColorFactor")), &[1.0, 1.0, 1.0, 1.0]);
			if base.len() == 4 {
				out.base = [srgb(base[0]), srgb(base[1]), srgb(base[2]), base[3]];
			}
			out.base_texture = texref(pbr.and_then(|p| p.get("baseColorTexture")));
			let e = color(m.get("emissiveFactor"), &[0.0, 0.0, 0.0]);
			let strength = num(m.get("extensions").and_then(|x| x.get("KHR_materials_emissive_strength")).and_then(|x| x.get("emissiveStrength")), 1.0);
			if e.len() == 3 {
				out.emissive = [srgb(e[0] * strength), srgb(e[1] * strength), srgb(e[2] * strength)];
			}
			out.emissive_texture = texref(m.get("emissiveTexture"));
			out.alpha = match m.get("alphaMode").and_then(Value::as_str).unwrap_or("OPAQUE") {
				"MASK" => AlphaMode::Mask(num(m.get("alphaCutoff"), 0.5)),
				"BLEND" => AlphaMode::Blend,
				_ => AlphaMode::Opaque,
			};
			out.zwrite = out.alpha != AlphaMode::Blend;
			out.double_sided = m.get("doubleSided").and_then(Value::as_bool).unwrap_or(false);
			out.unlit = m.get("extensions").and_then(|x| x.get("KHR_materials_unlit")).is_some();
			if let Some(t) = m.get("extensions").and_then(|x| x.get("VRMC_materials_mtoon")) {
				out.mtoon = true;
				out.unlit = false;
				let s = color(t.get("shadeColorFactor"), &[1.0, 1.0, 1.0]);
				if s.len() >= 3 {
					out.shade = [srgb(s[0]), srgb(s[1]), srgb(s[2])];
				}
				out.shade_texture = texref(t.get("shadeMultiplyTexture"));
				out.shading_shift = num(t.get("shadingShiftFactor"), 0.0);
				out.shading_toony = num(t.get("shadingToonyFactor"), 0.9);
				let r = color(t.get("parametricRimColorFactor"), &[0.0, 0.0, 0.0]);
				if r.len() >= 3 {
					out.rim = [srgb(r[0]), srgb(r[1]), srgb(r[2])];
				}
				out.rim_power = num(t.get("parametricRimFresnelPowerFactor"), 5.0);
				out.rim_lift = num(t.get("parametricRimLiftFactor"), 0.0);
				out.rim_mix = num(t.get("rimLightingMixFactor"), 1.0);
				out.outline_mode = match t.get("outlineWidthMode").and_then(Value::as_str).unwrap_or("none") {
					"worldCoordinates" => OutlineMode::World,
					"screenCoordinates" => OutlineMode::Screen,
					_ => OutlineMode::None,
				};
				out.outline_width = num(t.get("outlineWidthFactor"), 0.0);
				let o = color(t.get("outlineColorFactor"), &[0.0, 0.0, 0.0]);
				if o.len() >= 3 {
					out.outline_color = [srgb(o[0]), srgb(o[1]), srgb(o[2])];
				}
				out.outline_mix = num(t.get("outlineLightingMixFactor"), 1.0);
				if out.alpha == AlphaMode::Blend {
					out.zwrite = t.get("transparentWithZWrite").and_then(Value::as_bool).unwrap_or(false);
				}
				out.queue = num(t.get("renderQueueOffsetNumber"), 0.0) as i32;
			} else if version == 0 {
				if let Some(p) = props.and_then(|ps| {
					ps.iter().find(|p| p.get("name").and_then(Value::as_str) == Some(out.name.as_str())).or_else(|| ps.get(i))
				}) {
					read_mtoon_v0(p, &mut out);
				}
			}
			out
		})
		.collect()
}

/// A VRM 0.x material's MToon settings (Unity material properties).
fn read_mtoon_v0(p: &Value, out: &mut Material) {
	let shader = p.get("shader").and_then(Value::as_str).unwrap_or("");
	let floats = p.get("floatProperties");
	let vectors = p.get("vectorProperties");
	let textures = p.get("textureProperties");
	let f = |k: &str, d: f32| num(floats.and_then(|x| x.get(k)), d);
	let v = |k: &str| vectors.and_then(|x| x.get(k)).and_then(Value::as_array).map(|a| a.iter().map(|x| x.as_f64().unwrap_or(0.0) as f32).collect::<Vec<_>>());
	let t = |k: &str| textures.and_then(|x| x.get(k)).and_then(Value::as_u64).map(|i| TexRef { texture: i as usize, offset: Vec2::ZERO, scale: Vec2::ONE });
	if shader == "VRM/MToon" {
		out.mtoon = true;
		out.unlit = false;
		// Unity's colour properties are display values already.
		if let Some(c) = v("_Color").filter(|c| c.len() >= 4) {
			out.base = [c[0], c[1], c[2], c[3]];
		}
		if let Some(c) = v("_ShadeColor").filter(|c| c.len() >= 3) {
			out.shade = [c[0], c[1], c[2]];
		}
		if let Some(c) = v("_EmissionColor").filter(|c| c.len() >= 3) {
			out.emissive = [c[0], c[1], c[2]];
		}
		if let Some(c) = v("_RimColor").filter(|c| c.len() >= 3) {
			out.rim = [c[0], c[1], c[2]];
		}
		if let Some(c) = v("_OutlineColor").filter(|c| c.len() >= 3) {
			out.outline_color = [c[0], c[1], c[2]];
		}
		if let Some(st) = v("_MainTex").filter(|c| c.len() >= 4) {
			// UniVRM writes the main texture's placement as offset x, y then scale x, y, in Unity's
			// terms (V counted from the bottom); turned here into glTF's (V from the top).
			let tex = out.base_texture.get_or_insert(TexRef { texture: usize::MAX, offset: Vec2::ZERO, scale: Vec2::ONE });
			tex.scale = Vec2::new(st[2], st[3]);
			tex.offset = Vec2::new(st[0], 1.0 - st[3] - st[1]);
		}
		if let Some(tex) = t("_MainTex") {
			let mut tex = tex;
			if let Some(old) = out.base_texture {
				tex.offset = old.offset;
				tex.scale = old.scale;
			}
			out.base_texture = Some(tex);
		}
		if out.base_texture.is_some_and(|t| t.texture == usize::MAX) {
			out.base_texture = None;
		}
		out.shade_texture = t("_ShadeTexture");
		out.emissive_texture = t("_EmissionMap");
		// MToon 0.x shading, turned into 1.0's: 0.x shades with smoothstep(shift, shift + 1 - toony, N.L),
		// 1.0 with linearstep(-1 + toony', 1 - toony', N.L + shift'); these make the two edges meet.
		let shift = f("_ShadeShift", 0.0);
		let toony = f("_ShadeToony", 0.9).clamp(0.0, 1.0);
		out.shading_toony = (1.0 + toony) * 0.5;
		out.shading_shift = -shift - (1.0 - toony) * 0.5;
		out.rim_power = f("_RimFresnelPower", 1.0);
		out.rim_lift = f("_RimLift", 0.0);
		out.rim_mix = f("_RimLightingMix", 0.0);
		out.outline_mode = match f("_OutlineWidthMode", 0.0) as i32 {
			1 => OutlineMode::World,
			2 => OutlineMode::Screen,
			_ => OutlineMode::None,
		};
		// 0.x widths are in centimetres (world) or a share of the screen times 100.
		out.outline_width = f("_OutlineWidth", 0.0) * 0.01;
		out.outline_mix = f("_OutlineLightingMix", 1.0);
		let blend = f("_BlendMode", 0.0) as i32;
		out.alpha = match blend {
			1 => AlphaMode::Mask(f("_Cutoff", 0.5)),
			2 | 3 => AlphaMode::Blend,
			_ => AlphaMode::Opaque,
		};
		out.zwrite = blend != 2;
		out.double_sided = f("_CullMode", 2.0) as i32 == 0;
		out.queue = p.get("renderQueue").and_then(Value::as_i64).unwrap_or(2000) as i32 - if blend >= 2 { 3000 } else { 2000 };
	} else if shader.starts_with("VRM/Unlit") || shader.starts_with("UniGLTF/Unlit") {
		out.unlit = true;
		if shader.contains("Cutout") {
			out.alpha = AlphaMode::Mask(f("_Cutoff", 0.5));
		} else if shader.contains("Transparent") {
			out.alpha = AlphaMode::Blend;
			out.zwrite = shader.contains("ZWrite");
		}
	}
}

fn read_expressions_v1(vrm: &Value, nodes: &[Node], mesh_count: usize, material_count: usize) -> Vec<Expression> {
	let mut out = Vec::new();
	let ex = vrm.get("expressions");
	let mut add = |name: String, preset: Option<&'static str>, e: &Value| {
		let mut morphs = Vec::new();
		for b in e.get("morphTargetBinds").and_then(Value::as_array).map(Vec::as_slice).unwrap_or(&[]) {
			if let (Some(node), Some(index)) = (idx(b.get("node")), idx(b.get("index"))) {
				if let Some(mesh) = nodes.get(node).and_then(|n| n.mesh).filter(|m| *m < mesh_count) {
					morphs.push((mesh, index, num(b.get("weight"), 1.0).clamp(0.0, 1.0)));
				}
			}
		}
		let mut colors = Vec::new();
		for b in e.get("materialColorBinds").and_then(Value::as_array).map(Vec::as_slice).unwrap_or(&[]) {
			let kind = match b.get("type").and_then(Value::as_str).unwrap_or("") {
				"color" => ColorKind::Base,
				"shadeColor" => ColorKind::Shade,
				"emissionColor" => ColorKind::Emission,
				"rimColor" => ColorKind::Rim,
				"outlineColor" => ColorKind::Outline,
				_ => continue,
			};
			if let Some(m) = idx(b.get("material")).filter(|m| *m < material_count) {
				let c = color(b.get("targetValue"), &[0.0, 0.0, 0.0, 1.0]);
				if c.len() >= 3 {
					colors.push((m, kind, [srgb(c[0]), srgb(c[1]), srgb(c[2]), c.get(3).copied().unwrap_or(1.0)]));
				}
			}
		}
		let mut uv = Vec::new();
		for b in e.get("textureTransformBinds").and_then(Value::as_array).map(Vec::as_slice).unwrap_or(&[]) {
			if let Some(m) = idx(b.get("material")).filter(|m| *m < material_count) {
				let s = color(b.get("scale"), &[1.0, 1.0]);
				let o = color(b.get("offset"), &[0.0, 0.0]);
				uv.push((m, Vec2::new(s[0], *s.get(1).unwrap_or(&1.0)), Vec2::new(o[0], *o.get(1).unwrap_or(&0.0))));
			}
		}
		let ov = |k: &str| match e.get(k).and_then(Value::as_str).unwrap_or("none") {
			"block" => Override::Block,
			"blend" => Override::Blend,
			_ => Override::None,
		};
		out.push(Expression {
			name,
			preset,
			binary: e.get("isBinary").and_then(Value::as_bool).unwrap_or(false),
			morphs,
			colors,
			uv,
			override_blink: ov("overrideBlink"),
			override_look_at: ov("overrideLookAt"),
			override_mouth: ov("overrideMouth"),
		});
	};
	if let Some(Value::Object(presets)) = ex.and_then(|x| x.get("preset")) {
		for (name, preset) in PRESETS.iter().map(|(n, _)| *n).filter_map(|n| presets.get(n).map(|e| (n, e))) {
			add(name.to_string(), Some(name), preset);
		}
	}
	if let Some(Value::Object(custom)) = ex.and_then(|x| x.get("custom")) {
		for (name, e) in custom {
			if !PRESETS.iter().any(|(n, _)| n == name) {
				add(name.clone(), None, e);
			}
		}
	}
	out
}

fn read_expressions_v0(vrm: &Value, meshes: &[Mesh], materials: &[Material]) -> Vec<Expression> {
	let mut out: Vec<Expression> = Vec::new();
	let groups = vrm.get("blendShapeMaster").and_then(|b| b.get("blendShapeGroups")).and_then(Value::as_array);
	for g in groups.map(Vec::as_slice).unwrap_or(&[]) {
		let preset_v0 = g.get("presetName").and_then(Value::as_str).unwrap_or("unknown").to_lowercase();
		let preset = PRESETS.iter().find(|(_, v0)| *v0 == preset_v0).map(|(v1, _)| *v1);
		let name = match preset {
			Some(p) => p.to_string(),
			None => g.get("name").and_then(Value::as_str).unwrap_or("").to_string(),
		};
		if name.is_empty() || out.iter().any(|e| e.name == name) {
			continue;
		}
		let mut morphs = Vec::new();
		for b in g.get("binds").and_then(Value::as_array).map(Vec::as_slice).unwrap_or(&[]) {
			if let (Some(mesh), Some(index)) = (idx(b.get("mesh")), idx(b.get("index"))) {
				if mesh < meshes.len() {
					morphs.push((mesh, index, (num(b.get("weight"), 100.0) / 100.0).clamp(0.0, 1.0)));
				}
			}
		}
		let mut colors = Vec::new();
		let mut uv = Vec::new();
		for mv in g.get("materialValues").and_then(Value::as_array).map(Vec::as_slice).unwrap_or(&[]) {
			let mat = mv.get("materialName").and_then(Value::as_str).unwrap_or("");
			let Some(m) = materials.iter().position(|x| x.name == mat) else {
				continue;
			};
			let target = color(mv.get("targetValue"), &[0.0, 0.0, 0.0, 1.0]);
			let kind = match mv.get("propertyName").and_then(Value::as_str).unwrap_or("") {
				"_Color" => Some(ColorKind::Base),
				"_ShadeColor" => Some(ColorKind::Shade),
				"_EmissionColor" => Some(ColorKind::Emission),
				"_RimColor" => Some(ColorKind::Rim),
				"_OutlineColor" => Some(ColorKind::Outline),
				"_MainTex_ST" if target.len() >= 4 => {
					uv.push((m, Vec2::new(target[0], target[1]), Vec2::new(target[2], target[3])));
					None
				}
				_ => None,
			};
			if let Some(kind) = kind {
				if target.len() >= 3 {
					colors.push((m, kind, [target[0], target[1], target[2], target.get(3).copied().unwrap_or(1.0)]));
				}
			}
		}
		// 0.x had no override settings; emotions hid blinking in practice, so block blinking for them.
		let emotion = matches!(preset, Some("happy" | "angry" | "sad" | "relaxed" | "surprised"));
		out.push(Expression {
			name,
			preset,
			binary: g.get("isBinary").and_then(Value::as_bool).unwrap_or(false),
			morphs,
			colors,
			uv,
			override_blink: if emotion { Override::Blend } else { Override::None },
			override_look_at: Override::None,
			override_mouth: Override::None,
		});
	}
	out
}

fn range(v: Option<&Value>, input: &str, output: &str, default_out: f32) -> RangeMap {
	RangeMap { input_max: num(v.and_then(|x| x.get(input)), 90.0).max(1e-3), output_scale: num(v.and_then(|x| x.get(output)), default_out) }
}

fn read_look_at(version: u8, vrm: &Value) -> Option<LookAt> {
	if version == 1 {
		let l = vrm.get("lookAt")?;
		let bones = l.get("type").and_then(Value::as_str).unwrap_or("bone") == "bone";
		let d = if bones { 10.0 } else { 1.0 };
		Some(LookAt {
			bones,
			offset: vec3(l.get("offsetFromHeadBone"), Vec3::ZERO),
			horizontal_inner: range(l.get("rangeMapHorizontalInner"), "inputMaxValue", "outputScale", d),
			horizontal_outer: range(l.get("rangeMapHorizontalOuter"), "inputMaxValue", "outputScale", d),
			vertical_down: range(l.get("rangeMapVerticalDown"), "inputMaxValue", "outputScale", d),
			vertical_up: range(l.get("rangeMapVerticalUp"), "inputMaxValue", "outputScale", d),
		})
	} else {
		let f = vrm.get("firstPerson")?;
		let bones = f.get("lookAtTypeName").and_then(Value::as_str).unwrap_or("Bone") == "Bone";
		let d = if bones { 10.0 } else { 1.0 };
		Some(LookAt {
			bones,
			offset: vec3(f.get("firstPersonBoneOffset"), Vec3::ZERO),
			horizontal_inner: range(f.get("lookAtHorizontalInner"), "xRange", "yRange", d),
			horizontal_outer: range(f.get("lookAtHorizontalOuter"), "xRange", "yRange", d),
			vertical_down: range(f.get("lookAtVerticalDown"), "xRange", "yRange", d),
			vertical_up: range(f.get("lookAtVerticalUp"), "xRange", "yRange", d),
		})
	}
}

fn read_springs_v1(ext: Option<&Value>, nodes: &[Node]) -> (Vec<Spring>, Vec<Collider>) {
	let Some(ext) = ext else {
		return (Vec::new(), Vec::new());
	};
	let ok = |n: Option<usize>| n.filter(|n| *n < nodes.len());
	let colliders: Vec<Collider> = ext
		.get("colliders")
		.and_then(Value::as_array)
		.map(Vec::as_slice)
		.unwrap_or(&[])
		.iter()
		.filter_map(|c| {
			let node = ok(idx(c.get("node")))?;
			let shape = c.get("shape")?;
			if let Some(s) = shape.get("sphere") {
				Some(Collider { node, offset: vec3(s.get("offset"), Vec3::ZERO), radius: num(s.get("radius"), 0.0), tail: None })
			} else {
				shape.get("capsule").map(|s| Collider {
					node,
					offset: vec3(s.get("offset"), Vec3::ZERO),
					radius: num(s.get("radius"), 0.0),
					tail: Some(vec3(s.get("tail"), Vec3::ZERO)),
				})
			}
		})
		.collect();
	let groups: Vec<Vec<usize>> = ext
		.get("colliderGroups")
		.and_then(Value::as_array)
		.map(Vec::as_slice)
		.unwrap_or(&[])
		.iter()
		.map(|g| {
			g.get("colliders")
				.and_then(Value::as_array)
				.map(|c| c.iter().filter_map(|x| x.as_u64()).map(|x| x as usize).filter(|i| *i < colliders.len()).collect())
				.unwrap_or_default()
		})
		.collect();
	let mut springs = Vec::new();
	for s in ext.get("springs").and_then(Value::as_array).map(Vec::as_slice).unwrap_or(&[]) {
		let list: Vec<&Value> = s.get("joints").and_then(Value::as_array).map(|j| j.iter().collect()).unwrap_or_default();
		let mut joints = Vec::new();
		for pair in list.windows(2) {
			let (Some(node), Some(next)) = (ok(idx(pair[0].get("node"))), ok(idx(pair[1].get("node")))) else {
				continue;
			};
			if nodes[next].parent != Some(node) {
				continue; // joints must be a chain of parent and child
			}
			let j = pair[0];
			joints.push(SpringJoint {
				node,
				tail: Tail::Node(next),
				hit_radius: num(j.get("hitRadius"), 0.0),
				stiffness: num(j.get("stiffness"), 1.0),
				gravity_power: num(j.get("gravityPower"), 0.0),
				gravity_dir: vec3(j.get("gravityDir"), Vec3::NEG_Y).try_normalize().unwrap_or(Vec3::NEG_Y),
				drag: num(j.get("dragForce"), 0.5).clamp(0.0, 1.0),
			});
		}
		if joints.is_empty() {
			continue;
		}
		let mut cols = Vec::new();
		for g in s.get("colliderGroups").and_then(Value::as_array).map(Vec::as_slice).unwrap_or(&[]) {
			if let Some(group) = g.as_u64().and_then(|g| groups.get(g as usize)) {
				cols.extend_from_slice(group);
			}
		}
		springs.push(Spring { joints, colliders: cols, center: ok(idx(s.get("center"))) });
	}
	(springs, colliders)
}

fn read_springs_v0(sec: Option<&Value>, nodes: &[Node]) -> (Vec<Spring>, Vec<Collider>) {
	let Some(sec) = sec else {
		return (Vec::new(), Vec::new());
	};
	let ok = |n: Option<usize>| n.filter(|n| *n < nodes.len());
	let mut colliders = Vec::new();
	let mut groups = Vec::new();
	for g in sec.get("colliderGroups").and_then(Value::as_array).map(Vec::as_slice).unwrap_or(&[]) {
		let mut members = Vec::new();
		if let Some(node) = ok(idx(g.get("node"))) {
			for c in g.get("colliders").and_then(Value::as_array).map(Vec::as_slice).unwrap_or(&[]) {
				let o = vec3(c.get("offset"), Vec3::ZERO);
				// VRM 0.x stored offsets with z the other way round.
				members.push(colliders.len());
				colliders.push(Collider { node, offset: Vec3::new(o.x, o.y, -o.z), radius: num(c.get("radius"), 0.0), tail: None });
			}
		}
		groups.push(members);
	}
	let mut springs = Vec::new();
	for g in sec.get("boneGroups").and_then(Value::as_array).map(Vec::as_slice).unwrap_or(&[]) {
		let gd = vec3(g.get("gravityDir"), Vec3::NEG_Y);
		let settings = (
			num(g.get("hitRadius"), 0.02),
			num(g.get("stiffiness").or(g.get("stiffness")), 1.0),
			num(g.get("gravityPower"), 0.0),
			Vec3::new(gd.x, gd.y, -gd.z).try_normalize().unwrap_or(Vec3::NEG_Y),
			num(g.get("dragForce"), 0.4).clamp(0.0, 1.0),
		);
		let mut cols = Vec::new();
		for c in g.get("colliderGroups").and_then(Value::as_array).map(Vec::as_slice).unwrap_or(&[]) {
			if let Some(group) = c.as_u64().and_then(|c| groups.get(c as usize)) {
				cols.extend_from_slice(group);
			}
		}
		for root in g.get("bones").and_then(Value::as_array).map(Vec::as_slice).unwrap_or(&[]) {
			let Some(root) = ok(idx(Some(root))) else {
				continue;
			};
			// Every node under the root swings, each towards its first child (a leaf a little past itself).
			let mut joints = Vec::new();
			let mut stack = vec![root];
			while let Some(n) = stack.pop() {
				let tail = match nodes[n].children.first() {
					Some(&c) => Tail::Node(c),
					None => Tail::Offset(nodes[n].translation.try_normalize().unwrap_or(Vec3::NEG_Y) * 0.07),
				};
				joints.push(SpringJoint {
					node: n,
					tail,
					hit_radius: settings.0,
					stiffness: settings.1,
					gravity_power: settings.2,
					gravity_dir: settings.3,
					drag: settings.4,
				});
				for &c in nodes[n].children.iter().rev() {
					stack.push(c);
				}
			}
			springs.push(Spring { joints, colliders: cols.clone(), center: ok(idx(g.get("center"))) });
		}
	}
	(springs, colliders)
}

fn axis(name: &str) -> Vec3 {
	match name {
		"X" | "PositiveX" => Vec3::X,
		"Y" | "PositiveY" => Vec3::Y,
		"Z" | "PositiveZ" => Vec3::Z,
		"NegativeX" => Vec3::NEG_X,
		"NegativeY" => Vec3::NEG_Y,
		"NegativeZ" => Vec3::NEG_Z,
		_ => Vec3::X,
	}
}

fn read_constraints(glb: &Glb, count: usize) -> Vec<(usize, Constraint)> {
	let mut out = Vec::new();
	for (i, n) in glb.get("nodes").iter().enumerate() {
		let Some(c) = n.get("extensions").and_then(|e| e.get("VRMC_node_constraint")).and_then(|e| e.get("constraint")) else {
			continue;
		};
		let source = |v: &Value| idx(v.get("source")).filter(|s| *s < count && *s != i);
		if let Some(r) = c.get("rotation") {
			if let Some(source) = source(r) {
				out.push((i, Constraint::Rotation { source, weight: num(r.get("weight"), 1.0) }));
			}
		} else if let Some(r) = c.get("roll") {
			if let Some(source) = source(r) {
				let a = axis(r.get("rollAxis").and_then(Value::as_str).unwrap_or("X"));
				out.push((i, Constraint::Roll { source, axis: a, weight: num(r.get("weight"), 1.0) }));
			}
		} else if let Some(r) = c.get("aim") {
			if let Some(source) = source(r) {
				let a = axis(r.get("aimAxis").and_then(Value::as_str).unwrap_or("PositiveX"));
				out.push((i, Constraint::Aim { source, axis: a, weight: num(r.get("weight"), 1.0) }));
			}
		}
	}
	out
}

fn read_meta(version: u8, meta: Option<&Value>) -> Meta {
	let Some(m) = meta else {
		return Meta::default();
	};
	let text = |k: &str| m.get(k).and_then(Value::as_str).map(str::to_string);
	let mut out = Meta::default();
	if version == 1 {
		out.name = text("name").unwrap_or_default();
		out.authors = m.get("authors").and_then(Value::as_array).map(|a| a.iter().filter_map(|x| x.as_str().map(str::to_string)).collect()).unwrap_or_default();
		for k in ["licenseUrl", "avatarPermission", "commercialUsage", "allowRedistribution", "modification", "creditNotation"] {
			if let Some(v) = m.get(k) {
				out.fields.push((k.to_string(), v.as_str().map(str::to_string).unwrap_or_else(|| v.to_string())));
			}
		}
	} else {
		out.name = text("title").unwrap_or_default();
		out.authors = text("author").into_iter().collect();
		for k in ["licenseName", "otherPermissionUrl", "allowedUserName", "commercialUssageName", "violentUssageName", "sexualUssageName"] {
			if let Some(v) = m.get(k) {
				out.fields.push((k.to_string(), v.as_str().map(str::to_string).unwrap_or_else(|| v.to_string())));
			}
		}
	}
	out
}

/// Morph targets by name, with the names of a VRoid Studio face (the most common source of avatars):
/// separate mouth, eye and brow shapes the device can use for smiles and brows.
pub fn index_names(model: &Model) -> HashMap<String, Vec<(usize, usize)>> {
	let mut map: HashMap<String, Vec<(usize, usize)>> = HashMap::new();
	for (m, mesh) in model.meshes.iter().enumerate() {
		for (t, n) in mesh.target_names.iter().enumerate() {
			map.entry(n.clone()).or_default().push((m, t));
		}
	}
	map
}
