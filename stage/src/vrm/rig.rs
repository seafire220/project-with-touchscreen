//! Posing a VRM avatar from the stage's controls.
//!
//! Every VRM is in a T-pose at rest, but its bones' own axes differ from model to model. Poses here
//! are written once, in the *normalised* humanoid: the T-pose with every bone's axes along the
//! world's (x towards the avatar's left, y up, z towards the viewer), as VRM 1.0 defines it. A bone
//! given rotation `q` there turns by `q` in world terms on top of its parent's turn, whatever its
//! own axes; that is what lets the same waves and nods fit any avatar.

use glam::{Mat4, Quat, Vec2, Vec3};

use super::model::{bone, Constraint, Model};

/// What the stage asks of the avatar this frame, in the units of the stage's controls.
#[derive(Clone, Copy, Debug, Default, PartialEq)]
pub struct Controls {
	/// Head turn: yaw (towards the viewer's right), pitch (up), roll, in degrees.
	pub head: Vec3,
	/// A wide turn, to look beside or behind, in degrees (up to 90, a profile), the same way as the
	/// head's yaw: shared between the head, the neck and the chest, as a person turns to look aside.
	pub turn: f32,
	/// Body turn, the same way, in degrees.
	pub body: Vec3,
	pub breath: f32,
	/// Where the eyes look, -1 to 1 (right and up are positive).
	pub gaze: Vec2,
	/// How open each eye is, 0 to 1 (avatar's left, right).
	pub eye_open: [f32; 2],
	pub eye_smile: [f32; 2],
	pub mouth_open: f32,
	/// -1 (frown) to 1 (smile).
	pub mouth_form: f32,
	/// a, i, u, e, o.
	pub vowels: [f32; 5],
	pub brows: [f32; 2],
	pub brow_form: [f32; 2],
	pub cheek: f32,
	/// Each arm at the shoulder (A) and the elbow (B), -1 to 1, avatar's left then right.
	pub arm_a: [f32; 2],
	pub arm_b: [f32; 2],
	pub shoulders: f32,
}

impl Controls {
	pub fn rest() -> Self {
		Controls { eye_open: [1.0, 1.0], ..Default::default() }
	}
}

/// How the arms hang at rest: this far out from the body (degrees from straight down).
const REST_ABDUCTION: f32 = 11.0;
/// How far a raised arm (A = 1) goes beyond rest, and a lowered one (A = -1).
const RAISE: f32 = 72.0;
const LOWER: f32 = 10.0;
/// The elbow: forearm up (B = 1) and folded back to the hip (B = -1), and a slight bend at rest.
const FLEX_UP: f32 = 140.0;
const FLEX_IN: f32 = 122.0;
const REST_BEND: f32 = 12.0;

fn deg(d: f32) -> f32 {
	d.to_radians()
}

fn smoothstep(a: f32, b: f32, x: f32) -> f32 {
	let t = ((x - a) / (b - a)).clamp(0.0, 1.0);
	t * t * (3.0 - 2.0 * t)
}

/// Turn by yaw (about y), then pitch (about x; positive looks up), then roll (about z).
fn turn(yaw: f32, pitch: f32, roll: f32) -> Quat {
	Quat::from_rotation_y(deg(yaw)) * Quat::from_rotation_x(deg(-pitch)) * Quat::from_rotation_z(deg(roll))
}

