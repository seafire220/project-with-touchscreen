//! Reads what the stage needs to know about a puppet file without relying on
//! the renderer: its parameters and its overall size.

use serde_json::Value;

#[derive(Clone, Debug, PartialEq)]
pub struct ParamInfo {
	pub name: String,
	pub is_vec2: bool,
	pub min: [f32; 2],
	pub max: [f32; 2],
	pub defaults: [f32; 2],
}

#[derive(Clone, Debug, Default)]
pub struct PuppetInfo {
	pub name: Option<String>,
	pub params: Vec<ParamInfo>,
	/// min x, min y, max x, max y of all part meshes in puppet units.
	pub bounds: Option<[f32; 4]>,
	pub part_count: usize,
	pub node_types: Vec<String>,
}

const MAGIC: &[u8; 8] = b"TRNSRTS\0";

/// Node types the renderer can draw. Anything else is refused up front so a
/// character is never shown half-working.
pub const SUPPORTED_NODE_TYPES: [&str; 4] = ["Node", "Part", "Composite", "SimplePhysics"];

fn pair(v: Option<&Value>) -> [f32; 2] {
	let get = |i: usize| {
		v.and_then(|v| v.get(i)).and_then(Value::as_f64).unwrap_or(0.0) as f32
	};
	[get(0), get(1)]
}

fn walk(node: &Value, pos: [f32; 2], scale: [f32; 2], info: &mut PuppetInfo, bounds: &mut Option<[f32; 4]>) {
	let ty = node.get("type").and_then(Value::as_str).unwrap_or("Node").to_string();
	if !info.node_types.contains(&ty) {
		info.node_types.push(ty.clone());
	}
	let transform = node.get("transform");
	let trans = pair(transform.and_then(|t| t.get("trans")));
	let own_scale = transform
		.and_then(|t| t.get("scale"))
		.map(|s| pair(Some(s)))
		.unwrap_or([1.0, 1.0]);
	// Rotation is ignored: this is only used to frame the character on screen.
	let (pos, scale) = if node.get("lockToRoot").and_then(Value::as_bool).unwrap_or(false) {
		(trans, own_scale)
	} else {
		(
			[pos[0] + scale[0] * trans[0], pos[1] + scale[1] * trans[1]],
			[scale[0] * own_scale[0], scale[1] * own_scale[1]],
		)
	};
	if ty == "Part" {
		info.part_count += 1;
		if let Some(verts) = node.get("mesh").and_then(|m| m.get("verts")).and_then(Value::as_array) {
			for xy in verts.chunks(2) {
				if let (Some(x), Some(y)) = (xy.first().and_then(Value::as_f64), xy.get(1).and_then(Value::as_f64)) {
					let wx = pos[0] + scale[0] * x as f32;
					let wy = pos[1] + scale[1] * y as f32;
					let b = bounds.get_or_insert([wx, wy, wx, wy]);
					b[0] = b[0].min(wx);
					b[1] = b[1].min(wy);
					b[2] = b[2].max(wx);
					b[3] = b[3].max(wy);
				}
			}
		}
	}
	if let Some(children) = node.get("children").and_then(Value::as_array) {
		for child in children {
			walk(child, pos, scale, info, bounds);
		}
	}
}

/// Parse the JSON part of an `.inp` or `.inx` file.
pub fn read(bytes: &[u8]) -> Result<PuppetInfo, String> {
	if bytes.len() < 12 || &bytes[..8] != MAGIC {
		return Err("not an Inochi2D puppet file (bad header)".into());
	}
	let len = u32::from_be_bytes([bytes[8], bytes[9], bytes[10], bytes[11]]) as usize;
	let end = 12usize.checked_add(len).filter(|e| *e <= bytes.len());
	let Some(end) = end else {
		return Err("puppet file is truncated".into());
	};
	let json: Value = serde_json::from_slice(&bytes[12..end]).map_err(|e| format!("puppet data is not valid JSON: {e}"))?;

	let mut info = PuppetInfo {
		name: json
			.get("meta")
			.and_then(|m| m.get("name"))
			.and_then(Value::as_str)
			.map(str::to_string),
		..Default::default()
	};
	if let Some(params) = json.get("param").and_then(Value::as_array) {
		for p in params {
			let Some(name) = p.get("name").and_then(Value::as_str) else {
				continue;
			};
			info.params.push(ParamInfo {
				name: name.to_string(),
				is_vec2: p.get("is_vec2").and_then(Value::as_bool).unwrap_or(false),
				min: pair(p.get("min")),
				max: pair(p.get("max")),
				defaults: pair(p.get("defaults")),
			});
		}
	}
	let mut bounds = None;
	if let Some(root) = json.get("nodes") {
		walk(root, [0.0, 0.0], [1.0, 1.0], &mut info, &mut bounds);
	} else {
		return Err("puppet file has no nodes".into());
	}
	info.bounds = bounds;
	Ok(info)
}

/// Node types in the file that the renderer cannot draw.
pub fn unsupported_node_types(info: &PuppetInfo) -> Vec<String> {
	info.node_types
		.iter()
		.filter(|t| !SUPPORTED_NODE_TYPES.contains(&t.as_str()))
		.cloned()
		.collect()
}

#[cfg(test)]
pub(crate) fn make_file(json: &str) -> Vec<u8> {
	let mut out = MAGIC.to_vec();
	out.extend_from_slice(&(json.len() as u32).to_be_bytes());
	out.extend_from_slice(json.as_bytes());
	out
}

#[cfg(test)]
mod tests {
	use super::*;

	const SAMPLE: &str = r#"{
		"meta": {"name": "Test"},
		"param": [
			{"name": "Mouth:: Shape", "is_vec2": true, "min": [0,0], "max": [1,1], "defaults": [1,1]},
			{"name": "Breath", "is_vec2": false, "min": [0,0], "max": [1,1], "defaults": [0,0]}
		],
		"nodes": {"type": "Node", "transform": {"trans": [10, 20, 0], "scale": [2, 2]}, "children": [
			{"type": "Part", "transform": {"trans": [1, 1, 0], "scale": [1, 1]},
			 "mesh": {"verts": [-5, -5, 5, 5]}},
			{"type": "SimplePhysics", "transform": {"trans": [0, 0, 0], "scale": [1, 1]}}
		]}
	}"#;

	#[test]
	fn reads_params_and_bounds() {
		let info = read(&make_file(SAMPLE)).unwrap();
		assert_eq!(info.name.as_deref(), Some("Test"));
		assert_eq!(info.params.len(), 2);
		assert!(info.params[0].is_vec2);
		assert_eq!(info.params[0].defaults, [1.0, 1.0]);
		assert_eq!(info.part_count, 1);
		// part origin = 10 + 2*1 = 12, 20 + 2*1 = 22; verts scaled by 2
		assert_eq!(info.bounds, Some([2.0, 12.0, 22.0, 32.0]));
		assert!(unsupported_node_types(&info).is_empty());
	}

	#[test]
	fn rejects_bad_files() {
		assert!(read(b"hello").is_err());
		assert!(read(b"TRNSRTS\0\x00\x00\x10\x00{}").is_err());
		assert!(read(&make_file("not json")).is_err());
		assert!(read(&make_file("{}")).is_err());
	}

	#[test]
	fn reports_unsupported_nodes() {
		let json = r#"{"nodes": {"type": "Node", "children": [{"type": "MeshGroup"}]}}"#;
		let info = read(&make_file(json)).unwrap();
		assert_eq!(unsupported_node_types(&info), vec!["MeshGroup".to_string()]);
	}
}
