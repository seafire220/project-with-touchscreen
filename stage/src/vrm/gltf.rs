//! Reading glTF 2.0 binary files (GLB, which VRM files are): the JSON description, the binary
//! chunk, and accessors (typed views of the binary data), including sparse ones.
//!
//! Only what a VRM avatar needs: one binary buffer inside the file (no external files), and
//! images stored in it.

use serde_json::Value;

pub const MAGIC: &[u8; 4] = b"glTF";

pub struct Glb {
	pub json: Value,
	/// The whole file; the binary chunk is `bytes[bin.0..bin.1]`.
	bytes: Vec<u8>,
	bin: (usize, usize),
}

fn u32_at(bytes: &[u8], at: usize) -> Option<u32> {
	bytes.get(at..at + 4).map(|b| u32::from_le_bytes([b[0], b[1], b[2], b[3]]))
}

/// Does this look like a glTF binary file?
pub fn is_glb(bytes: &[u8]) -> bool {
	bytes.len() >= 20 && &bytes[..4] == MAGIC && u32_at(bytes, 4) == Some(2)
}

impl Glb {
	pub fn parse(bytes: Vec<u8>) -> Result<Glb, String> {
		if bytes.len() < 20 || &bytes[..4] != MAGIC {
			return Err("not a glTF binary file".into());
		}
		let version = u32_at(&bytes, 4).unwrap_or(0);
		if version != 2 {
			return Err(format!("glTF version {version} is not supported (version 2 is)"));
		}
		let total = (u32_at(&bytes, 8).unwrap_or(0) as usize).min(bytes.len());
		let mut at = 12;
		let mut json = None;
		let mut bin = (0, 0);
		while at + 8 <= total {
			let len = u32_at(&bytes, at).unwrap_or(0) as usize;
			let kind = &bytes[at + 4..at + 8];
			let start = at + 8;
			let end = start.checked_add(len).filter(|e| *e <= total).ok_or("the file is cut short")?;
			match kind {
				b"JSON" => {
					json = Some(serde_json::from_slice::<Value>(&bytes[start..end]).map_err(|e| format!("its description is not valid JSON: {e}"))?)
				}
				b"BIN\0" if bin == (0, 0) => bin = (start, end),
				_ => {}
			}
			at = (end + 3) & !3;
		}
		let json = json.ok_or("the file has no description (JSON chunk)")?;
		Ok(Glb { json, bytes, bin })
	}

	pub fn bin(&self) -> &[u8] {
		&self.bytes[self.bin.0..self.bin.1]
	}

	pub fn get(&self, key: &str) -> &[Value] {
		self.json.get(key).and_then(Value::as_array).map(Vec::as_slice).unwrap_or(&[])
	}

	/// A buffer view's bytes and its stride (if it has one).
	pub fn view(&self, index: usize) -> Result<(&[u8], Option<usize>), String> {
		let v = self.get("bufferViews").get(index).ok_or(format!("buffer view {index} does not exist"))?;
		let buffer = v.get("buffer").and_then(Value::as_u64).unwrap_or(0);
		if buffer != 0 {
			return Err("data in a second buffer is not supported".into());
		}
		if let Some(b) = self.get("buffers").first() {
			if b.get("uri").is_some() {
				return Err("data in a separate file is not supported; use a .vrm (or .glb) file".into());
			}
		}
		let offset = v.get("byteOffset").and_then(Value::as_u64).unwrap_or(0) as usize;
		let length = v.get("byteLength").and_then(Value::as_u64).ok_or(format!("buffer view {index} has no length"))? as usize;
		let stride = v.get("byteStride").and_then(Value::as_u64).map(|s| s as usize);
		let bin = self.bin();
		let end = offset.checked_add(length).filter(|e| *e <= bin.len()).ok_or(format!("buffer view {index} reaches past the data"))?;
		Ok((&bin[offset..end], stride))
	}

	/// An image's encoded bytes (PNG or JPEG) and its type.
	pub fn image(&self, index: usize) -> Result<(&[u8], String), String> {
		let img = self.get("images").get(index).ok_or(format!("image {index} does not exist"))?;
		let mime = img.get("mimeType").and_then(Value::as_str).unwrap_or("").to_string();
		match img.get("bufferView").and_then(Value::as_u64) {
			Some(v) => Ok((self.view(v as usize)?.0, mime)),
			None => Err(format!("image {index} is not stored inside the file")),
		}
	}