/// The normalised pose for these controls: one rotation per humanoid bone.
pub fn normalised_pose(model: &Model, c: &Controls) -> [Quat; 55] {
	let mut q = [Quat::IDENTITY; 55];
	let has = |name: &str| model.bone(name).is_some();

	// Body: shared between the spine, chest and upper chest, as a person bends.
	let shares: [(&str, f32); 3] = match (has("chest"), has("upperChest")) {
		(true, true) => [("spine", 0.4), ("chest", 0.3), ("upperChest", 0.3)],
		(true, false) => [("spine", 0.5), ("chest", 0.5), ("upperChest", 0.0)],
		_ => [("spine", 1.0), ("chest", 0.0), ("upperChest", 0.0)],
	};
	for (name, share) in shares {
		if share > 0.0 {
			q[bone(name)] = turn(c.body.x * share, c.body.y * share, -c.body.z * share);
		}
	}
	// Breathing: the chest lifts a little.
	let chest = if has("upperChest") { "upperChest" } else if has("chest") { "chest" } else { "spine" };
	q[bone(chest)] = q[bone(chest)] * Quat::from_rotation_x(deg(-1.8 * c.breath));

	// A wide turn: a quarter of it in the chest and spine (a person turns the shoulders to look far
	// aside), the rest in the neck and head.
	let wide = c.turn.clamp(-90.0, 90.0);
	if wide != 0.0 {
		let torso: [(&str, f32); 3] = match (has("chest"), has("upperChest")) {
			(true, true) => [("spine", 0.07), ("chest", 0.08), ("upperChest", 0.10)],
			(true, false) => [("spine", 0.10), ("chest", 0.15), ("upperChest", 0.0)],
			_ => [("spine", 0.25), ("chest", 0.0), ("upperChest", 0.0)],
		};
		for (name, share) in torso {
			if share > 0.0 {
				q[bone(name)] = Quat::from_rotation_y(deg(wide * share)) * q[bone(name)];
			}
		}
	}
	let wide = wide * 0.75;

	// Head: the neck takes a third of each turn when there is one (and 40% of a wide one).
	let neck_share = if has("neck") { 0.35 } else { 0.0 };
	let neck_wide = if has("neck") { 0.4 } else { 0.0 };
	if neck_share > 0.0 {
		q[bone("neck")] = turn(c.head.x * neck_share + wide * neck_wide, c.head.y * neck_share, -c.head.z * neck_share);
	}
	let h = 1.0 - neck_share;
	q[bone("head")] = turn(c.head.x * h + wide * (1.0 - neck_wide), c.head.y * h, -c.head.z * h);

	// Shoulders up for a shrug (and a touch with each breath).
	let lift = c.shoulders.clamp(-1.0, 1.0) * 14.0 + c.breath * 1.5;
	q[bone("leftShoulder")] = Quat::from_rotation_z(deg(lift));
	q[bone("rightShoulder")] = Quat::from_rotation_z(deg(-lift));

	// Arms, in the body's front plane like the picture characters' (so the same gestures fit),
	// with a slight forward bend at the elbow when resting.
	for (i, side) in ["left", "right"].iter().enumerate() {
		let s = if i == 0 { 1.0 } else { -1.0 };
		let a = c.arm_a[i].clamp(-1.0, 1.0);
		let b = c.arm_b[i].clamp(-1.0, 1.0);
		let abduction = REST_ABDUCTION + if a >= 0.0 { a * RAISE } else { a * LOWER };
		let forward = if a < 0.0 { -a * 25.0 } else { 0.0 };
		q[bone(&format!("{side}UpperArm"))] = Quat::from_rotation_x(deg(-forward)) * Quat::from_rotation_z(deg(s * (abduction - 90.0)));
		// The elbow. Folding back (B < 0) stays in the front plane: a hand on the hip. Raising it
		// (B > 0) bends the forearm forward, towards the viewer, for small amounts (a shrug's open
		// hands) and swings it up beside the head for large ones (a wave), where a 3D arm can do what
		// a flat picture's cannot.
		let lower = if b >= 0.0 {
			let up = smoothstep(0.45, 0.65, b);
			let forward = Quat::from_rotation_y(deg(-s * (b / 0.45).min(1.0) * 80.0));
			let frontal = Quat::from_rotation_z(deg(s * b * FLEX_UP));
			forward.slerp(frontal, up)
		} else {
			Quat::from_rotation_z(deg(s * b * FLEX_IN))
		};
		let bend = REST_BEND * (1.0 - b.abs()).max(0.0);
		q[bone(&format!("{side}LowerArm"))] = lower * Quat::from_rotation_y(deg(-s * bend));
		// A waving hand turns its palm to the viewer and opens.
		let wave = if b > 0.0 { smoothstep(0.5, 0.75, b) } else { 0.0 };
		q[bone(&format!("{side}Hand"))] = Quat::from_rotation_x(deg(-80.0 * wave));
		// Fingers curled a little, as a relaxed hand is; the outer fingers more.
		let open = 1.0 - 0.85 * wave;
		for (finger, curl) in [("Index", 9.0), ("Middle", 12.0), ("Ring", 15.0), ("Little", 18.0)] {
			for (joint, share) in [("Proximal", 1.0), ("Intermediate", 1.4), ("Distal", 1.0)] {
				q[bone(&format!("{side}{finger}{joint}"))] = Quat::from_rotation_z(deg(-s * curl * share * open));
			}
		}
		q[bone(&format!("{side}ThumbProximal"))] = Quat::from_rotation_y(deg(-s * 12.0 * open));
	}
	q
}

