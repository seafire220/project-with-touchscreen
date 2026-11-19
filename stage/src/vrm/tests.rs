//! Tests on a small stick-figure avatar built here (no third-party model is needed).

use glam::{Vec2, Vec3};
use serde_json::{json, Value};

use super::gltf::tests::build;
use super::*;

/// (name, parent, translation from parent, humanoid bone)
const SKELETON: [(&str, Option<usize>, [f32; 3], Option<&str>); 26] = [
	("Root", None, [0.0, 0.0, 0.0], None),
	("Hips", Some(0), [0.0, 0.9, 0.0], Some("hips")),
	("Spine", Some(1), [0.0, 0.1, 0.0], Some("spine")),
	("Chest", Some(2), [0.0, 0.15, 0.0], Some("chest")),
	("Neck", Some(3), [0.0, 0.2, 0.0], Some("neck")),
	("Head", Some(4), [0.0, 0.1, 0.0], Some("head")),
	("Hair1", Some(5), [0.0, 0.1, -0.08], None),
	("LeftShoulder", Some(3), [0.05, 0.15, 0.0], Some("leftShoulder")),
	("LeftUpperArm", Some(7), [0.1, 0.0, 0.0], Some("leftUpperArm")),
	("LeftLowerArm", Some(8), [0.25, 0.0, 0.0], Some("leftLowerArm")),
	("LeftHand", Some(9), [0.22, 0.0, 0.0], Some("leftHand")),
	("RightShoulder", Some(3), [-0.05, 0.15, 0.0], Some("rightShoulder")),
	("RightUpperArm", Some(11), [-0.1, 0.0, 0.0], Some("rightUpperArm")),
	("RightLowerArm", Some(12), [-0.25, 0.0, 0.0], Some("rightLowerArm")),
	("RightHand", Some(13), [-0.22, 0.0, 0.0], Some("rightHand")),
	("LeftUpperLeg", Some(1), [0.1, -0.05, 0.0], Some("leftUpperLeg")),
	("LeftLowerLeg", Some(15), [0.0, -0.4, 0.0], Some("leftLowerLeg")),
	("LeftFoot", Some(16), [0.0, -0.4, 0.0], Some("leftFoot")),
	("RightUpperLeg", Some(1), [-0.1, -0.05, 0.0], Some("rightUpperLeg")),
	("RightLowerLeg", Some(18), [0.0, -0.4, 0.0], Some("rightLowerLeg")),
	("RightFoot", Some(19), [0.0, -0.4, 0.0], Some("rightFoot")),
	("Hair2", Some(6), [0.0, -0.1, 0.0], None),
	("LeftEye", Some(5), [0.03, 0.05, 0.08], Some("leftEye")),
	("RightEye", Some(5), [-0.03, 0.05, 0.08], Some("rightEye")),
	("Body", Some(0), [0.0, 0.0, 0.0], None),
	("Hair3", Some(21), [0.0, -0.1, 0.0], None),
];

const BODY: usize = 24;
const HEAD: usize = 5;

/// Joints that carry a little triangle each (head first: its front point is the "nose").
const SKINNED: [usize; 8] = [5, 8, 9, 10, 12, 13, 14, 2];

fn world(i: usize) -> Vec3 {
	let (_, parent, t, _) = SKELETON[i];
	Vec3::from(t) + parent.map(world).unwrap_or(Vec3::ZERO)
}