	/// An accessor's values as floats, flattened, and how many numbers make one element.
	/// Normalised integers are turned into fractions as glTF defines.
	pub fn floats(&self, index: usize) -> Result<(Vec<f32>, usize), String> {
		let a = Accessor::read(self, index)?;
		let mut out = vec![0.0f32; a.count * a.components];
		if let Some(view) = a.view {
			let (data, stride) = view;
			for i in 0..a.count {
				let base = a.offset + i * stride;
				for c in 0..a.components {
					out[i * a.components + c] = a.kind.float(data, base + c * a.kind.size(), a.normalized);
				}
			}
		}
		if let Some(sparse) = &a.sparse {
			for (k, &target) in sparse.indices.iter().enumerate() {
				let target = target as usize;
				if target >= a.count {
					return Err(format!("accessor {index}: a sparse index is out of range"));
				}
				for c in 0..a.components {
					out[target * a.components + c] =
						a.kind.float(sparse.values, (k * a.components + c) * a.kind.size(), a.normalized);
				}
			}
		}
		Ok((out, a.components))
	}

	/// An accessor's values as whole numbers (indices, joint numbers), flattened.
	pub fn uints(&self, index: usize) -> Result<(Vec<u32>, usize), String> {
		let a = Accessor::read(self, index)?;
		if a.kind == Kind::F32 {
			return Err(format!("accessor {index} holds fractions where whole numbers were expected"));
		}
		let mut out = vec![0u32; a.count * a.components];
		if let Some((data, stride)) = a.view {
			for i in 0..a.count {
				let base = a.offset + i * stride;
				for c in 0..a.components {
					out[i * a.components + c] = a.kind.uint(data, base + c * a.kind.size());
				}
			}
		}
		if let Some(sparse) = &a.sparse {
			for (k, &target) in sparse.indices.iter().enumerate() {
				let target = target as usize;
				if target >= a.count {
					return Err(format!("accessor {index}: a sparse index is out of range"));
				}
				for c in 0..a.components {
					out[target * a.components + c] = a.kind.uint(sparse.values, (k * a.components + c) * a.kind.size());
				}
			}
		}
		Ok((out, a.components))
	}

	/// For a morph target: only the elements a sparse accessor changes, without expanding it
	/// (a model's face can have hundreds of targets, each touching few points).
	/// Returns None if the accessor is not sparse (then read it whole).
	pub fn sparse_vec3(&self, index: usize) -> Result<Option<(Vec<u32>, Vec<[f32; 3]>)>, String> {
		let a = Accessor::read(self, index)?;
		if a.view.is_some() || a.components != 3 {
			return Ok(None);
		}
		let Some(sparse) = &a.sparse else {
			return Ok(Some((Vec::new(), Vec::new())));
		};
		let mut values = Vec::with_capacity(sparse.indices.len());
		for k in 0..sparse.indices.len() {
			let f = |c: usize| a.kind.float(sparse.values, (k * 3 + c) * a.kind.size(), a.normalized);
			values.push([f(0), f(1), f(2)]);
		}
		if sparse.indices.iter().any(|&i| i as usize >= a.count) {
			return Err(format!("accessor {index}: a sparse index is out of range"));
		}
		Ok(Some((sparse.indices.clone(), values)))
	}

	/// How many elements an accessor has.
	#[allow(dead_code)]
	pub fn count(&self, index: usize) -> Result<usize, String> {
		let a = self.get("accessors").get(index).ok_or(format!("accessor {index} does not exist"))?;
		a.get("count").and_then(Value::as_u64).map(|c| c as usize).ok_or(format!("accessor {index} has no count"))
	}
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Kind {
	I8,
	U8,
	I16,
	U16,
	U32,
	F32,
}

impl Kind {
	fn from_code(code: u64) -> Result<Kind, String> {
		Ok(match code {
			5120 => Kind::I8,
			5121 => Kind::U8,
			5122 => Kind::I16,
			5123 => Kind::U16,
			5125 => Kind::U32,
			5126 => Kind::F32,
			other => return Err(format!("unknown number type {other}")),
		})
	}

	fn size(self) -> usize {
		match self {
			Kind::I8 | Kind::U8 => 1,
			Kind::I16 | Kind::U16 => 2,
			Kind::U32 | Kind::F32 => 4,
		}
	}

