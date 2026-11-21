//! A Live2D-format model's own motions (`.motion3.json`), as its artist made them. The model's idle
//! motions play all the time, under the device's own movement.
//!
//! Live2D's own player (the Cubism SDK's sample) plays a model's idle motions one after another,
//! picked at random, each faded in and out. The device does the same, with these differences:
//!
//! - **A base, not a replacement.** The motion is a starting pose that the device's own movement adds
//!   to. Where the motion turns the head 8 degrees, a nod nods from there; where it raises an arm, the
//!   breathing still shows. The device's movement was made to stand on its own, so a motion's change
//!   from the model's rest pose is added, the way Live2D's player adds dragging and breathing to a
//!   motion.
//! - **Giving way.** A gesture holding part of the body (a wave holds an arm, a nod the head) takes most
//!   of that part back from the motion while it plays. The motion also shows less while the character
//!   listens or talks, and less again while it dozes.
//! - **Blinks and the mouth stay the device's.** Its blinks follow speech and where it looks, and its
//!   mouth follows the voice, so a motion's own blinks and mouth opening (the model's `EyeBlink` and
//!   `LipSync` groups) are left out.
//! - **Crossfades.** The next motion fades in while the last fades out, instead of each returning to
//!   rest first.
//!
//! Curves are read as Cubism reads them: linear, Bézier, stepped and inverse-stepped segments; Béziers
//! solved for time with Cubism's own method unless the file says they are restricted; sine-eased fades
//! in and out for each motion and for single curves; and part-opacity curves choosing which part of a
//! pose group shows (a model drawn with two sets of arms), faded as Cubism's pose does.

use std::f32::consts::PI;

use glam::Vec2;

/// Cubism's fade when neither the model nor the motion gives one, in seconds.
pub const DEFAULT_FADE: f32 = 1.0;
/// Cubism's pose fade when the pose file gives none.
const DEFAULT_POSE_FADE: f32 = 0.5;
/// Looping motions shorter than this play again before the next is picked.
const MIN_SPELL: f32 = 4.0;
/// Limits for one motion file.
const MAX_CURVES: usize = 4096;
const MAX_POINTS: usize = 1 << 20;
/// Cubism's tolerance in its curve maths.
const EPSILON: f32 = 0.00001;

/// What a curve moves.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Target {
	/// The whole model: its opacity, or how much of the model's blinking and lip sync shows.
	Model,
	Parameter,
	/// A part's opacity, which chooses the part shown in its pose group.
	PartOpacity,
}

#[derive(Clone, Copy, Debug, PartialEq)]
enum Kind {
	Linear,
	Bezier,
	Stepped,
	InverseStepped,
}

#[derive(Clone, Debug)]
pub struct Curve {
	pub target: Target,
	pub id: String,
	/// The curve's own fades, when it has them (otherwise the motion's).
	fade_in: Option<f32>,
	fade_out: Option<f32>,
	/// (time, value) points; each segment starts at its point and ends one point later (three for a
	/// Bézier, whose two control points come between).
	points: Vec<[f32; 2]>,
	segments: Vec<(Kind, usize)>,
}

/// One motion file, read.
#[derive(Clone, Debug)]
pub struct Motion {
	pub name: String,
	pub duration: f32,
	pub looped: bool,
	pub fade_in: f32,
	pub fade_out: f32,
	/// Béziers are solved for time exactly (Cubism's "Cardano" reading), unless the file says its
	/// control points are restricted, when time is taken as the curve's own parameter.
	exact_beziers: bool,
	pub curves: Vec<Curve>,
}

fn number(v: &serde_json::Value, key: &str) -> Option<f32> {
	v.get(key).and_then(serde_json::Value::as_f64).map(|x| x as f32).filter(|x| x.is_finite())
}