/// The stick figure as a VRM file: version 1 (facing +z) or 0 (facing -z, as 0.x files do).
pub fn stick_figure(version: u8) -> Vec<u8> {
	// VRM 0.x avatars are stored turned round: x and z the other way.
	let turn = |v: Vec3| if version == 0 { Vec3::new(-v.x, v.y, -v.z) } else { v };
	let mut bin: Vec<u8> = Vec::new();
	let mut views = Vec::new();
	let mut accessors = Vec::new();
	let mut add = |bin: &mut Vec<u8>, data: Vec<u8>, accessor: Value| -> usize {
		while bin.len() % 4 != 0 {
			bin.push(0);
		}
		views.push(json!({"buffer": 0, "byteOffset": bin.len(), "byteLength": data.len()}));
		bin.extend_from_slice(&data);
		let mut a = accessor;
		a["bufferView"] = json!(views.len() - 1);
		accessors.push(a);
		accessors.len() - 1
	};
	let f32s = |v: &[f32]| v.iter().flat_map(|x| x.to_le_bytes()).collect::<Vec<u8>>();
	let mut positions = Vec::new();
	let mut joints: Vec<u16> = Vec::new();
	for (k, &j) in SKINNED.iter().enumerate() {
		let c = turn(world(j));
		let front = turn(Vec3::new(0.0, 0.0, 0.1));
		for p in [c + front, c + turn(Vec3::new(0.03, 0.03, 0.0)), c + turn(Vec3::new(-0.03, 0.03, 0.0))] {
			positions.extend_from_slice(&p.to_array());
			joints.extend_from_slice(&[k as u16, 0, 0, 0]);
		}
	}
	let n = positions.len() / 3;
	let weights: Vec<f32> = (0..n).flat_map(|_| [1.0f32, 0.0, 0.0, 0.0]).collect();
	let indices: Vec<u32> = (0..n as u32).collect();
	let pos = add(&mut bin, f32s(&positions), json!({"componentType": 5126, "count": n, "type": "VEC3"}));
	let jnt = add(&mut bin, joints.iter().flat_map(|x| x.to_le_bytes()).collect(), json!({"componentType": 5123, "count": n, "type": "VEC4"}));
	let wgt = add(&mut bin, f32s(&weights), json!({"componentType": 5126, "count": n, "type": "VEC4"}));
	let idx = add(&mut bin, indices.iter().flat_map(|x| x.to_le_bytes()).collect(), json!({"componentType": 5125, "count": n, "type": "SCALAR"}));
	let mut ibm = Vec::new();
	for &j in &SKINNED {
		let w = turn(world(j));
		ibm.extend_from_slice(&glam::Mat4::from_translation(-w).to_cols_array());
	}
	let ibm = add(&mut bin, f32s(&ibm), json!({"componentType": 5126, "count": SKINNED.len(), "type": "MAT4"}));
	// Morph targets: 0 opens the mouth (the nose point drops), 1 closes the eyes (a head corner drops).
	let mut targets = Vec::new();
	for (point, delta) in [(0usize, [0.0f32, -0.02, 0.0]), (1, [0.0, -0.01, 0.0])] {
		let mut d = vec![0.0f32; n * 3];
		d[point * 3..point * 3 + 3].copy_from_slice(&delta);
		targets.push(json!({"POSITION": add(&mut bin, f32s(&d), json!({"componentType": 5126, "count": n, "type": "VEC3"}))}));
	}
	let nodes: Vec<Value> = SKELETON
		.iter()
		.enumerate()
		.map(|(i, (name, _, t, _))| {
			let children: Vec<usize> = (0..SKELETON.len()).filter(|&c| SKELETON[c].1 == Some(i)).collect();
			let mut node = json!({"name": name, "translation": turn(Vec3::from(*t)).to_array()});
			if !children.is_empty() {
				node["children"] = json!(children);
			}
			if i == BODY {
				node["mesh"] = json!(0);
				node["skin"] = json!(0);
			}
			node
		})
		.collect();
	let mut doc = json!({
		"asset": {"version": "2.0"},
		"scenes": [{"nodes": [0]}],
		"nodes": nodes,
		"meshes": [{"name": "Body", "extras": {"targetNames": ["mouthA", "eyeClose"]},
			"primitives": [{"attributes": {"POSITION": pos, "JOINTS_0": jnt, "WEIGHTS_0": wgt}, "indices": idx,
			                "material": 0, "targets": targets}]}],
		"skins": [{"joints": SKINNED, "inverseBindMatrices": ibm}],
		"materials": [{"name": "Skin", "pbrMetallicRoughness": {"baseColorFactor": [1.0, 0.8, 0.7, 1.0]}}],
		"buffers": [{"byteLength": bin.len()}],
	});
	let bones: Vec<(String, usize)> = SKELETON.iter().enumerate().filter_map(|(i, s)| s.3.map(|b| (b.to_string(), i))).collect();
	if version == 1 {
		let human: serde_json::Map<String, Value> = bones.iter().map(|(b, i)| (b.clone(), json!({"node": i}))).collect();
		doc["extensionsUsed"] = json!(["VRMC_vrm", "VRMC_springBone"]);
		doc["extensions"] = json!({
			"VRMC_vrm": {
				"specVersion": "1.0",
				"meta": {"name": "Stick", "authors": ["test"], "licenseUrl": "https://vrm.dev/licenses/1.0/", "avatarPermission": "everyone"},
				"humanoid": {"humanBones": human},
				"expressions": {"preset": {
					"aa": {"morphTargetBinds": [{"node": BODY, "index": 0, "weight": 1.0}]},
					"blink": {"morphTargetBinds": [{"node": BODY, "index": 1, "weight": 1.0}]},
					"happy": {"morphTargetBinds": [{"node": BODY, "index": 1, "weight": 0.5}], "overrideBlink": "block"}
				}, "custom": {"blush": {"morphTargetBinds": []}}},
				"lookAt": {"type": "bone", "rangeMapHorizontalInner": {"inputMaxValue": 90, "outputScale": 10},
					"rangeMapHorizontalOuter": {"inputMaxValue": 90, "outputScale": 12},
					"rangeMapVerticalDown": {"inputMaxValue": 90, "outputScale": 10},
					"rangeMapVerticalUp": {"inputMaxValue": 90, "outputScale": 10}}
			},
			"VRMC_springBone": {
				"specVersion": "1.0",
				"colliders": [{"node": HEAD, "shape": {"sphere": {"offset": [0.0, 0.0, 0.0], "radius": 0.08}}}],
				"colliderGroups": [{"name": "head", "colliders": [0]}],
				"springs": [{"name": "hair", "joints": [
					{"node": 6, "hitRadius": 0.01, "stiffness": 0.5, "gravityPower": 1.0, "gravityDir": [0, -1, 0], "dragForce": 0.4},
					{"node": 21, "hitRadius": 0.01, "stiffness": 0.5, "gravityPower": 1.0, "gravityDir": [0, -1, 0], "dragForce": 0.4},
					{"node": 25}], "colliderGroups": [0]}]
			}
		});
	} else {
		let human: Vec<Value> = bones.iter().map(|(b, i)| json!({"bone": b, "node": i})).collect();
		doc["extensionsUsed"] = json!(["VRM"]);
		doc["extensions"] = json!({"VRM": {
			"exporterVersion": "test",
			"meta": {"title": "Stick", "author": "test", "allowedUserName": "Everyone", "licenseName": "CC0"},
			"humanoid": {"humanBones": human},
			"blendShapeMaster": {"blendShapeGroups": [
				{"name": "A", "presetName": "a", "binds": [{"mesh": 0, "index": 0, "weight": 100}]},
				{"name": "Blink", "presetName": "blink", "binds": [{"mesh": 0, "index": 1, "weight": 100}]},
				{"name": "Joy", "presetName": "joy", "binds": [{"mesh": 0, "index": 1, "weight": 50}]}
			]},
			"firstPerson": {"lookAtTypeName": "Bone",
				"lookAtHorizontalInner": {"xRange": 90, "yRange": 10}, "lookAtHorizontalOuter": {"xRange": 90, "yRange": 12},
				"lookAtVerticalDown": {"xRange": 90, "yRange": 10}, "lookAtVerticalUp": {"xRange": 90, "yRange": 10}},
			"secondaryAnimation": {
				"boneGroups": [{"bones": [6], "stiffiness": 0.5, "gravityPower": 1.0, "gravityDir": {"x": 0, "y": -1, "z": 0},
					"dragForce": 0.4, "hitRadius": 0.01, "colliderGroups": [0], "center": -1}],
				"colliderGroups": [{"node": HEAD, "colliders": [{"offset": {"x": 0, "y": 0, "z": 0}, "radius": 0.08}]}]
			},
			"materialProperties": [{"name": "Skin", "shader": "VRM/MToon", "floatProperties": {"_ShadeToony": 0.9},
				"vectorProperties": {"_Color": [1.0, 0.8, 0.7, 1.0], "_ShadeColor": [0.8, 0.6, 0.6, 1.0]}, "textureProperties": {}}]
		}});
	}
	doc["bufferViews"] = json!(views);
	doc["accessors"] = json!(accessors);
	build(&doc, &bin)
}