/// The avatar's skeleton, posed.
pub struct Rig {
	/// Each node's place in the world now.
	pub world: Vec<Mat4>,
	/// Each node's own rotation now (relative to its parent).
	pub local: Vec<Quat>,
	world_rot: Vec<Quat>,
	rest_world_rot: Vec<Quat>,
	root: Mat4,
	root_rot: Quat,
	node_bone: Vec<Option<usize>>,
	humanoid_parent: [Option<usize>; 55],
	/// Each skin's joint matrices for drawing.
	pub skins: Vec<Vec<Mat4>>,
	/// How far the hips are moved from where they stand at rest, in metres (full-body animation).
	pub hips_offset: Vec3,
	hips_node: Option<usize>,
}

impl Rig {
	pub fn new(model: &Model) -> Rig {
		let n = model.nodes.len();
		// VRM 0.x avatars face away (-z); turn them round so every avatar faces the viewer.
		let root_rot = if model.version == 0 { Quat::from_rotation_y(std::f32::consts::PI) } else { Quat::IDENTITY };
		let root = Mat4::from_quat(root_rot);
		let mut node_bone = vec![None; n];
		for (b, node) in model.humanoid.iter().enumerate() {
			if let Some(node) = node {
				node_bone[*node] = Some(b);
			}
		}
		let mut humanoid_parent = [None; 55];
		for (b, node) in model.humanoid.iter().enumerate() {
			let Some(node) = node else { continue };
			let mut up = model.nodes[*node].parent;
			while let Some(p) = up {
				if let Some(pb) = node_bone[p] {
					humanoid_parent[b] = Some(pb);
					break;
				}
				up = model.nodes[p].parent;
			}
		}
		let mut rig = Rig {
			world: vec![Mat4::IDENTITY; n],
			local: model.nodes.iter().map(|x| x.rotation).collect(),
			world_rot: vec![Quat::IDENTITY; n],
			rest_world_rot: vec![Quat::IDENTITY; n],
			root,
			root_rot,
			node_bone,
			humanoid_parent,
			skins: model.skins.iter().map(|s| vec![Mat4::IDENTITY; s.joints.len()]).collect(),
			hips_offset: Vec3::ZERO,
			hips_node: model.humanoid[0],
		};
		rig.update_world(model);
		rig.rest_world_rot = rig.world_rot.clone();
		rig
	}

	fn local_matrix(model: &Model, n: usize, rot: Quat) -> Mat4 {
		let node = &model.nodes[n];
		Mat4::from_scale_rotation_translation(node.scale, rot, node.translation)
	}

	fn parent_world(&self, model: &Model, n: usize) -> (Mat4, Quat) {
		let (w, r) = match model.nodes[n].parent {
			Some(p) => (self.world[p], self.world_rot[p]),
			None => (self.root, self.root_rot),
		};
		// The hips (and so everything on them) moved by the animation.
		if Some(n) == self.hips_node && self.hips_offset != Vec3::ZERO {
			(Mat4::from_translation(self.hips_offset) * w, r)
		} else {
			(w, r)
		}
	}

	/// Work out every node's place from its own rotation, parents first.
	pub fn update_world(&mut self, model: &Model) {
		for &n in &model.order {
			let (pw, pr) = self.parent_world(model, n);
			self.world_rot[n] = pr * self.local[n];
			self.world[n] = pw * Self::local_matrix(model, n, self.local[n]);
		}
	}

