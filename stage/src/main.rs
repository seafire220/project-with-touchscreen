//! The stage: draws and animates the character on the device screen.
//!
//! It loads a character (an Inochi2D puppet, or a Live2D-format model played
//! with Ayagami), keeps it alive with breathing, blinking and small movements,
//! and moves its mouth and changes its manner according to commands from the
//! core service. It holds no API keys and makes no network connections.

mod behaviour;
mod capture;
mod control;
mod live2d;
mod mapping;
mod motion;
mod overrides;
mod puppet_info;
mod smooth;
mod window;

use std::path::PathBuf;
use std::sync::mpsc::{channel, Receiver};
use std::time::Instant;

use glam::Vec2;
use glow::HasContext;
use inox2d::formats::inp::parse_inp;
use inox2d::model::Model;
use inox2d::render::InoxRendererExt;
use inox2d_opengl::OpenglRenderer;
use live2d::{Live2dPuppet, Live2dRenderer};
use serde_json::json;
use winit::window::{Fullscreen, WindowBuilder};

use behaviour::Behaviour;
use control::{Command, Events, Script};
use mapping::Mapper;
use motion::{Library, Motion};
use overrides::Overrides;
use puppet_info::PuppetInfo;
use window::{App, AppFrame, GlPreference};

const USAGE: &str = "\
Usage: stage CHARACTER [options]

  CHARACTER is an Inochi2D puppet (.inp or .inx) or a Live2D-format model
  (.model3.json, with the files it names beside it). The kind is decided by
  the file's contents, so a link with any name works.

  --size WxH            window size when not full screen (default 720x1280)
  --fullscreen          take the whole screen
  --gl auto|es|desktop  which OpenGL to ask for (default auto: ES first)
  --map FILE            JSON file overriding which parameters the controls drive
  --socket PATH         also accept commands and send events on this local socket
  --no-stdin            do not read commands from standard input
  --background RRGGBB   background colour (default 101014)
  --seed N              seed for blink timing (default 1)
  --still               no idle movement; only commanded mouth, blink and look
  --view X0,Y0,X1,Y1    show this box instead of the whole character (puppet units;
                        canvas pixels for Live2D-format models)

Testing:
  --script FILE         timed commands, one JSON object per line with \"at\"
  --fixed-dt SECONDS    advance time by a fixed step per frame
  --capture-dir DIR     where captured frames are written
  --capture-at T,T,...  times at which to save a frame
  --exit-after SECONDS  stop after this much stage time
  --no-physics          hair and clothes do not swing (Live2D-format models only)
";

struct Options {
	puppet: PathBuf,
	width: u32,
	height: u32,
	fullscreen: bool,
	gl: GlPreference,
	map: Option<PathBuf>,
	socket: Option<PathBuf>,
	stdin: bool,
	background: [f32; 3],
	seed: u64,
	still: bool,
	physics: bool,
	view: Option<[f32; 4]>,
	script: Option<PathBuf>,
	fixed_dt: Option<f32>,
	capture_dir: Option<PathBuf>,
	capture_at: Vec<f32>,
	exit_after: Option<f32>,
}