/// Read a motion file. `fade_in` and `fade_out` are the model's own choice for it (from its
/// `.model3.json`), which wins over the file's; Cubism's default of a second is used when neither says.
pub fn parse_motion(name: &str, bytes: &[u8], fade_in: Option<f32>, fade_out: Option<f32>) -> Result<Motion, String> {
	let v: serde_json::Value = serde_json::from_slice(bytes).map_err(|e| format!("motion {name}: {e}"))?;
	let meta = v.get("Meta").ok_or(format!("motion {name} has no Meta"))?;
	let list = v.get("Curves").and_then(|c| c.as_array()).ok_or(format!("motion {name} has no curves"))?;
	if list.len() > MAX_CURVES {
		return Err(format!("motion {name} has more than {MAX_CURVES} curves"));
	}
	let mut curves = Vec::new();
	let mut points_seen = 0;
	let mut last_time = 0.0f32;
	for c in list {
		let target = match c.get("Target").and_then(|t| t.as_str()) {
			Some("Model") => Target::Model,
			Some("Parameter") => Target::Parameter,
			Some("PartOpacity") => Target::PartOpacity,
			_ => continue,
		};
		let Some(id) = c.get("Id").and_then(|i| i.as_str()) else { continue };
		let raw = c.get("Segments").and_then(|s| s.as_array()).ok_or(format!("motion {name}: curve {id} has no segments"))?;
		let numbers: Vec<f32> = raw
			.iter()
			.map(|x| x.as_f64().map(|f| f as f32).filter(|f| f.is_finite()))
			.collect::<Option<_>>()
			.ok_or(format!("motion {name}: curve {id} has something that is not a number"))?;
		let (points, segments) = parse_segments(&numbers).map_err(|e| format!("motion {name}: curve {id} {e}"))?;
		points_seen += points.len();
		if points_seen > MAX_POINTS {
			return Err(format!("motion {name} has more than {MAX_POINTS} points"));
		}
		last_time = last_time.max(points.iter().map(|p| p[0]).fold(0.0, f32::max));
		let fade = |key: &str| number(c, key).filter(|t| *t >= 0.0);
		curves.push(Curve {
			target,
			id: id.to_string(),
			fade_in: fade("FadeInTime"),
			fade_out: fade("FadeOutTime"),
			points,
			segments,
		});
	}
	let duration = number(meta, "Duration").filter(|d| *d > 0.0).unwrap_or(last_time);
	if duration <= 0.0 {
		return Err(format!("motion {name} lasts no time"));
	}
	let own = |key: &str| number(meta, key).filter(|t| *t >= 0.0);
	Ok(Motion {
		name: name.to_string(),
		duration,
		looped: meta.get("Loop").and_then(|l| l.as_bool()).unwrap_or(false),
		fade_in: fade_in.filter(|t| t.is_finite() && *t >= 0.0).or(own("FadeInTime")).unwrap_or(DEFAULT_FADE),
		fade_out: fade_out.filter(|t| t.is_finite() && *t >= 0.0).or(own("FadeOutTime")).unwrap_or(DEFAULT_FADE),
		exact_beziers: !meta.get("AreBeziersRestricted").and_then(|b| b.as_bool()).unwrap_or(false),
		curves,
	})
}

/// A curve's numbers: its first point, then each segment as its type and the points that end it.
fn parse_segments(n: &[f32]) -> Result<(Vec<[f32; 2]>, Vec<(Kind, usize)>), String> {
	if n.len() < 2 {
		return Err("has no points".into());
	}
	let mut points = vec![[n[0], n[1]]];
	let mut segments = Vec::new();
	let mut i = 2;
	while i < n.len() {
		let (kind, count) = match n[i] {
			k if k == 0.0 => (Kind::Linear, 1),
			k if k == 1.0 => (Kind::Bezier, 3),
			k if k == 2.0 => (Kind::Stepped, 1),
			k if k == 3.0 => (Kind::InverseStepped, 1),
			k => return Err(format!("has a segment of unknown type {k}")),
		};
		if i + 2 * count >= n.len() {
			return Err("ends part way through a segment".into());
		}
		segments.push((kind, points.len() - 1));
		for k in 0..count {
			points.push([n[i + 1 + 2 * k], n[i + 2 + 2 * k]]);
		}
		i += 1 + 2 * count;
	}
	Ok((points, segments))
}

fn lerp(a: [f32; 2], b: [f32; 2], t: f32) -> [f32; 2] {
	[a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]
}

/// The value of a cubic Bézier at parameter `t` (de Casteljau, as Cubism does it).
fn bezier_at(p: &[[f32; 2]], t: f32) -> f32 {
	let p01 = lerp(p[0], p[1], t);
	let p12 = lerp(p[1], p[2], t);
	let p23 = lerp(p[2], p[3], t);
	lerp(lerp(p01, p12, t), lerp(p12, p23, t), t)[1]
}

/// Cubism's solution of a quadratic, for a cubic whose first term vanishes.
fn quadratic(a: f32, b: f32, c: f32) -> f32 {
	if a.abs() < EPSILON {
		if b.abs() < EPSILON {
			return -c;
		}
		return -c / b;
	}
	-(b + (b * b - 4.0 * a * c).sqrt()) / (2.0 * a)
}

/// Cubism's root of `a t³ + b t² + c t + d = 0` in 0..1 (its `CardanoAlgorithmForBezier`): the curve
/// parameter at which a Bézier segment reaches a time.
fn cardano(a: f32, b: f32, c: f32, d: f32) -> f32 {
	if a.abs() < EPSILON {
		return quadratic(b, c, d).clamp(0.0, 1.0);
	}
	let ba = b / a;
	let ca = c / a;
	let da = d / a;
	let p = (3.0 * ca - ba * ba) / 3.0;
	let p3 = p / 3.0;
	let q = (2.0 * ba * ba * ba - 9.0 * ba * ca + 27.0 * da) / 27.0;
	let q2 = q / 2.0;
	let discriminant = q2 * q2 + p3 * p3 * p3;
	let center = 0.5f32;
	let threshold = center + 0.01;
	if discriminant < 0.0 {
		let mp3 = -p / 3.0;
		let r = (mp3 * mp3 * mp3).sqrt();
		let cosphi = (-q / (2.0 * r)).clamp(-1.0, 1.0);
		let phi = cosphi.acos();
		let t1 = 2.0 * r.cbrt();
		let root1 = t1 * (phi / 3.0).cos() - ba / 3.0;
		if (root1 - center).abs() < threshold {
			return root1.clamp(0.0, 1.0);
		}
		let root2 = t1 * ((phi + 2.0 * PI) / 3.0).cos() - ba / 3.0;
		if (root2 - center).abs() < threshold {
			return root2.clamp(0.0, 1.0);
		}
		let root3 = t1 * ((phi + 4.0 * PI) / 3.0).cos() - ba / 3.0;
		return root3.clamp(0.0, 1.0);
	}
	if discriminant == 0.0 {
		let u1 = if q2 < 0.0 { (-q2).cbrt() } else { -q2.cbrt() };
		let root1 = 2.0 * u1 - ba / 3.0;
		if (root1 - center).abs() < threshold {
			return root1.clamp(0.0, 1.0);
		}
		return (-u1 - ba / 3.0).clamp(0.0, 1.0);
	}
	let sd = discriminant.sqrt();
	let u1 = (sd - q2).cbrt();
	let v1 = (sd + q2).cbrt();
	(u1 - v1 - ba / 3.0).clamp(0.0, 1.0)
}