	fn float(self, data: &[u8], at: usize, normalized: bool) -> f32 {
		match self {
			Kind::F32 => f32::from_le_bytes([data[at], data[at + 1], data[at + 2], data[at + 3]]),
			Kind::U8 => {
				let v = data[at] as f32;
				if normalized { v / 255.0 } else { v }
			}
			Kind::I8 => {
				let v = data[at] as i8 as f32;
				if normalized { (v / 127.0).max(-1.0) } else { v }
			}
			Kind::U16 => {
				let v = u16::from_le_bytes([data[at], data[at + 1]]) as f32;
				if normalized { v / 65535.0 } else { v }
			}
			Kind::I16 => {
				let v = i16::from_le_bytes([data[at], data[at + 1]]) as f32;
				if normalized { (v / 32767.0).max(-1.0) } else { v }
			}
			Kind::U32 => u32::from_le_bytes([data[at], data[at + 1], data[at + 2], data[at + 3]]) as f32,
		}
	}

	fn uint(self, data: &[u8], at: usize) -> u32 {
		match self {
			Kind::U8 => data[at] as u32,
			Kind::I8 => data[at] as i8 as i32 as u32,
			Kind::U16 => u16::from_le_bytes([data[at], data[at + 1]]) as u32,
			Kind::I16 => i16::from_le_bytes([data[at], data[at + 1]]) as i32 as u32,
			Kind::U32 => u32::from_le_bytes([data[at], data[at + 1], data[at + 2], data[at + 3]]),
			Kind::F32 => f32::from_le_bytes([data[at], data[at + 1], data[at + 2], data[at + 3]]) as u32,
		}
	}
}

struct Sparse<'a> {
	indices: Vec<u32>,
	values: &'a [u8],
}

struct Accessor<'a> {
	kind: Kind,
	components: usize,
	count: usize,
	normalized: bool,
	offset: usize,
	view: Option<(&'a [u8], usize)>,
	sparse: Option<Sparse<'a>>,
}

impl<'a> Accessor<'a> {
	fn read(glb: &'a Glb, index: usize) -> Result<Accessor<'a>, String> {
		let a = glb.get("accessors").get(index).ok_or(format!("accessor {index} does not exist"))?;
		let kind = Kind::from_code(a.get("componentType").and_then(Value::as_u64).unwrap_or(0))
			.map_err(|e| format!("accessor {index}: {e}"))?;
		let components = match a.get("type").and_then(Value::as_str).unwrap_or("") {
			"SCALAR" => 1,
			"VEC2" => 2,
			"VEC3" => 3,
			"VEC4" => 4,
			"MAT4" => 16,
			other => return Err(format!("accessor {index}: unknown element type '{other}'")),
		};
		let count = a.get("count").and_then(Value::as_u64).ok_or(format!("accessor {index} has no count"))? as usize;
		if count > 16_000_000 {
			return Err(format!("accessor {index} is too large"));
		}
		let normalized = a.get("normalized").and_then(Value::as_bool).unwrap_or(false);
		let offset = a.get("byteOffset").and_then(Value::as_u64).unwrap_or(0) as usize;
		let element = kind.size() * components;
		let view = match a.get("bufferView").and_then(Value::as_u64) {
			Some(v) => {
				let (data, stride) = glb.view(v as usize)?;
				let stride = stride.unwrap_or(element).max(element);
				if count > 0 && offset + (count - 1) * stride + element > data.len() {
					return Err(format!("accessor {index} reaches past its data"));
				}
				Some((data, stride))
			}
			None => None,
		};
		let sparse = match a.get("sparse") {
			Some(s) => {
				let n = s.get("count").and_then(Value::as_u64).unwrap_or(0) as usize;
				let idx = s.get("indices").ok_or(format!("accessor {index}: sparse data without indices"))?;
				let ikind = Kind::from_code(idx.get("componentType").and_then(Value::as_u64).unwrap_or(0))?;
				let (idata, _) = glb.view(idx.get("bufferView").and_then(Value::as_u64).ok_or("sparse indices without data")? as usize)?;
				let ioff = idx.get("byteOffset").and_then(Value::as_u64).unwrap_or(0) as usize;
				if ioff + n * ikind.size() > idata.len() {
					return Err(format!("accessor {index}: sparse indices reach past their data"));
				}
				let indices = (0..n).map(|k| ikind.uint(idata, ioff + k * ikind.size())).collect();
				let vals = s.get("values").ok_or(format!("accessor {index}: sparse data without values"))?;
				let (vdata, _) = glb.view(vals.get("bufferView").and_then(Value::as_u64).ok_or("sparse values without data")? as usize)?;
				let voff = vals.get("byteOffset").and_then(Value::as_u64).unwrap_or(0) as usize;
				if voff + n * element > vdata.len() {
					return Err(format!("accessor {index}: sparse values reach past their data"));
				}
				Some(Sparse { indices, values: &vdata[voff..voff + n * element] })
			}
			None => None,
		};
		Ok(Accessor { kind, components, count, normalized, offset, view: view.map(|(d, s)| (d, s)), sparse })
	}
}

#[cfg(test)]
pub(crate) mod tests {
	use super::*;