fn load(version: u8) -> VrmPuppet {
	VrmPuppet::from_bytes(stick_figure(version), Profile::L1).expect("the stick figure loads")
}

fn values(list: &[(&str, f32)]) -> Vec<(String, Vec2)> {
	list.iter().map(|(n, v)| (n.to_string(), Vec2::new(*v, 0.0))).collect()
}

fn at(p: &VrmPuppet, node: usize) -> Vec3 {
	p.rig.world_position(node)
}

/// Where a point of the head's triangle is drawn (skinned).
fn nose(p: &VrmPuppet) -> Vec3 {
	let points = &p.model.meshes[0].points[p.model.meshes[0].primitives[0].points];
	p.rig.skins[0][0].transform_point3(points.positions[0])
}

#[test]
fn both_versions_load_with_their_bones_expressions_and_springs() {
	for version in [0, 1] {
		let p = load(version);
		assert!(looks_like_vrm(&stick_figure(version)));
		assert_eq!(p.model.version, version);
		assert!(p.model.bone("head").is_some() && p.model.bone("leftEye").is_some());
		let names: Vec<&str> = p.model.expressions.iter().map(|e| e.name.as_str()).collect();
		for want in ["aa", "blink", "happy"] {
			assert!(names.contains(&want), "{version}: {names:?}");
		}
		assert!(p.info.params.iter().any(|x| x.name == "Expr:aa"));
		assert!(p.info.params.iter().any(|x| x.name == "ParamArmLA"));
		assert_eq!(p.info.expressions.len(), p.model.expressions.len());
		assert!(p.springs.as_ref().unwrap().joint_count() >= 2, "{version}");
		assert_eq!(p.model.meta.name, "Stick");
	}
	assert!(!looks_like_vrm(b"glTF\x02\x00\x00\x00"));
}