fn parse_options(args: &[String]) -> Result<Options, String> {
	let mut o = Options {
		puppet: PathBuf::new(),
		width: 720,
		height: 1280,
		fullscreen: false,
		gl: GlPreference::Auto,
		map: None,
		socket: None,
		stdin: true,
		background: [0x10 as f32 / 255.0, 0x10 as f32 / 255.0, 0x14 as f32 / 255.0],
		seed: 1,
		still: false,
		physics: true,
		view: None,
		script: None,
		fixed_dt: None,
		capture_dir: None,
		capture_at: Vec::new(),
		exit_after: None,
	};
	let mut puppet = None;
	let mut it = args.iter();
	while let Some(arg) = it.next() {
		let mut value = |name: &str| it.next().cloned().ok_or(format!("{name} needs a value"));
		match arg.as_str() {
			"--size" => {
				let v = value("--size")?;
				let (w, h) = v.split_once('x').ok_or("--size must look like 720x1280")?;
				o.width = w.parse().map_err(|_| "--size width is not a number")?;
				o.height = h.parse().map_err(|_| "--size height is not a number")?;
				if o.width == 0 || o.height == 0 {
					return Err("--size must be larger than zero".into());
				}
			}
			"--fullscreen" => o.fullscreen = true,
			"--gl" => {
				o.gl = match value("--gl")?.as_str() {
					"auto" => GlPreference::Auto,
					"es" => GlPreference::Es,
					"desktop" => GlPreference::Desktop,
					other => return Err(format!("--gl must be auto, es or desktop, not '{other}'")),
				}
			}
			"--map" => o.map = Some(value("--map")?.into()),
			"--socket" => o.socket = Some(value("--socket")?.into()),
			"--no-stdin" => o.stdin = false,
			"--background" => {
				let v = value("--background")?;
				let n = u32::from_str_radix(&v, 16).ok().filter(|_| v.len() == 6).ok_or("--background must be RRGGBB")?;
				o.background = [(n >> 16 & 255) as f32 / 255.0, (n >> 8 & 255) as f32 / 255.0, (n & 255) as f32 / 255.0];
			}
			"--seed" => o.seed = value("--seed")?.parse().map_err(|_| "--seed is not a number")?,
			"--still" => o.still = true,
			"--no-physics" => o.physics = false,
			"--view" => {
				let v: Vec<f32> = value("--view")?
					.split(',')
					.map(|t| t.trim().parse::<f32>())
					.collect::<Result<_, _>>()
					.map_err(|_| "--view must be four numbers: X0,Y0,X1,Y1")?;
				if v.len() != 4 || v[2] <= v[0] || v[3] <= v[1] {
					return Err("--view must be four numbers X0,Y0,X1,Y1 with X1 > X0 and Y1 > Y0".into());
				}
				o.view = Some([v[0], v[1], v[2], v[3]]);
			}
			"--script" => o.script = Some(value("--script")?.into()),
			"--fixed-dt" => {
				let dt: f32 = value("--fixed-dt")?.parse().map_err(|_| "--fixed-dt is not a number")?;
				if !(dt > 0.0 && dt <= 0.25) {
					return Err("--fixed-dt must be between 0 and 0.25".into());
				}
				o.fixed_dt = Some(dt);
			}
			"--capture-dir" => o.capture_dir = Some(value("--capture-dir")?.into()),
			"--capture-at" => {
				for part in value("--capture-at")?.split(',') {
					o.capture_at.push(part.trim().parse().map_err(|_| format!("--capture-at: '{part}' is not a number"))?);
				}
				o.capture_at.sort_by(|a, b| a.total_cmp(b));
			}
			"--exit-after" => o.exit_after = Some(value("--exit-after")?.parse().map_err(|_| "--exit-after is not a number")?),
			"-h" | "--help" => return Err(String::new()),
			other if other.starts_with("--") => return Err(format!("unknown option {other}")),
			other => {
				if puppet.replace(PathBuf::from(other)).is_some() {
					return Err("only one puppet file can be given".into());
				}
			}
		}
	}
	o.puppet = puppet.ok_or("no puppet file given")?;
	if !o.capture_at.is_empty() && o.capture_dir.is_none() {
		return Err("--capture-at needs --capture-dir".into());
	}
	Ok(o)
}

/// The character, in whichever format it came.
enum Puppet {
	Inox(Model),
	Live2d(Box<Live2dPuppet>),
}

impl Puppet {
	fn format(&self) -> &'static str {
		match self {
			Puppet::Inox(_) => "inochi2d",
			Puppet::Live2d(_) => "live2d",
		}
	}
}

enum Renderer {
	Inox(OpenglRenderer),
	Live2d(Box<Live2dRenderer>),
}

struct StageApp {
	opts: Options,
	puppet: Puppet,
	info: PuppetInfo,
	mapper: Mapper,
	behaviour: Behaviour,
	motion: Motion,
	overrides: Overrides,
	commands: Receiver<Command>,
	script: Option<Script>,
	events: Events,
	on_window: Option<(Renderer, glow::Context)>,
	width: u32,
	height: u32,
	t: f32,
	last: Instant,
	frames_since_beat: u32,
	last_beat: Instant,
	/// Seconds spent since the last heartbeat posing the character and issuing its drawing.
	update_time: f64,
	draw_time: f64,
	next_capture: usize,
	quit: bool,
}

impl StageApp {
	/// Scale and centre the puppet so all of it is visible.
	fn fit_camera(&mut self) {
		let Some((renderer, _)) = &mut self.on_window else {
			return;
		};
		let (w, h) = (self.width.max(1) as f32, self.height.max(1) as f32);
		let (scale, centre) = match self.opts.view.or(self.info.bounds) {
			Some([x0, y0, x1, y1]) if x1 > x0 && y1 > y0 => {
				(0.94 * (w / (x1 - x0)).min(h / (y1 - y0)), Vec2::new((x0 + x1) * 0.5, (y0 + y1) * 0.5))
			}
			_ => (0.15, Vec2::ZERO),
		};
		match renderer {
			Renderer::Inox(r) => {
				r.camera.scale = Vec2::splat(scale);
				r.camera.position = -centre;
			}
			Renderer::Live2d(r) => r.camera = live2d::Camera { centre, scale },
		}
	}

