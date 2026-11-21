//! Procedural OpenGL ES 3.0 tactile feedback effects: touch ripples, floating hearts, sparkles,
//! soft fingertip glow while petting, and a subtle bottom-edge listening/speaking light.
//!
//! Everything is drawn with analytic signed-distance functions in one tiny shader (no textures,
//! negligible memory, crisp at any screen resolution). GL state is saved and restored cleanly so
//! Inox2D, Live2D and VRM renderers never see any change.

use std::f32::consts::TAU;

use glow::HasContext;

use crate::behaviour::State;

/// What kind of particle is drawn.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ParticleKind {
	Ripple = 0,
	Heart = 1,
	Sparkle = 2,
	#[allow(dead_code)]
	Glow = 3,
}

#[derive(Clone, Debug)]
pub struct Particle {
	pub kind: ParticleKind,
	/// Normalized screen coordinates (0..1, top-left origin).
	pub x: f32,
	pub y: f32,
	/// Velocity in normalized screen units per second.
	pub vx: f32,
	pub vy: f32,
	/// Radius as a fraction of the screen's shorter side.
	pub start_radius: f32,
	pub end_radius: f32,
	pub age: f32,
	pub life: f32,
	pub color: [f32; 4],
	pub rotation: f32,
	pub spin: f32,
	pub sway_phase: f32,
	pub sway_amp: f32,
}

impl Particle {
	fn progress(&self) -> f32 {
		(self.age / self.life.max(1e-4)).clamp(0.0, 1.0)
	}

	fn current_radius(&self) -> f32 {
		let p = self.progress();
		match self.kind {
			ParticleKind::Ripple => {
				let ease = 1.0 - (1.0 - p).powi(3);
				self.start_radius + (self.end_radius - self.start_radius) * ease
			}
			ParticleKind::Heart => {
				// Pop in smoothly, then hold size with gentle settle.
				let pop = if p < 0.18 {
					let u = p / 0.18;
					u * u * (3.0 - 2.0 * u) * 1.12
				} else {
					1.12 - 0.12 * ((p - 0.18) / 0.82)
				};
				self.end_radius * pop
			}
			ParticleKind::Sparkle => {
				let pop = if p < 0.22 {
					(p / 0.22).sqrt()
				} else {
					1.0 - 0.55 * ((p - 0.22) / 0.78)
				};
				self.end_radius * pop
			}
			ParticleKind::Glow => self.start_radius + (self.end_radius - self.start_radius) * p,
		}
	}

	fn current_alpha(&self) -> f32 {
		let p = self.progress();
		let env = match self.kind {
			ParticleKind::Ripple => (1.0 - p).powf(1.6),
			ParticleKind::Heart => {
				let fade_in = (p / 0.12).min(1.0);
				let fade_out = ((1.0 - p) / 0.35).min(1.0);
				fade_in * fade_out * fade_out
			}
			ParticleKind::Sparkle => {
				let fade_in = (p / 0.14).min(1.0);
				let fade_out = ((1.0 - p) / 0.45).min(1.0);
				fade_in * fade_out
			}
			ParticleKind::Glow => (1.0 - p) * (1.0 - p),
		};
		self.color[3] * env.clamp(0.0, 1.0)
	}
}

/// Pure-logic particle & ambient edge glow state (unit-tested without OpenGL).
pub struct FxState {
	particles: Vec<Particle>,
	enabled: bool,
	rng: u64,
	t: f32,
	/// Active finger glow (position, strength 0..1, warm pink when petting else soft indigo).
	finger_pos: Option<(f32, f32)>,
	finger_strength: f32,
	finger_warm: bool,
	/// Ambient bottom-edge listening/speaking glow intensity (smoothed).
	edge_alpha: f32,
	edge_color: [f32; 3],
	edge_energy: f32,
}

const MAX_PARTICLES: usize = 72;