impl Curve {
	/// The curve's value at `time` seconds into its motion. Before the first point it holds the first
	/// value, after the last point the last, as Cubism does.
	pub fn value(&self, time: f32, exact_beziers: bool) -> f32 {
		for &(kind, base) in &self.segments {
			let end = base + if kind == Kind::Bezier { 3 } else { 1 };
			if self.points[end][0] <= time {
				continue;
			}
			let p = &self.points[base..=end];
			return match kind {
				Kind::Linear => {
					let span = p[1][0] - p[0][0];
					if span <= 0.0 {
						return p[1][1];
					}
					let t = ((time - p[0][0]) / span).clamp(0.0, 1.0);
					p[0][1] + (p[1][1] - p[0][1]) * t
				}
				Kind::Bezier => {
					let span = p[3][0] - p[0][0];
					let simple = if span > 0.0 { ((time - p[0][0]) / span).clamp(0.0, 1.0) } else { 1.0 };
					let t = if exact_beziers {
						let (x1, cx1, cx2, x2) = (p[0][0], p[1][0], p[2][0], p[3][0]);
						let t = cardano(x2 - 3.0 * cx2 + 3.0 * cx1 - x1, 3.0 * cx2 - 6.0 * cx1 + 3.0 * x1, 3.0 * cx1 - 3.0 * x1, x1 - time);
						if t.is_finite() { t } else { simple }
					} else {
						simple
					};
					bezier_at(p, t)
				}
				Kind::Stepped => p[0][1],
				Kind::InverseStepped => p[1][1],
			};
		}
		self.points.last().map(|p| p[1]).unwrap_or(0.0)
	}
}

/// Cubism's easing for fades: 0 before, 1 after, a half sine between.
pub fn ease(x: f32) -> f32 {
	if x <= 0.0 {
		0.0
	} else if x >= 1.0 {
		1.0
	} else {
		0.5 - 0.5 * (x * PI).cos()
	}
}

// ------------------------------------------------------------------------------------------------
// The pose: parts that take turns
// ------------------------------------------------------------------------------------------------

#[derive(Clone, Debug)]
struct PosePart {
	id: String,
	links: Vec<String>,
	/// Shown this much now.
	opacity: f32,
	/// What motions last asked of it: more than nothing means "show this one".
	chosen: f32,
}

/// A pose file's (`.pose3.json`) groups of parts shown one at a time, such as two sets of arms. The
/// first of each group shows until a motion's part-opacity curve chooses another, which then fades in
/// while the rest fade out, as Cubism's pose does.
#[derive(Clone, Debug)]
pub struct PoseGroups {
	fade: f32,
	groups: Vec<Vec<PosePart>>,
}

impl PoseGroups {
	pub fn parse(bytes: &[u8]) -> Result<Self, String> {
		let value: serde_json::Value = serde_json::from_slice(bytes).map_err(|e| format!("the pose file cannot be read: {e}"))?;
		let list = value.get("Groups").and_then(|g| g.as_array()).ok_or("the pose file has no groups")?;
		let fade = number(&value, "FadeInTime").filter(|t| *t > 0.0).unwrap_or(DEFAULT_POSE_FADE);
		let mut groups = Vec::new();
		for group in list {
			let mut parts = Vec::new();
			for entry in group.as_array().into_iter().flatten() {
				let Some(id) = entry.get("Id").and_then(|v| v.as_str()) else { continue };
				let links = entry
					.get("Link")
					.and_then(|l| l.as_array())
					.into_iter()
					.flatten()
					.filter_map(|l| l.as_str().map(str::to_string))
					.collect();
				let first = parts.is_empty();
				let shown = if first { 1.0 } else { 0.0 };
				parts.push(PosePart { id: id.to_string(), links, opacity: shown, chosen: shown });
			}
			if !parts.is_empty() {
				groups.push(parts);
			}
		}
		Ok(PoseGroups { fade, groups })
	}

