"""A small made-up VRM avatar for tests: the bones VRM requires, a triangle, a texture (large, so
it gets scaled down), a thumbnail, and a few expressions. No third-party model is needed."""
import io
import json
import struct

BONES = ["hips", "spine", "head", "leftUpperArm", "leftLowerArm", "leftHand", "rightUpperArm", "rightLowerArm",
         "rightHand", "leftUpperLeg", "leftLowerLeg", "leftFoot", "rightUpperLeg", "rightLowerLeg", "rightFoot"]


def png(width, height, colour=(200, 120, 160, 255)):
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGBA", (width, height), colour).save(out, "PNG")
    return out.getvalue()


def glb(doc, binary):
    text = json.dumps(doc).encode("utf-8")
    text += b" " * (-len(text) % 4)
    binary += b"\x00" * (-len(binary) % 4)
    total = 12 + 8 + len(text) + 8 + len(binary)
    return (struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<I4s", len(text), b"JSON") + text
            + struct.pack("<I4s", len(binary), b"BIN\x00") + binary)


def sample_vrm(version=1, texture_side=2048, meta=None, drop_bone=None, external=False):
    binary = bytearray()
    views = []

    def add(data):
        while len(binary) % 4:
            binary.append(0)
        views.append({"buffer": 0, "byteOffset": len(binary), "byteLength": len(data)})
        binary.extend(data)
        return len(views) - 1

    positions = struct.pack("<9f", 0, 1.5, 0.1, 0.05, 1.55, 0.1, -0.05, 1.55, 0.1)
    pos_view = add(positions)
    texture_view = add(png(texture_side, texture_side))
    thumb_view = add(png(64, 64, (10, 200, 10, 255)))
    nodes = [{"name": b, "translation": [0, 0.1 * i, 0]} for i, b in enumerate(BONES)]
    nodes.append({"name": "Body", "mesh": 0})
    nodes[0]["children"] = list(range(1, len(BONES))) + [len(BONES)]
    doc = {
        "asset": {"version": "2.0"},
        "scenes": [{"nodes": [0]}],
        "nodes": nodes,
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "material": 0}]}],
        "accessors": [{"bufferView": pos_view, "componentType": 5126, "count": 3, "type": "VEC3"}],
        "materials": [{"name": "Skin", "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}],
        "textures": [{"source": 0}, {"source": 1}],
        "images": [{"bufferView": texture_view, "mimeType": "image/png"},
                   {"bufferView": thumb_view, "mimeType": "image/png"}],
        "bufferViews": views,
        "buffers": [{"byteLength": 0}],
    }
    if external:
        doc["buffers"][0]["uri"] = "model.bin"
    bones = [b for b in BONES if b != drop_bone]
    if version == 1:
        doc["extensions"] = {"VRMC_vrm": {
            "specVersion": "1.0",
            "meta": dict({"name": "Sample", "authors": ["Test Maker"], "licenseUrl": "https://vrm.dev/licenses/1.0/",
                          "avatarPermission": "everyone", "commercialUsage": "personalNonProfit",
                          "thumbnailImage": 1}, **(meta or {})),
            "humanoid": {"humanBones": {b: {"node": BONES.index(b)} for b in bones}},
            "expressions": {"preset": {"happy": {}, "sad": {}, "aa": {}, "blink": {}},
                            "custom": {"Blush": {}, "Hmm": {}}},
        }}
    else:
        doc["extensions"] = {"VRM": {
            "meta": dict({"title": "Sample", "author": "Test Maker", "allowedUserName": "Everyone",
                          "commercialUssageName": "Disallow", "licenseName": "Other", "texture": 1}, **(meta or {})),
            "humanoid": {"humanBones": [{"bone": b, "node": BONES.index(b)} for b in bones]},
            "blendShapeMaster": {"blendShapeGroups": [
                {"name": "Joy", "presetName": "joy"}, {"name": "A", "presetName": "a"},
                {"name": "Blink", "presetName": "blink"}, {"name": "Blush", "presetName": "unknown"}]},
        }}
    doc["buffers"][0]["byteLength"] = len(binary)
    return glb(doc, bytes(binary))