impl FxState {
	pub fn new(seed: u64) -> Self {
		Self {
			particles: Vec::with_capacity(MAX_PARTICLES),
			enabled: true,
			rng: seed.max(1),
			t: 0.0,
			finger_pos: None,
			finger_strength: 0.0,
			finger_warm: false,
			edge_alpha: 0.0,
			edge_color: [0.42, 0.56, 1.0],
			edge_energy: 0.0,
		}
	}

	pub fn set_enabled(&mut self, enabled: bool) {
		self.enabled = enabled;
		if !enabled {
			self.particles.clear();
			self.finger_pos = None;
			self.finger_strength = 0.0;
		}
	}

	#[cfg(test)]
	pub fn count(&self) -> usize {
		self.particles.len()
	}

	fn rand(&mut self) -> f32 {
		self.rng ^= self.rng >> 12;
		self.rng ^= self.rng << 25;
		self.rng ^= self.rng >> 27;
		let v = self.rng.wrapping_mul(0x2545_F491_4F6C_DD1D);
		((v >> 40) as f32) / ((1u64 << 24) as f32)
	}

	fn between(&mut self, lo: f32, hi: f32) -> f32 {
		lo + self.rand() * (hi - lo)
	}

	fn push(&mut self, p: Particle) {
		if !self.enabled {
			return;
		}
		if self.particles.len() >= MAX_PARTICLES {
			self.particles.remove(0);
		}
		self.particles.push(p);
	}

	/// A crisp luminous tap ripple at normalized `(x, y)`.
	pub fn spawn_ripple(&mut self, x: f32, y: f32, color: [f32; 4]) {
		self.push(Particle {
			kind: ParticleKind::Ripple,
			x,
			y,
			vx: 0.0,
			vy: 0.0,
			start_radius: 0.014,
			end_radius: 0.092,
			age: 0.0,
			life: 0.46,
			color,
			rotation: 0.0,
			spin: 0.0,
			sway_phase: 0.0,
			sway_amp: 0.0,
		});
	}

	/// Floating rose-pink hearts + golden sparkles when petting or cheek-rubbing.
	pub fn spawn_hearts(&mut self, x: f32, y: f32, count: usize) {
		for i in 0..count {
			let ox = self.between(-0.045, 0.045);
			let oy = self.between(-0.02, 0.02);
			let rose = if i % 2 == 0 { [1.0, 0.49, 0.72, 0.92] } else { [1.0, 0.65, 0.80, 0.88] };
			let size = self.between(0.026, 0.042);
			let vx = self.between(-0.025, 0.025);
			let vy = -self.between(0.09, 0.16);
			let life = self.between(0.95, 1.35);
			let rotation = self.between(-0.22, 0.22);
			let spin = self.between(-0.25, 0.25);
			let sway_phase = self.between(0.0, TAU);
			let sway_amp = self.between(0.012, 0.028);
			self.push(Particle {
				kind: ParticleKind::Heart,
				x: (x + ox).clamp(0.05, 0.95),
				y: (y + oy).clamp(0.05, 0.95),
				vx,
				vy,
				start_radius: size * 0.4,
				end_radius: size,
				age: 0.0,
				life,
				color: rose,
				rotation,
				spin,
				sway_phase,
				sway_amp,
			});
		}
	}

	/// Crisp 4-point sparkles radiating gently from a touch point.
	pub fn spawn_sparkles(&mut self, x: f32, y: f32, count: usize, warm: bool) {
		for i in 0..count {
			let angle = self.between(0.0, TAU);
			let speed = self.between(0.04, 0.13);
			let color = if warm {
				if i % 2 == 0 { [1.0, 0.84, 0.42, 0.94] } else { [1.0, 0.68, 0.84, 0.9] }
			} else if i % 2 == 0 {
				[0.58, 0.76, 1.0, 0.92]
			} else {
				[0.75, 0.92, 1.0, 0.88]
			};
			let size = self.between(0.018, 0.032);
			let life = self.between(0.55, 0.85);
			let rotation = self.between(0.0, TAU);
			let spin = self.between(-2.4, 2.4);
			self.push(Particle {
				kind: ParticleKind::Sparkle,
				x: (x + angle.cos() * 0.015).clamp(0.02, 0.98),
				y: (y + angle.sin() * 0.015).clamp(0.02, 0.98),
				vx: angle.cos() * speed,
				vy: angle.sin() * speed - 0.04,
				start_radius: size * 0.4,
				end_radius: size,
				age: 0.0,
				life,
				color,
				rotation,
				spin,
				sway_phase: 0.0,
				sway_amp: 0.0,
			});
		}
	}

