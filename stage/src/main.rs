//! The stage: draws and animates the character on the device screen.
//!
//! It loads an Inochi2D puppet, keeps it alive with breathing, blinking and
//! small movements, and moves its mouth and changes its manner according to
//! commands from the core service. It holds no API keys and makes no network
//! connections.

mod behaviour;
mod capture;
mod control;
mod mapping;
mod puppet_info;
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
use serde_json::json;
use winit::window::{Fullscreen, WindowBuilder};

use behaviour::Behaviour;
use control::{Command, Events, Script};
use mapping::Mapper;
use puppet_info::PuppetInfo;
use window::{App, AppFrame, GlPreference};

const USAGE: &str = "\
Usage: stage PUPPET.inp [options]

  --size WxH            window size when not full screen (default 720x1280)
  --fullscreen          take the whole screen
  --gl auto|es|desktop  which OpenGL to ask for (default auto: ES first)
  --map FILE            JSON file overriding which parameters the controls drive
  --socket PATH         also accept commands and send events on this local socket
  --no-stdin            do not read commands from standard input
  --background RRGGBB   background colour (default 101014)
  --seed N              seed for blink timing (default 1)
  --still               no idle movement; only commanded mouth, blink and look

Testing:
  --script FILE         timed commands, one JSON object per line with \"at\"
  --fixed-dt SECONDS    advance time by a fixed step per frame
  --capture-dir DIR     where captured frames are written
  --capture-at T,T,...  times at which to save a frame
  --exit-after SECONDS  stop after this much stage time
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

struct StageApp {
	opts: Options,
	model: Model,
	info: PuppetInfo,
	mapper: Mapper,
	behaviour: Behaviour,
	commands: Receiver<Command>,
	script: Option<Script>,
	events: Events,
	on_window: Option<(OpenglRenderer, glow::Context)>,
	width: u32,
	height: u32,
	t: f32,
	last: Instant,
	frames_since_beat: u32,
	last_beat: Instant,
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
		match self.info.bounds {
			Some([x0, y0, x1, y1]) if x1 > x0 && y1 > y0 => {
				let scale = 0.94 * (w / (x1 - x0)).min(h / (y1 - y0));
				renderer.camera.scale = Vec2::splat(scale);
				renderer.camera.position = Vec2::new(-(x0 + x1) * 0.5, -(y0 + y1) * 0.5);
			}
			_ => renderer.camera.scale = Vec2::splat(0.15),
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
			Command::Quit => self.quit = true,
		}
	}
}

impl App for StageApp {
	fn resume_window(&mut self, gl: glow::Context, aux: glow::Context) {
		let version = aux.version().clone();
		let [r, g, b] = self.opts.background;
		unsafe { aux.clear_color(r, g, b, 1.0) };
		match OpenglRenderer::new(gl, &self.model) {
			Ok(mut renderer) => {
				renderer.resize(self.opts.width, self.opts.height);
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
					"parts": self.info.part_count,
					"params": self.info.params.len(),
					"controls": controls,
					"opengl": format!("{}{}.{}", if version.is_embedded { "ES " } else { "" }, version.major, version.minor),
				}));
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
		if let Some((renderer, _)) = &mut self.on_window {
			renderer.resize(width, height);
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

		let pose = self.behaviour.update(dt);
		let values = self.mapper.resolve(&pose);

		let Some((renderer, aux)) = &mut self.on_window else {
			return !self.quit;
		};
		renderer.clear();
		let puppet = &mut self.model.puppet;
		puppet.begin_frame();
		if let Some(params) = puppet.param_ctx.as_mut() {
			for (name, value) in &values {
				let _ = params.set(name, *value);
			}
		}
		puppet.end_frame(dt);
		renderer.on_begin_draw(puppet);
		renderer.draw(puppet);
		renderer.on_end_draw(puppet);

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
			self.events.emit(json!({
				"event": "heartbeat",
				"fps": (self.frames_since_beat as f64 / since as f64 * 10.0).round() / 10.0,
				"state": self.behaviour.state().name(),
			}));
			self.frames_since_beat = 0;
			self.last_beat = now;
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
	let info = puppet_info::read(&bytes)?;
	let unsupported = puppet_info::unsupported_node_types(&info);
	if !unsupported.is_empty() {
		return Err(format!(
			"this puppet uses features the renderer does not support yet: {}",
			unsupported.join(", ")
		));
	}
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

	let mut model = parse_inp(bytes.as_slice()).map_err(|e| format!("cannot load puppet: {e}"))?;
	model.puppet.init_transforms();
	model.puppet.init_rendering();
	model.puppet.init_params();
	model.puppet.init_physics();

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
	let app = StageApp {
		behaviour,
		opts,
		model,
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
		] {
			assert!(parse_options(&args(&bad)).is_err(), "{bad:?}");
		}
	}
}