	/// A GLB file from a description and binary data.
	pub fn build(json: &Value, bin: &[u8]) -> Vec<u8> {
		let mut text = serde_json::to_vec(json).unwrap();
		while text.len() % 4 != 0 {
			text.push(b' ');
		}
		let mut data = bin.to_vec();
		while data.len() % 4 != 0 {
			data.push(0);
		}
		let total = 12 + 8 + text.len() + 8 + data.len();
		let mut out = Vec::with_capacity(total);
		out.extend_from_slice(MAGIC);
		out.extend_from_slice(&2u32.to_le_bytes());
		out.extend_from_slice(&(total as u32).to_le_bytes());
		out.extend_from_slice(&(text.len() as u32).to_le_bytes());
		out.extend_from_slice(b"JSON");
		out.extend_from_slice(&text);
		out.extend_from_slice(&(data.len() as u32).to_le_bytes());
		out.extend_from_slice(b"BIN\0");
		out.extend_from_slice(&data);
		out
	}

	#[test]
	fn reads_plain_normalised_strided_and_sparse_accessors() {
		let mut bin = Vec::new();
		for v in [1.0f32, 2.0, 3.0, 4.0, 5.0, 6.0] {
			bin.extend_from_slice(&v.to_le_bytes());
		}
		bin.extend_from_slice(&[0, 255, 128, 0]); // u8 normalised
		bin.extend_from_slice(&[1u16.to_le_bytes(), 2u16.to_le_bytes()].concat()); // sparse indices
		for v in [9.0f32, 9.5, 9.75, 7.0, 7.5, 7.75] {
			bin.extend_from_slice(&v.to_le_bytes());
		}
		let json = serde_json::json!({
			"asset": {"version": "2.0"},
			"buffers": [{"byteLength": bin.len()}],
			"bufferViews": [
				{"buffer": 0, "byteOffset": 0, "byteLength": 24},
				{"buffer": 0, "byteOffset": 24, "byteLength": 4},
				{"buffer": 0, "byteOffset": 28, "byteLength": 4},
				{"buffer": 0, "byteOffset": 32, "byteLength": 24},
				{"buffer": 0, "byteOffset": 0, "byteLength": 24, "byteStride": 12}
			],
			"accessors": [
				{"bufferView": 0, "componentType": 5126, "count": 2, "type": "VEC3"},
				{"bufferView": 1, "componentType": 5121, "normalized": true, "count": 4, "type": "SCALAR"},
				{"componentType": 5126, "count": 3, "type": "VEC3",
				 "sparse": {"count": 2, "indices": {"bufferView": 2, "componentType": 5123},
				            "values": {"bufferView": 3}}},
				{"bufferView": 4, "byteOffset": 4, "componentType": 5126, "count": 2, "type": "VEC2"}
			]
		});
		let glb = Glb::parse(build(&json, &bin)).unwrap();
		assert_eq!(glb.floats(0).unwrap(), (vec![1.0, 2.0, 3.0, 4.0, 5.0, 6.0], 3));
		let (n, _) = glb.floats(1).unwrap();
		assert!((n[1] - 1.0).abs() < 1e-6 && (n[2] - 128.0 / 255.0).abs() < 1e-6);
		let (s, _) = glb.floats(2).unwrap();
		assert_eq!(s, vec![0.0, 0.0, 0.0, 9.0, 9.5, 9.75, 7.0, 7.5, 7.75]);
		let (ids, vals) = glb.sparse_vec3(2).unwrap().unwrap();
		assert_eq!(ids, vec![1, 2]);
		assert_eq!(vals[1], [7.0, 7.5, 7.75]);
		assert_eq!(glb.floats(3).unwrap().0, vec![2.0, 3.0, 5.0, 6.0], "strided, from an offset");
	}

	#[test]
	fn refuses_damaged_files() {
		assert!(Glb::parse(b"glTF".to_vec()).is_err());
		let json = serde_json::json!({"accessors": [{"bufferView": 0, "componentType": 5126, "count": 100, "type": "VEC3"}],
			"bufferViews": [{"buffer": 0, "byteLength": 8}], "buffers": [{"byteLength": 8}]});
		let glb = Glb::parse(build(&json, &[0; 8])).unwrap();
		assert!(glb.floats(0).is_err(), "reaches past its data");
		let mut cut = build(&json, &[0; 8]);
		cut.truncate(30);
		assert!(Glb::parse(cut).is_err());
	}
}