	/// Track an active fingertip for a subtle soft aura while touching/petting.
	pub fn set_finger(&mut self, pos: Option<(f32, f32)>, warm: bool) {
		if !self.enabled {
			self.finger_pos = None;
			return;
		}
		self.finger_pos = pos;
		self.finger_warm = warm;
	}

	/// Advance particle physics and ambient state glow by `dt` seconds.
	pub fn update(&mut self, dt: f32, state: State, energy: f32, ui_covering_bottom: bool) {
		let dt = dt.clamp(0.0, 0.1);
		self.t += dt;

		for p in &mut self.particles {
			p.age += dt;
			let sway = if p.sway_amp > 0.0 {
				(self.t * 4.2 + p.sway_phase).cos() * p.sway_amp
			} else {
				0.0
			};
			p.x += (p.vx + sway) * dt;
			p.y += p.vy * dt;
			// Gentle drag so bursts settle gracefully.
			let drag = (-dt * 1.8).exp();
			p.vx *= drag;
			if p.kind == ParticleKind::Sparkle {
				p.vy *= drag;
			}
			p.rotation += p.spin * dt;
		}
		self.particles.retain(|p| p.age < p.life);

		let target_finger = if self.finger_pos.is_some() && self.enabled { 1.0 } else { 0.0 };
		self.finger_strength += (target_finger - self.finger_strength) * (1.0 - (-dt / 0.12).exp());
		if self.finger_strength < 0.005 {
			self.finger_strength = 0.0;
		}

		// Subtle bottom-edge ambient light when listening, thinking or speaking (hidden when a drawer covers it).
		let (target_alpha, target_color) = if ui_covering_bottom {
			(0.0, self.edge_color)
		} else {
			match state {
				State::Idle => (0.0, self.edge_color),
				State::Listening => (0.58, [0.32, 0.78, 1.0]),
				State::Thinking => (0.42, [0.58, 0.62, 1.0]),
				State::Speaking => (0.52, [0.68, 0.56, 1.0]),
			}
		};
		let k = 1.0 - (-dt / 0.2).exp();
		self.edge_alpha += (target_alpha - self.edge_alpha) * k;
		for i in 0..3 {
			self.edge_color[i] += (target_color[i] - self.edge_color[i]) * k;
		}
		let pulse = 0.5 + 0.5 * (self.t * 3.1).sin();
		let want_energy = (0.35 + 0.65 * energy.clamp(0.0, 1.0) + 0.15 * pulse).clamp(0.0, 1.2);
		self.edge_energy += (want_energy - self.edge_energy) * (1.0 - (-dt / 0.08).exp());
	}

	#[cfg(test)]
	pub fn active(&self) -> bool {
		!self.particles.is_empty() || self.finger_strength > 0.005 || self.edge_alpha > 0.005
	}
}

const VERTEX: &str = r#"
in vec2 a_pos;
uniform vec2 u_screen;
uniform vec4 u_rect;
out vec2 v_local;
void main() {
	vec2 p = u_rect.xy + a_pos * u_rect.zw;
	v_local = a_pos * 2.0 - 1.0;
	gl_Position = vec4(p.x / u_screen.x * 2.0 - 1.0, 1.0 - p.y / u_screen.y * 2.0, 0.0, 1.0);
}
"#;

const FRAGMENT: &str = r#"
in vec2 v_local;
uniform int u_kind;
uniform vec4 u_color;
uniform float u_param;
uniform float u_rot;
out vec4 o_color;

