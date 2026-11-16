# Local changes to inox2d-opengl

Copied from https://github.com/Inochi2D/inox2d at commit
`d4dd9dd7f16b775042cbda44370570abf9a8cf81` (BSD-2-Clause, see `LICENSE`).

Changes made for this project, all so the renderer runs on the OpenGL ES 3.0
that low-cost ARM boards provide, not only on desktop OpenGL 3.3:

1. `src/shader.rs` — shaders are given the GLSL ES 3.00 header whenever the
   context is OpenGL ES, decided at run time. Upstream does this only when
   compiled for WebAssembly.
2. `src/texture.rs` — textures use `CLAMP_TO_EDGE` on OpenGL ES and WebGL,
   which have no `CLAMP_TO_BORDER`. In the browser this mode was being
   rejected, leaving the default repeat mode and stray fragments at part
   edges.
3. `src/texture.rs` — the off-screen emissive buffer is 8-bit on OpenGL ES,
   where rendering to float textures is an optional extension.
4. `src/lib.rs` — helper `is_gles`.
5. `Cargo.toml` — depends on the upstream `inox2d` crate by git revision.