	/// A motion's part-opacity curve: more than nothing chooses the part. Whether the part is in a group.
	pub fn choose(&mut self, id: &str, value: f32) -> bool {
		for part in self.groups.iter_mut().flatten() {
			if part.id == id {
				part.chosen = value;
				return true;
			}
		}
		false
	}

	/// Fade the chosen part of each group in and the others out (Cubism's `CubismPose::DoFade`: the
	/// others fade so that little of what is behind shows through on the way).
	pub fn update(&mut self, dt: f32) {
		const PHI: f32 = 0.5;
		const BACK_OPACITY_THRESHOLD: f32 = 0.15;
		let step = if self.fade > 0.0 { dt.max(0.0) / self.fade } else { 1.0 };
		for group in &mut self.groups {
			let shown = group.iter().position(|p| p.chosen > 0.001);
			let (shown, new) = match shown {
				Some(i) => (i, (group[i].opacity + step).min(1.0)),
				None => (0, 1.0),
			};
			for (i, part) in group.iter_mut().enumerate() {
				if i == shown {
					part.opacity = new;
					continue;
				}
				let mut a1 = if new < PHI { new * (PHI - 1.0) / PHI + 1.0 } else { (1.0 - new) * PHI / (1.0 - PHI) };
				let back = (1.0 - a1) * (1.0 - new);
				if back > BACK_OPACITY_THRESHOLD {
					a1 = 1.0 - BACK_OPACITY_THRESHOLD / (1.0 - new);
				}
				part.opacity = part.opacity.min(a1);
			}
		}
	}

	/// Every part in the groups, and the parts linked to each, with the opacity it shows at.
	pub fn opacities(&self) -> Vec<(String, f32)> {
		let mut out = Vec::new();
		for part in self.groups.iter().flatten() {
			out.push((part.id.clone(), part.opacity));
			for link in &part.links {
				out.push((link.clone(), part.opacity));
			}
		}
		out
	}
}

// ------------------------------------------------------------------------------------------------
// Playing the idle motions
// ------------------------------------------------------------------------------------------------

#[derive(Clone, Debug)]
struct Playing {
	motion: usize,
	/// Seconds since it started.
	t: f32,
	/// When (in its own time) it starts fading out and the next one starts.
	plan: f32,
	/// When it has faded out, once it has begun to.
	until: Option<f32>,
}

/// A model's idle motions, played one after another.
#[derive(Clone, Debug)]
pub struct IdleMotions {
	motions: Vec<Motion>,
	playing: Vec<Playing>,
	/// Parameters left to the device: its blinks and its mouth.
	skip: Vec<String>,
	rng: u64,
	last: Option<usize>,
}

impl IdleMotions {
	/// `skip` names the parameters the motions leave alone.
	pub fn new(motions: Vec<Motion>, skip: Vec<String>, seed: u64) -> Self {
		IdleMotions { motions, playing: Vec::new(), skip, rng: seed.max(1), last: None }
	}

	/// Start the random choices again from `seed` (a fixed one for tests, the time on the device).
	pub fn reseed(&mut self, seed: u64) {
		self.rng = seed.max(1);
	}

	/// Leave these parameters to the device as well.
	pub fn leave(&mut self, names: impl IntoIterator<Item = String>) {
		for name in names {
			if !self.skip.contains(&name) {
				self.skip.push(name);
			}
		}
	}

	pub fn names(&self) -> Vec<String> {
		self.motions.iter().map(|m| m.name.clone()).collect()
	}

	/// The motion playing (the newest, if two are crossfading).
	pub fn current(&self) -> Option<&str> {
		self.playing.last().map(|p| self.motions[p.motion].name.as_str())
	}

	fn random(&mut self) -> f32 {
		self.rng ^= self.rng >> 12;
		self.rng ^= self.rng << 25;
		self.rng ^= self.rng >> 27;
		((self.rng.wrapping_mul(0x2545_F491_4F6C_DD1D) >> 40) as f32) / ((1u64 << 24) as f32)
	}

	/// The next motion: any but the last one, when there is a choice.
	fn pick(&mut self) -> usize {
		let n = self.motions.len();
		let choices = if n > 1 && self.last.is_some() { n - 1 } else { n };
		let mut i = ((self.random() * choices as f32) as usize).min(choices - 1);
		if let Some(last) = self.last {
			if n > 1 && i >= last {
				i += 1;
			}
		}
		self.last = Some(i);
		i
	}

	/// How long a motion plays before the next takes over: once (a looping one that is short plays
	/// until it has lasted a few seconds, and sometimes once more); for ever, if it loops and is the
	/// only one.
	fn plan(&mut self, i: usize) -> f32 {
		let (duration, looped, fade_out) = {
			let m = &self.motions[i];
			(m.duration, m.looped, m.fade_out)
		};
		if looped && self.motions.len() == 1 {
			return f32::INFINITY;
		}
		let mut plays = 1.0;
		if looped {
			plays = (MIN_SPELL / duration).ceil().max(1.0);
			if self.random() < 0.3 {
				plays += 1.0;
			}
		}
		(plays * duration - fade_out).max(0.1)
	}