float sd_heart(vec2 p) {
	p.x = abs(p.x);
	p.y = -p.y + 0.52;
	if (p.y + p.x > 1.0) {
		vec2 d = p - vec2(0.25, 0.75);
		return sqrt(dot(d, d)) - 0.35355339;
	}
	vec2 d1 = p - vec2(0.0, 1.0);
	vec2 d2 = p - 0.5 * max(p.x + p.y, 0.0);
	return sqrt(min(dot(d1, d1), dot(d2, d2))) * sign(p.x - p.y);
}

void main() {
	float c = cos(u_rot);
	float s = sin(u_rot);
	vec2 p = vec2(c * v_local.x - s * v_local.y, s * v_local.x + c * v_local.y);

	if (u_kind == 0) {
		// Luminous expanding ripple ring with delicate inner glow.
		float r = length(p);
		float thickness = mix(0.16, 0.06, u_param);
		float ring = 1.0 - smoothstep(thickness * 0.45, thickness, abs(r - 0.84));
		float wash = smoothstep(0.86, 0.0, r) * 0.14 * (1.0 - u_param);
		float a = (ring + wash) * u_color.a;
		o_color = vec4(u_color.rgb, clamp(a, 0.0, 1.0));
	} else if (u_kind == 1) {
		// Crisp analytic heart with soft rosy outer halo.
		float d = sd_heart(p * 1.18);
		float fill = 1.0 - smoothstep(-0.04, 0.05, d);
		float halo = (1.0 - smoothstep(0.0, 0.35, max(d, 0.0))) * 0.32;
		float a = (fill + halo) * u_color.a;
		vec3 col = mix(u_color.rgb, vec3(1.0, 0.92, 0.96), fill * 0.25);
		o_color = vec4(col, clamp(a, 0.0, 1.0));
	} else if (u_kind == 2) {
		// 4-point star sparkle.
		vec2 q = abs(p);
		float star = pow(q.x, 0.58) + pow(q.y, 0.58);
		float core = 1.0 - smoothstep(0.55, 0.82, star);
		float glow = (1.0 - smoothstep(0.0, 0.95, length(p))) * 0.4;
		float a = (core + glow) * u_color.a;
		vec3 col = mix(u_color.rgb, vec3(1.0), core * 0.65);
		o_color = vec4(col, clamp(a, 0.0, 1.0));
	} else if (u_kind == 3) {
		// Soft radial fingertip glow.
		float r = length(p);
		float g = pow(max(0.0, 1.0 - r), 2.2);
		o_color = vec4(u_color.rgb, g * u_color.a);
	} else {
		// Bottom-edge ambient voice/listening horizon glow.
		// v_local.x in [-1, 1], v_local.y in [-1, 1] (1 is bottom edge).
		float horiz = smoothstep(1.0, 0.12, abs(v_local.x));
		float vert = pow(clamp((v_local.y + 1.0) * 0.5, 0.0, 1.0), 2.6);
		float bar = smoothstep(0.84, 1.0, v_local.y) * smoothstep(0.75, 0.05, abs(v_local.x));
		float a = (horiz * vert * 0.42 + bar * 0.72) * u_color.a;
		vec3 col = mix(u_color.rgb, vec3(0.92, 0.97, 1.0), bar * 0.45);
		o_color = vec4(col, clamp(a, 0.0, 1.0));
	}
}
"#;

/// GL state saved before drawing effects and restored after.
struct Saved {
	program: Option<glow::Program>,
	vao: Option<glow::VertexArray>,
	array_buffer: Option<glow::Buffer>,
	framebuffer: Option<glow::Framebuffer>,
	viewport: [i32; 4],
	blend: bool,
	blend_func: [i32; 4],
	depth: bool,
	stencil: bool,
	scissor: bool,
	cull: bool,
}