#[test]
fn every_avatar_faces_the_viewer_with_its_arms_down() {
	for version in [0, 1] {
		let p = load(version);
		assert!(nose(&p).z > at(&p, HEAD).z + 0.05, "{version}: faces +z");
		let (shoulder, hand) = (at(&p, 8), at(&p, 10));
		assert!(hand.x > 0.1, "{version}: the left hand is on the avatar's left (+x): {hand}");
		assert!(hand.y < shoulder.y - 0.35, "{version}: and hangs down: {hand} {shoulder}");
		assert!(at(&p, 14).x < -0.1 && at(&p, 14).y < shoulder.y - 0.35, "{version}: the right hand too");
		assert!(at(&p, 22).x > 0.0, "{version}: the left eye is on +x");
	}
}

#[test]
fn the_head_turns_and_nods_the_stages_way() {
	let mut p = load(1);
	let rest = nose(&p);
	p.update(&values(&[("ParamAngleX", 30.0)]), 0.0);
	assert!(nose(&p).x > rest.x + 0.03, "a positive turn faces the viewer's right");
	p.update(&values(&[("ParamAngleY", 30.0)]), 0.0);
	assert!(nose(&p).y > rest.y + 0.02, "a positive nod looks up");
	p.update(&values(&[("ParamBodyAngleY", -10.0)]), 0.0);
	assert!(at(&p, HEAD).z > 0.01, "bowing brings the head forward");
}