	/// Move on by `dt` seconds: the next motion starts as the one before begins to fade out.
	pub fn step(&mut self, dt: f32) {
		if self.motions.is_empty() {
			return;
		}
		for p in &mut self.playing {
			p.t += dt.max(0.0);
		}
		self.playing.retain(|p| p.until.is_none_or(|u| p.t < u));
		let due = match self.playing.last() {
			None => true,
			Some(p) => p.until.is_none() && p.t >= p.plan,
		};
		if due {
			if let Some(p) = self.playing.last_mut() {
				p.until = Some(p.t + self.motions[p.motion].fade_out);
			}
			let next = self.pick();
			let plan = self.plan(next);
			self.playing.push(Playing { motion: next, t: 0.0, plan, until: None });
		}
		if self.playing.len() > 3 {
			let extra = self.playing.len() - 3;
			self.playing.drain(..extra);
		}
	}

	/// Each parameter the motions move now, and how far from its default: Cubism's way of laying one
	/// motion over another (each moves the value toward its own by its weight), counted from the
	/// default. Part-opacity curves go to the pose.
	pub fn changes(&self, default: impl Fn(&str) -> Option<f32>, mut pose: Option<&mut PoseGroups>) -> Vec<(String, f32)> {
		let mut out: Vec<(String, f32)> = Vec::new();
		for p in &self.playing {
			let m = &self.motions[p.motion];
			let fade_in = if m.fade_in > 0.0 { ease(p.t / m.fade_in) } else { 1.0 };
			let fade_out = match p.until {
				Some(u) if m.fade_out > 0.0 => ease((u - p.t) / m.fade_out),
				_ => 1.0,
			};
			let time = if m.looped { p.t % m.duration } else { p.t };
			for c in &m.curves {
				match c.target {
					Target::Model => {}
					Target::PartOpacity => {
						if let Some(pose) = pose.as_deref_mut() {
							pose.choose(&c.id, c.value(time, m.exact_beziers));
						}
					}
					Target::Parameter => {
						if self.skip.iter().any(|s| s == &c.id) {
							continue;
						}
						let Some(rest) = default(&c.id) else { continue };
						let w = if c.fade_in.is_none() && c.fade_out.is_none() {
							fade_in * fade_out
						} else {
							let fin = match c.fade_in {
								None => fade_in,
								Some(f) if f > 0.0 => ease(p.t / f),
								Some(_) => 1.0,
							};
							let fout = match (c.fade_out, p.until) {
								(None, _) => fade_out,
								(Some(f), Some(u)) if f > 0.0 => ease((u - p.t) / f),
								_ => 1.0,
							};
							fin * fout
						};
						let target = c.value(time, m.exact_beziers) - rest;
						match out.iter_mut().find(|(id, _)| id == &c.id) {
							Some((_, d)) => *d += (target - *d) * w,
							None => out.push((c.id.clone(), target * w)),
						}
					}
				}
			}
		}
		out
	}
}

/// The part of the body (a motion system channel, `motion::CHANNELS`) a Live2D standard parameter
/// belongs to, by its name, for parameters the device's controls do not use.
pub fn channel_by_name(id: &str) -> Option<usize> {
	let s = id.to_ascii_lowercase();
	let name = if s.starts_with("parambodyangle") || s.starts_with("paramshoulder") {
		"torso"
	} else if s.starts_with("paramangle") {
		"head"
	} else if s.starts_with("parameyeball") {
		"eyes"
	} else if s.starts_with("parambrow") {
		"brows"
	} else if s.contains("smile") || s == "parammouthform" || s == "paramcheek" {
		"expression"
	} else if s.starts_with("paramarml") || s.starts_with("paramhandl") {
		"arm_left"
	} else if s.starts_with("paramarmr") || s.starts_with("paramhandr") {
		"arm_right"
	} else if s.starts_with("parammouth") {
		"mouth"
	} else if s.starts_with("parameyel") || s.starts_with("parameyer") {
		"eyelids"
	} else {
		return None;
	};
	crate::motion::CHANNELS.iter().position(|n| *n == name)
}

/// Add the motions' changes to this frame's values, each by its share (`share` of a parameter: how much
/// of the motion shows on it now), keeping every value inside its parameter's range.
pub fn add_changes(
	values: &mut Vec<(String, Vec2)>,
	changes: &[(String, f32)],
	range: impl Fn(&str) -> Option<(f32, f32, f32)>,
	share: impl Fn(&str) -> f32,
) {
	for (id, change) in changes {
		let Some((min, max, rest)) = range(id) else { continue };
		let w = share(id);
		if w <= 0.0 || *change == 0.0 {
			continue;
		}
		let i = match values.iter().position(|(n, _)| n == id) {
			Some(i) => i,
			None => {
				values.push((id.clone(), Vec2::new(rest, 0.0)));
				values.len() - 1
			}
		};
		let v = &mut values[i].1.x;
		*v = (*v + change * w).clamp(min.min(max), max.max(min));
	}
}

#[cfg(test)]
mod tests {
	use super::*;

	fn motion(json: &str) -> Motion {
		parse_motion("test", json.as_bytes(), None, None).unwrap()
	}