impl Saved {
	unsafe fn take(gl: &glow::Context) -> Self {
		let mut viewport = [0; 4];
		gl.get_parameter_i32_slice(glow::VIEWPORT, &mut viewport);
		Self {
			program: gl.get_parameter_program(glow::CURRENT_PROGRAM),
			vao: gl.get_parameter_vertex_array(glow::VERTEX_ARRAY_BINDING),
			array_buffer: gl.get_parameter_buffer(glow::ARRAY_BUFFER_BINDING),
			framebuffer: gl.get_parameter_framebuffer(glow::DRAW_FRAMEBUFFER_BINDING),
			viewport,
			blend: gl.is_enabled(glow::BLEND),
			blend_func: [
				gl.get_parameter_i32(glow::BLEND_SRC_RGB),
				gl.get_parameter_i32(glow::BLEND_DST_RGB),
				gl.get_parameter_i32(glow::BLEND_SRC_ALPHA),
				gl.get_parameter_i32(glow::BLEND_DST_ALPHA),
			],
			depth: gl.is_enabled(glow::DEPTH_TEST),
			stencil: gl.is_enabled(glow::STENCIL_TEST),
			scissor: gl.is_enabled(glow::SCISSOR_TEST),
			cull: gl.is_enabled(glow::CULL_FACE),
		}
	}

	unsafe fn restore(&self, gl: &glow::Context) {
		let set = |cap: u32, on: bool| if on { gl.enable(cap) } else { gl.disable(cap) };
		set(glow::BLEND, self.blend);
		set(glow::DEPTH_TEST, self.depth);
		set(glow::STENCIL_TEST, self.stencil);
		set(glow::SCISSOR_TEST, self.scissor);
		set(glow::CULL_FACE, self.cull);
		let [a, b, c, d] = self.blend_func;
		gl.blend_func_separate(a as u32, b as u32, c as u32, d as u32);
		gl.viewport(self.viewport[0], self.viewport[1], self.viewport[2], self.viewport[3]);
		gl.bind_framebuffer(glow::DRAW_FRAMEBUFFER, self.framebuffer);
		gl.bind_buffer(glow::ARRAY_BUFFER, self.array_buffer);
		gl.bind_vertex_array(self.vao);
		gl.use_program(self.program);
	}
}

pub struct FxRenderer {
	program: glow::Program,
	vao: glow::VertexArray,
	_vbo: glow::Buffer,
	u_screen: Option<glow::UniformLocation>,
	u_rect: Option<glow::UniformLocation>,
	u_kind: Option<glow::UniformLocation>,
	u_color: Option<glow::UniformLocation>,
	u_param: Option<glow::UniformLocation>,
	u_rot: Option<glow::UniformLocation>,
}

impl FxRenderer {
	pub fn new(gl: &glow::Context) -> Result<Self, String> {
		unsafe {
			let program = crate::live2d::compile(gl, VERTEX, FRAGMENT)?;
			let vao = gl.create_vertex_array()?;
			let vbo = gl.create_buffer()?;
			let saved_vao = gl.get_parameter_vertex_array(glow::VERTEX_ARRAY_BINDING);
			let saved_buffer = gl.get_parameter_buffer(glow::ARRAY_BUFFER_BINDING);
			gl.bind_vertex_array(Some(vao));
			gl.bind_buffer(glow::ARRAY_BUFFER, Some(vbo));
			let quad: [f32; 8] = [0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 1.0, 1.0];
			let bytes: Vec<u8> = quad.iter().flat_map(|v| v.to_le_bytes()).collect();
			gl.buffer_data_u8_slice(glow::ARRAY_BUFFER, &bytes, glow::STATIC_DRAW);
			let at = gl.get_attrib_location(program, "a_pos").ok_or("the fx program has no a_pos")?;
			gl.enable_vertex_attrib_array(at);
			gl.vertex_attrib_pointer_f32(at, 2, glow::FLOAT, false, 8, 0);
			gl.bind_vertex_array(saved_vao);
			gl.bind_buffer(glow::ARRAY_BUFFER, saved_buffer);
			Ok(Self {
				u_screen: gl.get_uniform_location(program, "u_screen"),
				u_rect: gl.get_uniform_location(program, "u_rect"),
				u_kind: gl.get_uniform_location(program, "u_kind"),
				u_color: gl.get_uniform_location(program, "u_color"),
				u_param: gl.get_uniform_location(program, "u_param"),
				u_rot: gl.get_uniform_location(program, "u_rot"),
				program,
				vao,
				_vbo: vbo,
			})
		}
	}