	fn handle(&mut self, command: Command) {
		match command {
			Command::Mouth(level) => self.behaviour.set_mouth(level),
			Command::State(state) => {
				if state != self.behaviour.state() {
					self.behaviour.set_state(state);
					self.events.emit(json!({"event": "state", "state": state.name()}));
				}
			}
			Command::Look(x, y) => self.behaviour.set_look(x, y),
			Command::Blink => self.behaviour.blink_now(),
			Command::Set(name, value, ease) => {
				if !self.overrides.set(&name, value, ease) {
					self.events.emit(json!({"event": "error", "message": format!("this puppet has no parameter '{name}'")}));
				}
			}
			Command::Unset(name, ease) => self.overrides.clear(&name, ease),
			Command::ClearAll(ease) => self.overrides.clear_all(ease),
			Command::Emotion(name, intensity) => match self.motion.set_emotion(&name, intensity) {
				Ok(started) => {
					self.events.emit(json!({"event": "emotion", "emotion": name, "intensity": intensity}));
					if let Some(g) = started {
						self.events.emit(json!({"event": "gesture", "name": g, "cause": "emotion"}));
					}
				}
				Err(e) => self.events.emit(json!({"event": "error", "message": e})),
			},
			Command::Gesture(name, intensity) => match self.motion.play(&name, intensity) {
				Ok(()) => self.events.emit(json!({"event": "gesture", "name": name, "cause": "command"})),
				Err(e) => self.events.emit(json!({"event": "error", "message": e})),
			},
			Command::RandomGestures(on) => self.motion.set_random(on),
			Command::Quit => self.quit = true,
		}
	}
}

impl App for StageApp {
	fn resume_window(&mut self, gl: glow::Context, aux: glow::Context) {
		let version = aux.version().clone();
		let [r, g, b] = self.opts.background;
		unsafe { aux.clear_color(r, g, b, 1.0) };
		let made = match &mut self.puppet {
			Puppet::Inox(model) => OpenglRenderer::new(gl, model).map(Renderer::Inox).map_err(|e| e.to_string()),
			Puppet::Live2d(puppet) => Live2dRenderer::new(gl, puppet).map(|mut r| {
				r.background = self.opts.background;
				Renderer::Live2d(Box::new(r))
			}),
		};
		match made {
			Ok(mut renderer) => {
				match &mut renderer {
					Renderer::Inox(r) => r.resize(self.opts.width, self.opts.height),
					Renderer::Live2d(r) => r.resize(self.opts.width, self.opts.height),
				}
				self.width = self.opts.width;
				self.height = self.opts.height;
				self.on_window = Some((renderer, aux));
				self.fit_camera();
				let controls: Vec<_> = self
					.mapper
					.targets()
					.iter()
					.map(|(c, t)| json!({"control": c.key(), "param": t.param, "axis": if t.axis == 0 { "x" } else { "y" }}))
					.collect();
				self.events.emit(json!({
					"event": "ready",
					"puppet": self.info.name,
					"format": self.puppet.format(),
					"parts": self.info.part_count,
					"params": self.info.params.len(),
					"param_names": self.info.params.iter().map(|p| p.name.clone()).collect::<Vec<_>>(),
					"controls": controls,
					"emotions": self.motion.emotions(),
					"gestures": self.motion.gestures(),
					"opengl": format!("{}{}.{}", if version.is_embedded { "ES " } else { "" }, version.major, version.minor),
				}));
				if let Puppet::Live2d(puppet) = &self.puppet {
					self.events.emit(json!({"event": "features", "live2d": puppet.features().to_json()}));
					for warning in &puppet.warnings {
						self.events.emit(json!({"event": "warning", "message": warning}));
					}
				}
			}
			Err(e) => {
				self.events.emit(json!({"event": "fatal", "message": format!("renderer could not start: {e}")}));
				self.quit = true;
			}
		}
		self.last = Instant::now();
		self.last_beat = self.last;
	}

	fn resize(&mut self, width: u32, height: u32) {
		self.width = width;
		self.height = height;
		match &mut self.on_window {
			Some((Renderer::Inox(r), _)) => r.resize(width, height),
			Some((Renderer::Live2d(r), _)) => r.resize(width, height),
			None => {}
		}
		self.fit_camera();
	}