	/// Put the bones that are not humanoid back as modelled (the springs and constraints then move
	/// theirs), and pose the humanoid bones from the normalised pose.
	pub fn pose(&mut self, model: &Model, q: &[Quat; 55]) {
		let mut g = [Quat::IDENTITY; 55];
		for &n in &model.order {
			let (pw, pr) = self.parent_world(model, n);
			match self.node_bone[n] {
				Some(b) => {
					let parent_g = self.humanoid_parent[b].map(|hp| g[hp]).unwrap_or(Quat::IDENTITY);
					g[b] = parent_g * q[b];
					self.local[n] = (pr.inverse() * g[b] * self.rest_world_rot[n]).normalize();
				}
				None => self.local[n] = model.nodes[n].rotation,
			}
			self.world_rot[n] = pr * self.local[n];
			self.world[n] = pw * Self::local_matrix(model, n, self.local[n]);
		}
	}

	/// Twist bones and the like follow the bones they are tied to.
	pub fn constrain(&mut self, model: &Model) {
		if model.constraints.is_empty() {
			return;
		}
		for (dst, c) in &model.constraints {
			let rest = model.nodes[*dst].rotation;
			let rotation = match *c {
				Constraint::Rotation { source, weight } => {
					let delta = model.nodes[source].rotation.inverse() * self.local[source];
					rest.slerp(rest * delta, weight.clamp(0.0, 1.0))
				}
				Constraint::Roll { source, axis, weight } => {
					let delta = model.nodes[source].rotation.inverse() * self.local[source];
					// The twist about the axis: keep only the rotation's part around it.
					let v = Vec3::new(delta.x, delta.y, delta.z);
					let p = axis * v.dot(axis);
					let twist = Quat::from_xyzw(p.x, p.y, p.z, delta.w);
					let twist = if twist.length_squared() > 1e-12 { twist.normalize() } else { Quat::IDENTITY };
					rest.slerp(rest * twist, weight.clamp(0.0, 1.0))
				}
				Constraint::Aim { source, axis, weight } => {
					let (pw, pr) = self.parent_world(model, *dst);
					let here = (pw * Self::local_matrix(model, *dst, rest)).transform_point3(Vec3::ZERO);
					let target = self.world[source].transform_point3(Vec3::ZERO);
					let from = (pr * rest) * axis;
					match (target - here).try_normalize() {
						Some(to) => {
							let aimed = pr.inverse() * Quat::from_rotation_arc(from.normalize(), to) * pr * rest;
							rest.slerp(aimed, weight.clamp(0.0, 1.0))
						}
						None => rest,
					}
				}
			};
			self.local[*dst] = rotation;
		}
		self.update_world(model);
	}

	/// The matrices that move each skin's points.
	pub fn skin(&mut self, model: &Model) {
		for (s, skin) in model.skins.iter().enumerate() {
			for (k, (&joint, ibm)) in skin.joints.iter().zip(skin.inverse_bind.iter()).enumerate() {
				self.skins[s][k] = self.world[joint] * *ibm;
			}
		}
	}

	/// Set one node's rotation and its place, from its parent's place now (children are not moved).
	pub fn set_local(&mut self, model: &Model, n: usize, rot: Quat) {
		let (pw, pr) = self.parent_world(model, n);
		self.local[n] = rot;
		self.world_rot[n] = pr * rot;
		self.world[n] = pw * Self::local_matrix(model, n, rot);
	}

	pub fn world_position(&self, n: usize) -> Vec3 {
		self.world[n].transform_point3(Vec3::ZERO)
	}

	pub fn world_rotation(&self, n: usize) -> Quat {
		self.world_rot[n]
	}

}

#[cfg(test)]
mod tests {
	use super::*;

	#[test]
	fn turns_follow_the_stages_directions() {
		// Yaw towards the viewer's right (+x), pitch up, for a face looking at the viewer (+z).
		let face = turn(30.0, 0.0, 0.0) * Vec3::Z;
		assert!(face.x > 0.4, "{face}");
		let up = turn(0.0, 20.0, 0.0) * Vec3::Z;
		assert!(up.y > 0.3, "{up}");
		// The left upper arm (along +x in the T-pose) hangs down at rest.
		let a = Quat::from_rotation_z(deg(REST_ABDUCTION - 90.0)) * Vec3::X;
		assert!(a.y < -0.95 && a.x > 0.1, "{a}");
	}
}