	/// Draw character-layer effects (ambient bottom-edge glow, fingertip aura, floating hearts & sparkles)
	/// directly over the character and beneath UI sheets/overlays.
	pub fn draw_under_ui(&self, gl: &glow::Context, state: &FxState, width: u32, height: u32) {
		let has_particles = state.particles.iter().any(|p| p.kind != ParticleKind::Ripple);
		if !has_particles && state.finger_strength <= 0.005 && state.edge_alpha <= 0.005 {
			return;
		}
		let (sw, sh) = (width.max(1) as f32, height.max(1) as f32);
		let side = sw.min(sh);
		unsafe {
			let saved = Saved::take(gl);
			self.begin(gl, width, height, sw, sh);

			// Ambient bottom-edge listening/speaking glow.
			if state.edge_alpha > 0.005 {
				let h = (sh * 0.08 * (0.75 + 0.35 * state.edge_energy)).max(24.0);
				gl.uniform_1_i32(self.u_kind.as_ref(), 4);
				gl.uniform_4_f32(
					self.u_color.as_ref(),
					state.edge_color[0],
					state.edge_color[1],
					state.edge_color[2],
					state.edge_alpha * (0.65 + 0.35 * state.edge_energy).min(1.0),
				);
				gl.uniform_1_f32(self.u_param.as_ref(), state.edge_energy);
				gl.uniform_1_f32(self.u_rot.as_ref(), 0.0);
				gl.uniform_4_f32(self.u_rect.as_ref(), 0.0, sh - h, sw, h);
				gl.draw_arrays(glow::TRIANGLE_STRIP, 0, 4);
			}

			// Soft fingertip aura while actively petting or touching the character.
			if let Some((fx, fy)) = state.finger_pos {
				if state.finger_strength > 0.005 {
					let rad = side * 0.085;
					let col = if state.finger_warm { [1.0, 0.56, 0.78] } else { [0.52, 0.72, 1.0] };
					gl.uniform_1_i32(self.u_kind.as_ref(), 3);
					gl.uniform_4_f32(self.u_color.as_ref(), col[0], col[1], col[2], 0.32 * state.finger_strength);
					gl.uniform_1_f32(self.u_param.as_ref(), 0.0);
					gl.uniform_1_f32(self.u_rot.as_ref(), 0.0);
					gl.uniform_4_f32(self.u_rect.as_ref(), fx * sw - rad, fy * sh - rad, rad * 2.0, rad * 2.0);
					gl.draw_arrays(glow::TRIANGLE_STRIP, 0, 4);
				}
			}

			for p in &state.particles {
				if p.kind == ParticleKind::Ripple {
					continue;
				}
				self.draw_particle(gl, p, sw, sh, side);
			}

			saved.restore(gl);
		}
	}

	/// Draw crisp expanding tap ripples above UI panels for instant tactile feedback on every press.
	pub fn draw_over_ui(&self, gl: &glow::Context, state: &FxState, width: u32, height: u32) {
		if !state.particles.iter().any(|p| p.kind == ParticleKind::Ripple) {
			return;
		}
		let (sw, sh) = (width.max(1) as f32, height.max(1) as f32);
		let side = sw.min(sh);
		unsafe {
			let saved = Saved::take(gl);
			self.begin(gl, width, height, sw, sh);
			for p in &state.particles {
				if p.kind == ParticleKind::Ripple {
					self.draw_particle(gl, p, sw, sh, side);
				}
			}
			saved.restore(gl);
		}
	}