#[test]
fn arms_wave_and_rest_on_the_hips() {
	let mut p = load(1);
	p.update(&values(&[("ParamArmLA", 5.0), ("ParamArmLB", 8.5)]), 0.0);
	let (elbow, hand) = (at(&p, 9), at(&p, 10));
	assert!(hand.y > elbow.y + 0.15, "waving: the hand is up above the elbow: {hand} {elbow}");
	p.update(&values(&[("ParamArmLA", 6.0), ("ParamArmLB", -9.0)]), 0.0);
	let (shoulder, elbow, hand) = (at(&p, 8), at(&p, 9), at(&p, 10));
	assert!(elbow.x > shoulder.x + 0.15, "hands on hips: the elbow out: {elbow}");
	assert!(hand.x < elbow.x - 0.05 && hand.y < elbow.y, "and the hand back in, lower: {hand} {elbow}");
}

#[test]
fn blinking_and_talking_drive_the_expressions_and_their_shapes() {
	let mut p = load(1);
	let blink = p.model.expression("blink").unwrap();
	let aa = p.model.expression("aa").unwrap();
	p.update(&values(&[("ParamEyeLOpen", 0.0), ("ParamEyeROpen", 0.0), ("ParamMouthOpenY", 0.6)]), 0.0);
	assert!((p.weights[blink] - 1.0).abs() < 1e-5 && (p.weights[aa] - 0.6).abs() < 1e-5);
	assert!((p.morphs[0][1] - 1.0).abs() < 1e-5 && (p.morphs[0][0] - 0.6).abs() < 1e-5);
	// Vowels win over the plain opening while speaking; a vowel the avatar lacks shows as "aa".
	p.update(&values(&[("ParamMouthOpenY", 0.6), ("ParamI", 0.4)]), 0.0);
	assert!((p.weights[aa] - 0.4).abs() < 1e-5, "{}", p.weights[aa]);
}

#[test]
fn an_expression_that_blocks_blinking_wins_over_a_blink() {
	let mut p = load(1);
	let blink = p.model.expression("blink").unwrap();
	let happy = p.model.expression("happy").unwrap();
	p.update(&values(&[("Expr:happy", 1.0), ("ParamEyeLOpen", 0.0), ("ParamEyeROpen", 0.0)]), 0.0);
	assert_eq!(p.weights[blink], 0.0);
	assert!(p.weights[happy] > 0.5 && p.weights[happy] < 1.0, "a mood shows at less than full strength");
	assert!((p.morphs[0][1] - p.weights[happy] * 0.5).abs() < 1e-5);
	// VRM 0.x had no override settings: its emotions soften blinking.
	let mut p = load(0);
	p.update(&values(&[("Expr:happy", 1.0), ("ParamEyeLOpen", 0.0), ("ParamEyeROpen", 0.0)]), 0.0);
	let blink = p.model.expression("blink").unwrap();
	assert!(p.weights[blink] < 0.5);
}

#[test]
fn the_eyes_turn_within_the_avatars_range() {
	let mut p = load(1);
	p.update(&values(&[("ParamEyeBallX", 1.0)]), 0.0);
	let eye = p.model.bone("leftEye").unwrap();
	let forward = p.rig.world_rotation(eye) * Vec3::Z;
	let degrees = forward.x.atan2(forward.z).to_degrees();
	assert!(degrees > 1.0 && degrees < 13.0, "looking right turns the eye a little: {degrees}");
}

#[test]
fn hair_swings_but_keeps_its_length_and_stays_out_of_the_head() {
	for version in [0, 1] {
		let mut p = load(version);
		for k in 0..90 {
			let yaw = if k % 30 < 15 { 30.0 } else { -30.0 };
			p.update(&values(&[("ParamAngleX", yaw)]), 1.0 / 30.0);
			let (h1, h2, h3) = (at(&p, 6), at(&p, 21), at(&p, 25));
			assert!(((h2 - h1).length() - 0.1).abs() < 0.002, "{version}: {}", (h2 - h1).length());
			assert!(((h3 - h2).length() - 0.1).abs() < 0.002);
			assert!((h3 - at(&p, HEAD)).length() > 0.08 - 1e-3, "{version}: kept out of the head");
		}
		assert!(at(&p, 25).y < at(&p, 6).y, "{version}: it hangs down");
	}
}