	fn draw(&mut self) -> bool {
		if self.quit {
			return false;
		}
		let now = Instant::now();
		let dt = match self.opts.fixed_dt {
			Some(dt) => dt,
			None => now.duration_since(self.last).as_secs_f32().min(0.1),
		};
		self.last = now;
		self.t += dt;

		let mut pending: Vec<Command> = self.commands.try_iter().collect();
		if let Some(script) = &mut self.script {
			pending.extend(script.take_due(self.t));
		}
		for command in pending {
			self.handle(command);
		}

		let (energy, beats) = self.motion.style();
		self.behaviour.set_style(energy, beats);
		let mut pose = self.behaviour.update(dt);
		if let Some(g) = self.motion.apply(dt, &mut pose, self.behaviour.state(), !self.opts.still) {
			self.events.emit(json!({"event": "gesture", "name": g, "cause": "mood"}));
		}
		let mut values = self.mapper.resolve(&pose);
		self.overrides.apply(dt, &mut values);

		let Some((renderer, aux)) = &mut self.on_window else {
			return !self.quit;
		};
		let started = Instant::now();
		let posed: Instant;
		match (&mut self.puppet, renderer) {
			(Puppet::Inox(model), Renderer::Inox(renderer)) => {
				renderer.clear();
				let puppet = &mut model.puppet;
				puppet.begin_frame();
				if let Some(params) = puppet.param_ctx.as_mut() {
					for (name, value) in &values {
						let _ = params.set(name, *value);
					}
				}
				puppet.end_frame(dt);
				posed = Instant::now();
				renderer.on_begin_draw(puppet);
				renderer.draw(puppet);
				renderer.on_end_draw(puppet);
			}
			(Puppet::Live2d(puppet), Renderer::Live2d(renderer)) => {
				puppet.update(&values, dt);
				posed = Instant::now();
				if let Err(e) = renderer.draw(puppet) {
					self.events.emit(json!({"event": "fatal", "message": format!("drawing failed: {e}")}));
					return false;
				}
			}
			_ => unreachable!("the renderer is made for the puppet's format"),
		}
		self.update_time += posed.duration_since(started).as_secs_f64();
		self.draw_time += posed.elapsed().as_secs_f64();

		// Save frames that tests asked for, before the buffers are swapped.
		while self.next_capture < self.opts.capture_at.len() && self.t >= self.opts.capture_at[self.next_capture] {
			if let Some(dir) = &self.opts.capture_dir {
				let path = dir.join(format!("frame_{:03}.png", self.next_capture));
				match capture::save_frame(aux, self.width, self.height, &path) {
					Ok(()) => self.events.emit(json!({"event": "captured", "file": path, "t": self.t})),
					Err(e) => self.events.emit(json!({"event": "error", "message": e})),
				}
			}
			self.next_capture += 1;
		}

		self.frames_since_beat += 1;
		let since = now.duration_since(self.last_beat).as_secs_f32();
		if since >= 1.0 {
			let per_frame = |total: f64| (total * 1000.0 / self.frames_since_beat.max(1) as f64 * 100.0).round() / 100.0;
			self.events.emit(json!({
				"event": "heartbeat",
				"fps": (self.frames_since_beat as f64 / since as f64 * 10.0).round() / 10.0,
				"state": self.behaviour.state().name(),
				"mood": self.motion.mood(),
				// Average milliseconds per frame on the processor: moving the character, and
				// handing its drawing to the graphics chip (which then draws in parallel).
				"update_ms": per_frame(self.update_time),
				"draw_ms": per_frame(self.draw_time),
			}));
			self.frames_since_beat = 0;
			self.last_beat = now;
			self.update_time = 0.0;
			self.draw_time = 0.0;
		}

		if let Some(limit) = self.opts.exit_after {
			if self.t >= limit {
				return false;
			}
		}
		!self.quit
	}
}

