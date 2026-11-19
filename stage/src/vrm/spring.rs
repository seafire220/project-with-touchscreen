//! Spring bones: hair, skirts and ribbons that swing as the avatar moves, as VRM defines them
//! (`VRMC_springBone`, and VRM 0.x's `secondaryAnimation`). Each joint's tip keeps its momentum,
//! is pulled back towards the shape it was modelled in (stiffness), falls (gravity), stays the
//! bone's length from the joint, and is pushed out of the body's spheres and capsules.

use glam::{Mat4, Quat, Vec3};

use super::model::{Model, Tail};
use super::rig::Rig;

struct Joint {
	node: usize,
	parent: Option<usize>,
	axis: Vec3,
	length: f32,
	hit_radius: f32,
	stiffness: f32,
	gravity: Vec3,
	drag: f32,
	/// The tip now and a step ago (in the chain's centre space).
	current: Vec3,
	previous: Vec3,
}

struct Chain {
	joints: std::ops::Range<usize>,
	colliders: Vec<usize>,
	center: Option<usize>,
}

pub struct Springs {
	joints: Vec<Joint>,
	chains: Vec<Chain>,
}

/// Longest step simulated at once; longer frames are cut into steps this long.
const STEP: f32 = 1.0 / 60.0;

impl Springs {
	/// Set up from the avatar's pose as it is now (so nothing jumps at the start).
	pub fn new(model: &Model, rig: &Rig) -> Springs {
		let mut joints = Vec::new();
		let mut chains = Vec::new();
		for spring in &model.springs {
			let start = joints.len();
			for j in &spring.joints {
				let tail_local = match j.tail {
					Tail::Node(c) => model.nodes[c].translation,
					Tail::Offset(o) => o,
				};
				let Some(axis) = tail_local.try_normalize() else { continue };
				let world_tail = rig.world[j.node].transform_point3(tail_local);
				let here = rig.world_position(j.node);
				let length = (world_tail - here).length().max(1e-5);
				let center = spring.center.map(|c| rig.world[c].inverse()).unwrap_or(Mat4::IDENTITY);
				let tip = center.transform_point3(world_tail);
				joints.push(Joint {
					node: j.node,
					parent: model.nodes[j.node].parent,
					axis,
					length,
					hit_radius: j.hit_radius,
					stiffness: j.stiffness,
					gravity: j.gravity_dir * j.gravity_power,
					drag: j.drag,
					current: tip,
					previous: tip,
				});
			}
			if joints.len() > start {
				chains.push(Chain { joints: start..joints.len(), colliders: spring.colliders.clone(), center: spring.center });
			}
		}
		Springs { joints, chains }
	}

	pub fn joint_count(&self) -> usize {
		self.joints.len()
	}

	/// Move every chain on by `dt` seconds and set its bones' rotations on the rig.
	pub fn update(&mut self, model: &Model, rig: &mut Rig, dt: f32) {
		if self.joints.is_empty() {
			return;
		}
		let dt = dt.clamp(0.0, 0.1);
		let steps = (dt / STEP).ceil().max(1.0) as usize;
		let h = dt / steps as f32;
		// The colliders' places, once per frame (the body moves only with the humanoid pose).
		let colliders: Vec<(Vec3, Option<Vec3>, f32)> = model
			.colliders
			.iter()
			.map(|c| {
				let w = rig.world[c.node];
				let scale = w.x_axis.truncate().length();
				(w.transform_point3(c.offset), c.tail.map(|t| w.transform_point3(t)), c.radius * scale)
			})
			.collect();
		for _ in 0..steps {
			for chain in &self.chains {
				let to_world = chain.center.map(|c| rig.world[c]).unwrap_or(Mat4::IDENTITY);
				let to_center = to_world.inverse();
				for j in &mut self.joints[chain.joints.clone()] {
					let parent_world = j.parent.map(|p| rig.world[p]).unwrap_or(Mat4::IDENTITY);
					let parent_rot = j.parent.map(|p| rig.world_rotation(p)).unwrap_or(Quat::IDENTITY);
					let node = &model.nodes[j.node];
					let rest = node.rotation;
					let here = parent_world.transform_point3(node.translation);
					let rest_axis = (parent_rot * rest * j.axis).normalize();
					let current = to_world.transform_point3(j.current);
					let previous = to_world.transform_point3(j.previous);
					let mut next = current
						+ (current - previous) * (1.0 - j.drag)
						+ rest_axis * j.stiffness * h
						+ j.gravity * h;
					next = here + (next - here).try_normalize().unwrap_or(rest_axis) * j.length;
					for &ci in &chain.colliders {
						let Some(&(c, tail, radius)) = colliders.get(ci) else { continue };
						let centre = match tail {
							Some(t) => closest_on_segment(c, t, next),
							None => c,
						};
						let reach = radius + j.hit_radius;
						let d = next - centre;
						let dist = d.length();
						if dist < reach && dist > 1e-6 {
							next = centre + d / dist * reach;
							next = here + (next - here).try_normalize().unwrap_or(rest_axis) * j.length;
						}
					}
					j.previous = to_center.transform_point3(current);
					j.current = to_center.transform_point3(next);
					// Turn the bone so its tip points at the new place.
					let to_local = (parent_rot * rest).inverse();
					let dir = (to_local * (next - here)).try_normalize().unwrap_or(j.axis);
					rig.set_local(model, j.node, rest * Quat::from_rotation_arc(j.axis, dir));
				}
			}
		}
		rig.update_world(model);
	}
}

impl Springs {
	/// Keep the bones where the last step left them, without moving them on (for frames between
	/// steps, when the springs run at half rate).
	pub fn hold(&self, model: &Model, rig: &mut Rig) {
		if self.joints.is_empty() {
			return;
		}
		for chain in &self.chains {
			let to_world = chain.center.map(|c| rig.world[c]).unwrap_or(Mat4::IDENTITY);
			for j in &self.joints[chain.joints.clone()] {
				let parent_world = j.parent.map(|p| rig.world[p]).unwrap_or(Mat4::IDENTITY);
				let parent_rot = j.parent.map(|p| rig.world_rotation(p)).unwrap_or(Quat::IDENTITY);
				let node = &model.nodes[j.node];
				let here = parent_world.transform_point3(node.translation);
				let tip = to_world.transform_point3(j.current);
				let to_local = (parent_rot * node.rotation).inverse();
				let dir = (to_local * (tip - here)).try_normalize().unwrap_or(j.axis);
				rig.set_local(model, j.node, node.rotation * Quat::from_rotation_arc(j.axis, dir));
			}
		}
		rig.update_world(model);
	}
}

fn closest_on_segment(a: Vec3, b: Vec3, p: Vec3) -> Vec3 {
	let ab = b - a;
	let t = if ab.length_squared() > 1e-12 { ((p - a).dot(ab) / ab.length_squared()).clamp(0.0, 1.0) } else { 0.0 };
	a + ab * t
}