	unsafe fn begin(&self, gl: &glow::Context, width: u32, height: u32, sw: f32, sh: f32) {
		gl.bind_framebuffer(glow::DRAW_FRAMEBUFFER, None);
		gl.viewport(0, 0, width as i32, height as i32);
		gl.disable(glow::DEPTH_TEST);
		gl.disable(glow::STENCIL_TEST);
		gl.disable(glow::SCISSOR_TEST);
		gl.disable(glow::CULL_FACE);
		gl.enable(glow::BLEND);
		gl.blend_func_separate(glow::SRC_ALPHA, glow::ONE_MINUS_SRC_ALPHA, glow::ONE, glow::ONE_MINUS_SRC_ALPHA);
		gl.use_program(Some(self.program));
		gl.bind_vertex_array(Some(self.vao));
		gl.uniform_2_f32(self.u_screen.as_ref(), sw, sh);
	}

	unsafe fn draw_particle(&self, gl: &glow::Context, p: &Particle, sw: f32, sh: f32, side: f32) {
		let alpha = p.current_alpha();
		if alpha <= 0.004 {
			return;
		}
		let rad = p.current_radius() * side;
		let px = p.x * sw - rad;
		let py = p.y * sh - rad;
		gl.uniform_1_i32(self.u_kind.as_ref(), p.kind as i32);
		gl.uniform_4_f32(self.u_color.as_ref(), p.color[0], p.color[1], p.color[2], alpha);
		gl.uniform_1_f32(self.u_param.as_ref(), p.progress());
		gl.uniform_1_f32(self.u_rot.as_ref(), p.rotation);
		gl.uniform_4_f32(self.u_rect.as_ref(), px, py, rad * 2.0, rad * 2.0);
		gl.draw_arrays(glow::TRIANGLE_STRIP, 0, 4);
	}
}

#[cfg(test)]
mod tests {
	use super::*;

	#[test]
	fn ripples_hearts_and_sparkles_animate_and_expire_cleanly() {
		let mut fx = FxState::new(7);
		assert!(!fx.active());
		fx.spawn_ripple(0.5, 0.4, [0.6, 0.8, 1.0, 0.9]);
		fx.spawn_hearts(0.5, 0.25, 3);
		fx.spawn_sparkles(0.5, 0.35, 4, true);
		assert_eq!(fx.count(), 8);
		assert!(fx.active());
		let heart_y0 = fx.particles[1].y;
		for _ in 0..20 {
			fx.update(0.02, State::Idle, 0.0, false);
		}
		assert!(fx.particles.iter().any(|p| p.kind == ParticleKind::Heart && p.y < heart_y0), "hearts float upward");
		// After two seconds every burst particle expires cleanly.
		for _ in 0..100 {
			fx.update(0.02, State::Idle, 0.0, false);
		}
		assert_eq!(fx.count(), 0);
	}

	#[test]
	fn disabling_effects_clears_particles_and_ignores_new_spawns() {
		let mut fx = FxState::new(3);
		fx.spawn_hearts(0.5, 0.2, 4);
		assert_eq!(fx.count(), 4);
		fx.set_enabled(false);
		assert_eq!(fx.count(), 0);
		fx.spawn_ripple(0.5, 0.5, [1.0; 4]);
		fx.spawn_sparkles(0.5, 0.5, 3, false);
		assert_eq!(fx.count(), 0);
	}

	#[test]
	fn ambient_edge_glow_follows_conversation_state_and_yields_to_drawers() {
		let mut fx = FxState::new(1);
		for _ in 0..30 {
			fx.update(0.05, State::Listening, 0.7, false);
		}
		assert!(fx.edge_alpha > 0.45, "listening lights the bottom edge: {}", fx.edge_alpha);
		for _ in 0..30 {
			fx.update(0.05, State::Listening, 0.7, true);
		}
		assert!(fx.edge_alpha < 0.05, "a drawer hides the ambient edge glow: {}", fx.edge_alpha);
	}
}