fn run(opts: Options) -> Result<(), String> {
	let events = Events::default();
	let bytes = std::fs::read(&opts.puppet).map_err(|e| format!("cannot read {}: {e}", opts.puppet.display()))?;
	let (puppet, info) = if live2d::looks_like_model3(&bytes) {
		drop(bytes);
		let mut puppet = Live2dPuppet::load(&opts.puppet)?;
		if !opts.physics {
			puppet.drop_physics();
		}
		let info = puppet.info.clone();
		(Puppet::Live2d(Box::new(puppet)), info)
	} else {
		let info = puppet_info::read(&bytes)?;
		let unsupported = puppet_info::unsupported_node_types(&info);
		if !unsupported.is_empty() {
			return Err(format!(
				"this puppet uses features the renderer does not support yet: {}",
				unsupported.join(", ")
			));
		}
		let mut model = parse_inp(bytes.as_slice()).map_err(|e| format!("cannot load puppet: {e}"))?;
		model.puppet.init_transforms();
		model.puppet.init_rendering();
		model.puppet.init_params();
		model.puppet.init_physics();
		(Puppet::Inox(model), info)
	};
	let mapper = match &opts.map {
		Some(path) => {
			let text = std::fs::read_to_string(path).map_err(|e| format!("cannot read {}: {e}", path.display()))?;
			let spec = serde_json::from_str(&text).map_err(|e| format!("{}: {e}", path.display()))?;
			Mapper::with_overrides(&info, &spec)?
		}
		None => Mapper::auto(&info),
	};
	let script = match &opts.script {
		Some(path) => {
			let text = std::fs::read_to_string(path).map_err(|e| format!("cannot read {}: {e}", path.display()))?;
			Some(Script::parse(&text)?)
		}
		None => None,
	};
	if let Some(dir) = &opts.capture_dir {
		std::fs::create_dir_all(dir).map_err(|e| format!("cannot create {}: {e}", dir.display()))?;
	}

	let (tx, rx) = channel();
	if opts.stdin {
		control::spawn_stdin(tx.clone(), events.clone());
	}
	if let Some(path) = &opts.socket {
		control::spawn_socket(path, tx.clone(), events.clone())?;
	}

	let mut builder = WindowBuilder::new()
		.with_title("Character stage")
		.with_resizable(true)
		.with_inner_size(winit::dpi::PhysicalSize::new(opts.width, opts.height));
	if opts.fullscreen {
		builder = builder.with_fullscreen(Some(Fullscreen::Borderless(None)));
	}
	let frame = AppFrame::init(builder, opts.gl).map_err(|e| format!("cannot open a window: {e}"))?;
	let mut behaviour = Behaviour::new(opts.seed);
	behaviour.set_idle_motion(!opts.still);
	let motion = Motion::new(Library::builtin(), |key| mapper.drives(key), opts.seed);
	let app = StageApp {
		overrides: Overrides::new(&info.params),
		behaviour,
		motion,
		opts,
		puppet,
		info,
		mapper,
		commands: rx,
		script,
		events,
		on_window: None,
		width: 0,
		height: 0,
		t: 0.0,
		last: Instant::now(),
		frames_since_beat: 0,
		last_beat: Instant::now(),
		update_time: 0.0,
		draw_time: 0.0,
		next_capture: 0,
		quit: false,
	};
	frame.run(app).map_err(|e| format!("stage stopped: {e}"))
}

fn main() {
	let args: Vec<String> = std::env::args().skip(1).collect();
	let opts = match parse_options(&args) {
		Ok(o) => o,
		Err(e) => {
			if !e.is_empty() {
				eprintln!("stage: {e}\n");
			}
			eprint!("{USAGE}");
			std::process::exit(if e.is_empty() { 0 } else { 2 });
		}
	};
	if let Err(e) = run(opts) {
		println!("{}", json!({"event": "fatal", "message": e}));
		eprintln!("stage: {e}");
		std::process::exit(1);
	}
}

#[cfg(test)]
mod tests {
	use super::*;

	fn args(list: &[&str]) -> Vec<String> {
		list.iter().map(|s| s.to_string()).collect()
	}

	#[test]
	fn parses_typical_options() {
		let o = parse_options(&args(&[
			"aka.inp", "--size", "600x800", "--gl", "es", "--background", "ff8000", "--capture-dir", "out",
			"--capture-at", "2, 1,3", "--fixed-dt", "0.02", "--exit-after", "4", "--no-stdin",
		]))
		.unwrap();
		assert_eq!((o.width, o.height), (600, 800));
		assert_eq!(o.gl, GlPreference::Es);
		assert_eq!(o.background, [1.0, 128.0 / 255.0, 0.0]);
		assert_eq!(o.capture_at, vec![1.0, 2.0, 3.0]);
		assert_eq!(o.fixed_dt, Some(0.02));
		assert!(!o.stdin);
	}

	#[test]
	fn rejects_bad_options() {
		for bad in [
			vec![],
			vec!["a.inp", "b.inp"],
			vec!["a.inp", "--size", "600"],
			vec!["a.inp", "--size", "0x10"],
			vec!["a.inp", "--gl", "vulkan"],
			vec!["a.inp", "--background", "red"],
			vec!["a.inp", "--fixed-dt", "5"],
			vec!["a.inp", "--capture-at", "1"],
			vec!["a.inp", "--bogus"],
			vec!["a.inp", "--seed"],
			vec!["a.inp", "--view", "1,2,3"],
			vec!["a.inp", "--view", "5,0,1,1"],
		] {
			assert!(parse_options(&args(&bad)).is_err(), "{bad:?}");
		}
	}
}