	fn curve_of(m: &Motion, id: &str) -> Curve {
		m.curves.iter().find(|c| c.id == id).unwrap().clone()
	}

	#[test]
	fn reads_every_kind_of_segment() {
		// 0..1 linear to 10; 1..2 stepped (holds 10, then 20); 2..3 inverse stepped (jumps to 30);
		// 3..4 a Bézier to 40 whose handles lie on the straight line.
		let m = motion(
			r#"{"Version": 3, "Meta": {"Duration": 4, "Fps": 30, "Loop": true, "AreBeziersRestricted": true},
			"Curves": [{"Target": "Parameter", "Id": "ParamAngleX", "Segments":
			[0, 0, 0, 1, 10, 2, 2, 20, 3, 3, 30, 1, 3.333, 33.33, 3.667, 36.67, 4, 40]}]}"#,
		);
		let c = curve_of(&m, "ParamAngleX");
		let at = |t: f32| c.value(t, m.exact_beziers);
		assert_eq!(at(-1.0), 0.0, "before the first point, the first value");
		assert!((at(0.5) - 5.0).abs() < 1e-5);
		assert_eq!(at(1.5), 10.0, "a stepped segment holds its start");
		assert_eq!(at(2.5), 30.0, "an inverse-stepped segment jumps to its end");
		assert!((at(3.5) - 35.0).abs() < 0.01, "{}", at(3.5));
		assert_eq!(at(9.0), 40.0, "after the last point, the last value");
		assert!(m.looped && (m.duration - 4.0).abs() < 1e-6);
		assert_eq!(m.fade_in, DEFAULT_FADE);
	}

	#[test]
	fn exact_beziers_follow_the_time_axis() {
		// Handles pulled toward the start in time: the curve gets most of the way early. Read with time
		// as the curve's own parameter (restricted), the middle is the plain average; read exactly, it is
		// further along.
		let json = |restricted: bool| {
			format!(
				r#"{{"Meta": {{"Duration": 1, "AreBeziersRestricted": {restricted}}}, "Curves": [{{"Target": "Parameter",
				"Id": "P", "Segments": [0, 0, 1, 0.05, 1, 0.1, 1, 1, 1]}}]}}"#
			)
		};
		let simple = motion(&json(true));
		let exact = motion(&json(false));
		let s = curve_of(&simple, "P").value(0.5, simple.exact_beziers);
		let e = curve_of(&exact, "P").value(0.5, exact.exact_beziers);
		assert!((s - 0.875).abs() < 1e-4, "{s}");
		assert!(e > 0.95 && e <= 1.0, "{e}");
		// On a straight line in time the two agree.
		let line = motion(r#"{"Meta": {"Duration": 3}, "Curves": [{"Target": "Parameter", "Id": "P", "Segments": [0, 0, 1, 1, 1, 2, 2, 3, 3]}]}"#);
		for t in [0.3f32, 1.5, 2.7] {
			assert!((curve_of(&line, "P").value(t, true) - t).abs() < 1e-3, "{t}");
		}
	}

	#[test]
	fn cubisms_cubic_root_lands_inside_the_segment() {
		// t³ - 0.125 = 0 has its root at 0.5.
		assert!((cardano(1.0, 0.0, 0.0, -0.125) - 0.5).abs() < 1e-5);
		// A first term that vanishes falls back to the quadratic (here linear: 2t - 1 = 0).
		assert!((cardano(0.0, 0.0, 2.0, -1.0) - 0.5).abs() < 1e-6);
		// Never outside 0..1.
		for d in [-5.0f32, -1.0, 0.0, 1.0, 5.0] {
			let t = cardano(1.0, -1.5, 0.75, d);
			assert!((0.0..=1.0).contains(&t), "{d}: {t}");
		}
	}

	#[test]
	fn broken_motion_files_are_refused() {
		assert!(parse_motion("x", b"not json", None, None).is_err());
		assert!(parse_motion("x", br#"{"Curves": []}"#, None, None).is_err(), "no Meta");
		let bad_type = br#"{"Meta": {"Duration": 1}, "Curves": [{"Target": "Parameter", "Id": "P", "Segments": [0, 0, 7, 1, 1]}]}"#;
		assert!(parse_motion("x", bad_type, None, None).is_err());
		let cut_short = br#"{"Meta": {"Duration": 1}, "Curves": [{"Target": "Parameter", "Id": "P", "Segments": [0, 0, 1, 0.3, 0.3, 0.6]}]}"#;
		assert!(parse_motion("x", cut_short, None, None).is_err());
		let no_time = br#"{"Meta": {}, "Curves": [{"Target": "Parameter", "Id": "P", "Segments": [0, 1]}]}"#;
		assert!(parse_motion("x", no_time, None, None).is_err());
		// The model's own fade times win over the file's.
		let m = parse_motion("x", br#"{"Meta": {"Duration": 2, "FadeInTime": 0.2}, "Curves": []}"#, Some(0.5), None).unwrap();
		assert_eq!((m.fade_in, m.fade_out), (0.5, DEFAULT_FADE));
	}

	fn idle(json: &[&str], skip: &[&str]) -> IdleMotions {
		let motions = json.iter().enumerate().map(|(i, j)| parse_motion(&format!("m{i}"), j.as_bytes(), Some(0.5), Some(0.5)).unwrap()).collect();
		IdleMotions::new(motions, skip.iter().map(|s| s.to_string()).collect(), 7)
	}

	const HEAD: &str = r#"{"Meta": {"Duration": 2, "Loop": true}, "Curves": [
		{"Target": "Parameter", "Id": "ParamAngleX", "Segments": [0, 10, 0, 2, 10]},
		{"Target": "Parameter", "Id": "ParamEyeLOpen", "Segments": [0, 0, 0, 2, 0]},
		{"Target": "PartOpacity", "Id": "PartArmA", "Segments": [0, 0, 0, 2, 0]},
		{"Target": "PartOpacity", "Id": "PartArmB", "Segments": [0, 1, 0, 2, 1]}]}"#;
	const BODY: &str = r#"{"Meta": {"Duration": 3}, "Curves": [
		{"Target": "Parameter", "Id": "ParamAngleX", "Segments": [0, -10, 0, 3, -10]},
		{"Target": "Parameter", "Id": "ParamBodyAngleX", "Segments": [0, 5, 0, 3, 5]}]}"#;

	fn rest(id: &str) -> Option<f32> {
		match id {
			"ParamEyeLOpen" => Some(1.0),
			"ParamAngleX" | "ParamBodyAngleX" => Some(0.0),
			_ => None,
		}
	}

	fn change(c: &[(String, f32)], id: &str) -> f32 {
		c.iter().find(|(n, _)| n == id).map(|(_, v)| *v).unwrap_or(0.0)
	}

	#[test]
	fn a_motion_fades_in_from_rest_and_leaves_blinks_to_the_device() {
		let mut m = idle(&[HEAD], &["ParamEyeLOpen"]);
		m.step(0.0);
		assert_eq!(change(&m.changes(rest, None), "ParamAngleX"), 0.0, "starts at rest");
		m.step(0.25);
		let half = change(&m.changes(rest, None), "ParamAngleX");
		assert!((half - 5.0).abs() < 1e-4, "half way through a 0.5 s sine fade: {half}");
		m.step(1.0);
		let c = m.changes(rest, None);
		assert!((change(&c, "ParamAngleX") - 10.0).abs() < 1e-4);
		assert!(c.iter().all(|(n, _)| n != "ParamEyeLOpen"), "the motion's eyes are left to the device");
		// The only motion, looping: it plays on for ever.
		for _ in 0..100 {
			m.step(0.5);
		}
		assert_eq!(m.playing.len(), 1);
		assert!((change(&m.changes(rest, None), "ParamAngleX") - 10.0).abs() < 1e-4);
	}

	#[test]
	fn the_next_motion_crossfades_in_and_differs_from_the_last() {
		let mut m = idle(&[HEAD, BODY], &[]);
		let mut seen = Vec::new();
		let mut was = String::new();
		let mut biggest_jump = 0.0f32;
		let mut previous = 0.0;
		for _ in 0..2000 {
			m.step(0.02);
			let now = m.current().unwrap().to_string();
			if now != was {
				seen.push(now.clone());
				was = now;
			}
			assert!(m.playing.len() <= 2, "at most two at once");
			let x = change(&m.changes(rest, None), "ParamAngleX");
			biggest_jump = biggest_jump.max((x - previous).abs());
			previous = x;
		}
		assert!(seen.len() > 5, "{seen:?}");
		assert!(seen.windows(2).all(|w| w[0] != w[1]), "never the same one twice running: {seen:?}");
		// From +10 to -10 without a jump: a 0.5 s crossfade moves at most about 1.3 per 20 ms frame.
		assert!(biggest_jump < 1.5, "{biggest_jump}");
	}

	#[test]
	fn part_opacity_curves_choose_the_part_shown_and_it_fades_in() {
		let pose = br#"{"Type": "Live2D Pose", "FadeInTime": 0.5, "Groups": [
			[{"Id": "PartArmA", "Link": ["PartHandA"]}, {"Id": "PartArmB", "Link": ["PartHandB"]}]]}"#;
		let mut groups = PoseGroups::parse(pose).unwrap();
		groups.update(0.016);
		let shown = |g: &PoseGroups, id: &str| g.opacities().into_iter().find(|(n, _)| n == id).unwrap().1;
		assert_eq!((shown(&groups, "PartArmA"), shown(&groups, "PartHandA"), shown(&groups, "PartArmB")), (1.0, 1.0, 0.0));
		// A motion asks for the second set of arms.
		let mut m = idle(&[HEAD], &[]);
		m.step(0.1);
		m.changes(rest, Some(&mut groups));
		groups.update(0.25);
		let (a, b) = (shown(&groups, "PartArmA"), shown(&groups, "PartArmB"));
		assert!(b > 0.4 && b < 0.6 && a < 1.0 && a > 0.0, "half way: {a} {b}");
		assert_eq!(shown(&groups, "PartHandB"), b, "linked parts follow");
		for _ in 0..20 {
			groups.update(0.05);
		}
		assert_eq!((shown(&groups, "PartArmA"), shown(&groups, "PartArmB")), (0.0, 1.0));
		assert!(!groups.choose("PartHat", 1.0), "a part in no group");
		assert!(PoseGroups::parse(b"{}").is_err());
	}

	/// Real motion files, if a folder of them is given (Live2D's sample models are not in the
	/// repository): every curve reaches each of its points, and moves smoothly between them.
	#[test]
	fn sample_motions_hit_their_points_and_do_not_jump() {
		let Ok(dir) = std::env::var("COMPANION_LIVE2D_MOTIONS") else { return };
		let mut files = 0;
		let mut checked = 0;
		for entry in std::fs::read_dir(&dir).unwrap() {
			let path = entry.unwrap().path();
			if !path.to_string_lossy().ends_with(".motion3.json") {
				continue;
			}
			let m = parse_motion("sample", &std::fs::read(&path).unwrap(), None, None).unwrap();
			files += 1;
			for c in &m.curves {
				let lo = c.points.iter().map(|p| p[1]).fold(f32::MAX, f32::min);
				let hi = c.points.iter().map(|p| p[1]).fold(f32::MIN, f32::max);
				let span = (hi - lo).max(1e-3);
				for &(kind, base) in &c.segments {
					let end = base + if kind == Kind::Bezier { 3 } else { 1 };
					let (start, finish) = (c.points[base], c.points[end]);
					if finish[0] <= start[0] {
						continue;
					}
					let at_start = c.value(start[0], m.exact_beziers);
					let want = if kind == Kind::InverseStepped { finish[1] } else { start[1] };
					assert!((at_start - want).abs() <= 1e-3 * span, "{path:?} {} at {}: {at_start} not {want}", c.id, start[0]);
					if matches!(kind, Kind::Linear | Kind::Bezier) {
						let near_end = c.value(finish[0] - 1e-4, m.exact_beziers);
						assert!((near_end - finish[1]).abs() <= 0.02 * span, "{path:?} {} near {}: {near_end} not {}", c.id, finish[0], finish[1]);
						// No jumps inside: 50 steps across the segment never move more than the
						// segment's whole rise and fall (its points' range) in one step.
						let pts = &c.points[base..=end];
						let local = pts.iter().map(|p| p[1]).fold(f32::MIN, f32::max) - pts.iter().map(|p| p[1]).fold(f32::MAX, f32::min);
						let mut previous = at_start;
						for i in 1..=50 {
							let t = start[0] + (finish[0] - start[0]) * i as f32 / 50.0 - 1e-5;
							let v = c.value(t, m.exact_beziers);
							assert!(v.is_finite());
							assert!((v - previous).abs() <= local * 0.25 + 1e-4, "{path:?} {} jumps at {t}: {previous} to {v}", c.id);
							previous = v;
						}
					}
					checked += 1;
				}
			}
		}
		assert!(files > 0, "no motion files in {dir}");
		eprintln!("checked {checked} segments in {files} motion files");
	}

	#[test]
	fn standard_parameters_belong_to_parts_of_the_body() {
		let channel = |id: &str| channel_by_name(id).map(|c| crate::motion::CHANNELS[c]);
		assert_eq!(channel("ParamAngleX"), Some("head"));
		assert_eq!(channel("ParamBodyAngleZ"), Some("torso"));
		assert_eq!(channel("ParamEyeBallY"), Some("eyes"));
		assert_eq!(channel("ParamBrowLForm"), Some("brows"));
		assert_eq!(channel("ParamEyeLSmile"), Some("expression"));
		assert_eq!(channel("ParamArmLA"), Some("arm_left"));
		assert_eq!(channel("ParamHandRB"), Some("arm_right"));
		assert_eq!(channel("ParamEyeROpen"), Some("eyelids"));
		assert_eq!(channel("ParamHairFront"), None, "hair is nobody's: it always shows the motion");
	}

	#[test]
	fn changes_are_added_by_their_share_and_kept_in_range() {
		let mut values = vec![("ParamAngleX".to_string(), Vec2::new(25.0, 0.0))];
		let changes = vec![("ParamAngleX".to_string(), 10.0), ("ParamBodyAngleX".to_string(), 4.0), ("Unknown".to_string(), 1.0)];
		let range = |id: &str| match id {
			"ParamAngleX" => Some((-30.0, 30.0, 0.0)),
			"ParamBodyAngleX" => Some((-10.0, 10.0, 0.0)),
			_ => None,
		};
		add_changes(&mut values, &changes, range, |id| if id == "ParamBodyAngleX" { 0.5 } else { 1.0 });
		let get = |n: &str| values.iter().find(|(k, _)| k == n).map(|(_, v)| v.x);
		assert_eq!(get("ParamAngleX"), Some(30.0), "kept inside the range");
		assert_eq!(get("ParamBodyAngleX"), Some(2.0), "added from rest, by its share");
		assert_eq!(get("Unknown"), None, "the model has no such parameter");
	}
}