#[test]
fn damaged_or_wrong_files_are_refused_with_a_reason() {
	assert!(VrmPuppet::from_bytes(b"not a model".to_vec(), Profile::L1).is_err());
	let plain = build(&json!({"asset": {"version": "2.0"}, "nodes": [{"name": "a"}]}), &[]);
	let e = VrmPuppet::from_bytes(plain, Profile::L1).err().unwrap();
	assert!(e.contains("not a VRM"), "{e}");
	// A VRM without its head bone.
	let bytes = stick_figure(1);
	let len = u32::from_le_bytes([bytes[12], bytes[13], bytes[14], bytes[15]]) as usize;
	let mut doc: Value = serde_json::from_slice(&bytes[20..20 + len]).unwrap();
	let bin = &bytes[20 + len + 8..];
	doc["extensions"]["VRMC_vrm"]["humanoid"]["humanBones"].as_object_mut().unwrap().remove("head");
	let e = VrmPuppet::from_bytes(build(&doc, bin), Profile::L1).err().unwrap();
	assert!(e.contains("head"), "{e}");
}

#[test]
#[ignore]
fn print_rest_weights_of_a_model() {
	let path = std::env::var("VRM_FILE").expect("set VRM_FILE");
	let mut p = VrmPuppet::load(std::path::Path::new(&path), Profile::L1).unwrap();
	let rest = values(&[("ParamEyeLOpen", 1.0), ("ParamEyeROpen", 1.0), ("ParamMouthOpenY", 0.0), ("ParamMouthForm", 0.0)]);
	p.update(&rest, 0.0);
	for (e, w) in p.model.expressions.iter().zip(&p.weights) {
		if *w > 0.0 {
			println!("expression {} {}", e.name, w);
		}
	}
	for (m, ws) in p.morphs.iter().enumerate() {
		for (t, w) in ws.iter().enumerate() {
			if *w > 0.0 {
				println!("morph mesh {} target {} ({}) {}", m, t, p.model.meshes[m].target_names.get(t).cloned().unwrap_or_default(), w);
			}
		}
	}
	for (m, mesh) in p.model.meshes.iter().enumerate() {
		for (pi, prim) in mesh.primitives.iter().enumerate() {
			let set = &mesh.points[prim.points];
			let moved: usize = set.targets.iter().map(|t| t.indices.len()).sum();
			println!("mesh {m} {} prim {pi}: points set {} ({} points), {} targets, {} moved points, material {:?}", mesh.name, prim.points, set.positions.len(), set.targets.len(), moved, prim.material);
		}
	}
}

#[test]
fn parts_that_share_points_share_them_on_the_device_too() {
	// VRoid Studio's exports give one set of points to many parts (each with its own material): the
	// set is read once, and its face shapes move every part.
	let glb = crate::vrm::gltf::Glb::parse(stick_figure(1)).unwrap();
	let mut doc = glb.json.clone();
	let first = doc["meshes"][0]["primitives"][0].clone();
	let mut second = first.clone();
	second["material"] = json!(0);
	doc["meshes"][0]["primitives"] = json!([first, second]);
	let file = crate::vrm::gltf::tests::build(&doc, glb.bin());
	let mut p = VrmPuppet::from_bytes(file, Profile::L1).unwrap();
	let mesh = &p.model.meshes[0];
	assert_eq!((mesh.points.len(), mesh.primitives.len()), (1, 2));
	assert_eq!(mesh.primitives[0].points, mesh.primitives[1].points);
	assert_eq!(p.size.0, mesh.points[0].positions.len(), "points counted once");
	assert_eq!(p.size.1, 2 * (mesh.primitives[0].indices.len() / 3), "triangles counted per part");
	p.update(&values(&[("ParamA", 1.0)]), 1.0 / 30.0);
	assert!(p.morphs[0][0] > 0.5, "the shared face shape moves");
}
