//! Saves the frame that was just drawn, for tests and previews.

use std::path::Path;

use glow::HasContext;

pub fn save_frame(gl: &glow::Context, width: u32, height: u32, path: &Path) -> Result<(), String> {
	let stride = width as usize * 4;
	let mut pixels = vec![0u8; stride * height as usize];
	unsafe {
		gl.pixel_store_i32(glow::PACK_ALIGNMENT, 1);
		gl.read_pixels(
			0,
			0,
			width as i32,
			height as i32,
			glow::RGBA,
			glow::UNSIGNED_BYTE,
			glow::PixelPackData::Slice(&mut pixels),
		);
	}
	// OpenGL rows run bottom to top; image files run top to bottom.
	let mut flipped = vec![0u8; pixels.len()];
	for y in 0..height as usize {
		let src = &pixels[y * stride..(y + 1) * stride];
		let dst = (height as usize - 1 - y) * stride;
		flipped[dst..dst + stride].copy_from_slice(src);
	}
	image::save_buffer(path, &flipped, width, height, image::ExtendedColorType::Rgba8)
		.map_err(|e| format!("cannot write {}: {e}", path.display()))
}
