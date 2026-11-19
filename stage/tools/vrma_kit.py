"""A small kit for writing VRM Animation clips (.vrma) by hand: the built-in full-body animations for
3D avatars (stage/motions/vrma, made by vrma_library.py) are written with it.

A clip is a function of time that returns a pose; the kit samples it at 30 frames a second and writes
a glTF binary file with the VRMC_vrm_animation extension, which the stage (stage/src/vrm/anim.rs), and
any other VRM Animation player, plays on any VRM avatar.

Poses are written on a reference skeleton in VRM's T-pose whose bones have no turn of their own at
rest, so each bone's rotation is its *normalised* rotation (rig.rs): x towards the avatar's left, y
up, z towards the viewer. Rather than giving every bone's turn, a pose is described the way an
animator thinks of it:

    Pose(hips=(x, y, z) metres moved, pelvis=(turn, bend, side) degrees,
         torso=(turn, bend, side), head=(turn, down, tilt),
         shoulders=((up, forward), (up, forward)),           avatar's left then right
         hands=(Hand(...), Hand(...)), fingers=((thumb, index, middle, ring, little), (...)),
         feet=((x, z, turn, toes up), (x, z, turn, toes up)))

Angles are in degrees. A turn is towards the avatar's left (the viewer's right), a bend is forward,
a side lean is towards the avatar's left; the head's "down" looks down and its tilt leans its top
towards the avatar's left. A hand is placed where it should be (inverse kinematics: the elbow finds
its own place, bending towards its "pole"), relative to the chest, the hips or the world, with the
palm facing a given way; the feet stay planted where they are put (the knees bend as the hips move).
"""
import json
import math
import struct

RATE = 30.0

# ---------------------------------------------------------------- quaternions (x, y, z, w)


def qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw,
            aw * bw - ax * bx - ay * by - az * bz)


def qinv(q):
    return (-q[0], -q[1], -q[2], q[3])


def qnorm(q):
    n = math.sqrt(sum(c * c for c in q)) or 1.0
    q = tuple(c / n for c in q)
    return q if q[3] >= 0 else tuple(-c for c in q)


def qaxis(axis, degrees):
    x, y, z = vnorm(axis)
    h = math.radians(degrees) / 2
    s = math.sin(h)
    return (x * s, y * s, z * s, math.cos(h))


def rx(d):
    return qaxis((1, 0, 0), d)


def ry(d):
    return qaxis((0, 1, 0), d)


def rz(d):
    return qaxis((0, 0, 1), d)


def qrot(q, v):
    p = qmul(qmul(q, (v[0], v[1], v[2], 0.0)), qinv(q))
    return (p[0], p[1], p[2])


def qslerp(a, b, t):
    d = sum(x * y for x, y in zip(a, b))
    if d < 0:
        b, d = tuple(-c for c in b), -d
    if d > 0.9995:
        return qnorm(tuple(x + (y - x) * t for x, y in zip(a, b)))
    th = math.acos(d)
    s = math.sin(th)
    wa, wb = math.sin((1 - t) * th) / s, math.sin(t * th) / s
    return qnorm(tuple(wa * x + wb * y for x, y in zip(a, b)))


def qangle(a, b=(0, 0, 0, 1)):
    d = abs(sum(x * y for x, y in zip(a, b)))
    return math.degrees(2 * math.acos(min(1.0, d)))


def qframe(x_axis, y_axis):
    """The rotation taking the world's x and y axes to these (orthonormalised)."""
    x = vnorm(x_axis)
    y = vnorm(vsub(y_axis, vscale(x, vdot(x, y_axis))))
    z = vcross(x, y)
    m = ((x[0], y[0], z[0]), (x[1], y[1], z[1]), (x[2], y[2], z[2]))
    tr = m[0][0] + m[1][1] + m[2][2]
    if tr > 0:
        s = math.sqrt(tr + 1.0) * 2
        q = ((m[2][1] - m[1][2]) / s, (m[0][2] - m[2][0]) / s, (m[1][0] - m[0][1]) / s, 0.25 * s)
    elif m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2
        q = (0.25 * s, (m[0][1] + m[1][0]) / s, (m[0][2] + m[2][0]) / s, (m[2][1] - m[1][2]) / s)
    elif m[1][1] > m[2][2]:
        s = math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2
        q = ((m[0][1] + m[1][0]) / s, 0.25 * s, (m[1][2] + m[2][1]) / s, (m[0][2] - m[2][0]) / s)
    else:
        s = math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2
        q = ((m[0][2] + m[2][0]) / s, (m[1][2] + m[2][1]) / s, 0.25 * s, (m[1][0] - m[0][1]) / s)
    return qnorm(q)


def turn(turn=0.0, bend=0.0, side=0.0):
    """Turn towards the avatar's left, bend forward, lean towards its left (degrees)."""
    return qnorm(qmul(qmul(ry(turn), rx(bend)), rz(-side)))


# ---------------------------------------------------------------- vectors


def vadd(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def vsub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def vscale(a, s):
    return (a[0] * s, a[1] * s, a[2] * s)


def vdot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def vcross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def vlen(a):
    return math.sqrt(vdot(a, a))


def vnorm(a):
    n = vlen(a) or 1.0
    return (a[0] / n, a[1] / n, a[2] / n)


def vlerp(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


# ---------------------------------------------------------------- the reference skeleton

# (bone, parent, position in the T-pose, metres). A girl about 1.55 m tall, as most VRoid avatars are;
# what matters for other avatars is only the turns, and the hips' movement in hips heights.
SKELETON = [
    ("hips", None, (0.0, 0.880, 0.0)),
    ("spine", "hips", (0.0, 0.940, 0.0)),
    ("chest", "spine", (0.0, 1.040, 0.0)),
    ("upperChest", "chest", (0.0, 1.140, 0.0)),
    ("neck", "upperChest", (0.0, 1.270, -0.010)),
    ("head", "neck", (0.0, 1.340, 0.0)),
    ("jaw", "head", (0.0, 1.370, 0.020)),
    ("leftEye", "head", (0.030, 1.400, 0.070)),
    ("rightEye", "head", (-0.030, 1.400, 0.070)),
    ("leftUpperLeg", "hips", (0.075, 0.830, 0.0)),
    ("leftLowerLeg", "leftUpperLeg", (0.075, 0.450, 0.0)),
    ("leftFoot", "leftLowerLeg", (0.075, 0.065, 0.0)),
    ("leftToes", "leftFoot", (0.075, 0.015, 0.120)),
]
for _side, _s in (("left", 1), ("right", -1)):
    if _side == "right":
        SKELETON += [("rightUpperLeg", "hips", (-0.075, 0.830, 0.0)),
                     ("rightLowerLeg", "rightUpperLeg", (-0.075, 0.450, 0.0)),
                     ("rightFoot", "rightLowerLeg", (-0.075, 0.065, 0.0)),
                     ("rightToes", "rightFoot", (-0.075, 0.015, 0.120))]
    SKELETON += [
        (_side + "Shoulder", "upperChest", (_s * 0.020, 1.240, -0.010)),
        (_side + "UpperArm", _side + "Shoulder", (_s * 0.105, 1.240, -0.010)),
        (_side + "LowerArm", _side + "UpperArm", (_s * 0.335, 1.240, -0.010)),
        (_side + "Hand", _side + "LowerArm", (_s * 0.555, 1.240, -0.010)),
        (_side + "ThumbMetacarpal", _side + "Hand", (_s * 0.570, 1.232, 0.012)),
        (_side + "ThumbProximal", _side + "ThumbMetacarpal", (_s * 0.598, 1.226, 0.034)),
        (_side + "ThumbDistal", _side + "ThumbProximal", (_s * 0.622, 1.222, 0.050)),
    ]
    for _finger, _z, _lengths in (("Index", 0.022, (0.085, 0.040, 0.025)), ("Middle", 0.004, (0.088, 0.045, 0.028)),
                                  ("Ring", -0.014, (0.085, 0.040, 0.025)), ("Little", -0.030, (0.078, 0.032, 0.020))):
        _x = 0.555
        _parent = _side + "Hand"
        for _joint, _step in zip(("Proximal", "Intermediate", "Distal"), _lengths):
            _x += _step
            SKELETON.append((_side + _finger + _joint, _parent, (_s * _x, 1.240, _z - 0.010)))
            _parent = _side + _finger + _joint

REST = {name: pos for name, _, pos in SKELETON}
PARENT = {name: parent for name, parent, _ in SKELETON}
ORDER = [name for name, _, _ in SKELETON]
UPPER_ARM = 0.230
LOWER_ARM = 0.220
UPPER_LEG = 0.380
LOWER_LEG = 0.385
ANKLE = REST["leftFoot"][1]
HIPS_HEIGHT = REST["hips"][1] - ANKLE
SIDES = (("left", 1.0), ("right", -1.0))
FINGERS = ("Thumb", "Index", "Middle", "Ring", "Little")


def forward(rot, hips_offset=(0, 0, 0)):
    """World turns and positions of every bone for normalised rotations `rot` (bone -> quaternion)."""
    world_rot, world_pos = {}, {}
    for name in ORDER:
        parent = PARENT[name]
        q = rot.get(name, (0, 0, 0, 1))
        if parent is None:
            world_rot[name] = q
            world_pos[name] = vadd(REST[name], hips_offset)
        else:
            world_rot[name] = qmul(world_rot[parent], q)
            world_pos[name] = vadd(world_pos[parent], qrot(world_rot[parent], vsub(REST[name], REST[parent])))
    return world_rot, world_pos


# ---------------------------------------------------------------- posing


class Hand:
    """Where a hand goes: `at` (metres) in a frame, the way the elbow points (`pole`, same frame), the
    way the palm faces (`palm`, or None for the forearm's own way), and the wrist bent towards the palm
    (`flex`) and towards the thumb (`tilt`), in degrees. Frames:

      'hang'   from the shoulder joint, along the world's axes: an arm hanging stays hanging whatever
               the body does
      'chest'  from the upper chest, turning with it
      'hips'   from the hips, turning with them
      'world'  from the ground at the feet
    """

    def __init__(self, at, frame="hang", pole=None, palm=None, flex=0.0, tilt=0.0):
        self.at, self.frame, self.pole, self.palm, self.flex, self.tilt = tuple(at), frame, pole, palm, flex, tilt

    def lerp(self, other, t):
        if isinstance(other, Hand) and other.frame == self.frame:
            pole = vlerp(self.pole, other.pole, t) if self.pole and other.pole else (other.pole if t > 0.5 else self.pole)
            if self.palm and other.palm:
                palm = vnorm(vlerp(self.palm, other.palm, t))
            else:
                palm = other.palm if t > 0.5 else self.palm
            return Hand(vlerp(self.at, other.at, t), self.frame, pole, palm,
                        self.flex + (other.flex - self.flex) * t, self.tilt + (other.tilt - self.tilt) * t)
        return HandMix(self, other, t)

    def moved(self, by):
        return Hand(vadd(self.at, by), self.frame, self.pole, self.palm, self.flex, self.tilt)

    def resolve(self, s, world_rot, world_pos):
        """(target, pole, palm or None, flex, tilt) in the world."""
        pole = self.pole or (s * 0.35, -0.2, -1.0)
        return (_in_world(self.frame, self.at, s, world_rot, world_pos), _in_world(self.frame, pole, s, world_rot, world_pos, True),
                _in_world(self.frame, self.palm, s, world_rot, world_pos, True) if self.palm else None, self.flex, self.tilt)


class HandMix:
    """Part way from one hand's place to another's, when they are in different frames."""

    def __init__(self, a, b, t):
        self.a, self.b, self.t = a, b, t

    def lerp(self, other, t):
        return HandMix(self, other, t)

    def moved(self, by):
        return HandMix(self.a.moved(by), self.b.moved(by), self.t)

    def resolve(self, s, world_rot, world_pos):
        ta, pa, na, fa, ia = self.a.resolve(s, world_rot, world_pos)
        tb, pb, nb, fb, ib = self.b.resolve(s, world_rot, world_pos)
        t = self.t
        palm = vnorm(vlerp(na, nb, t)) if na and nb else (nb if t > 0.5 else na)
        return vlerp(ta, tb, t), vlerp(pa, pb, t), palm, fa + (fb - fa) * t, ia + (ib - ia) * t


def _in_world(frame, v, s, world_rot, world_pos, direction=False):
    """A point (or a direction) given in a frame, in the world."""
    if frame == "world":
        return tuple(v)
    if frame == "hang":
        return tuple(v) if direction else vadd(world_pos[("left" if s > 0 else "right") + "UpperArm"], v)
    bone = {"chest": "upperChest", "hips": "hips"}[frame]
    r = qrot(world_rot[bone], v)
    return r if direction else vadd(world_pos[bone], r)


def relaxed_hand(s, out=0.0, forward=0.0, up=0.0):
    """A hand hanging at the side, the elbow a little bent, the palm towards the leg."""
    return Hand((s * (0.095 + out), -0.425 + up, 0.035 + forward), "hang", pole=(s * 0.35, -0.2, -1.0), flex=6.0)


RELAXED_FINGERS = (0.25, 0.22, 0.28, 0.34, 0.40)
OPEN_FINGERS = (0.05, 0.03, 0.03, 0.04, 0.06)
LOOSE_FIST = (0.40, 0.55, 0.62, 0.68, 0.72)
FIST = (0.60, 0.90, 0.95, 0.95, 0.95)


class Pose:
    """A whole-body pose, as an animator describes it (see the module's description). `knees` turns
    each knee outwards (degrees)."""

    FIELDS = ("hips", "pelvis", "torso", "head", "shoulders", "hands", "fingers", "spread", "feet", "knees")

    def __init__(self, hips=(0.0, -0.012, 0.0), pelvis=(0.0, 0.0, 0.0), torso=(0.0, 0.0, 0.0), head=(0.0, 0.0, 0.0),
                 shoulders=((0.0, 0.0), (0.0, 0.0)), hands=None, fingers=(RELAXED_FINGERS, RELAXED_FINGERS),
                 spread=(0.0, 0.0), feet=((0.085, 0.0, 8.0, 0.0), (-0.085, 0.0, -8.0, 0.0)), knees=(0.0, 0.0)):
        self.hips, self.pelvis, self.torso, self.head = tuple(hips), tuple(pelvis), tuple(torso), tuple(head)
        self.shoulders = tuple(tuple(s) for s in shoulders)
        self.hands = tuple(hands or (relaxed_hand(1.0), relaxed_hand(-1.0)))
        self.fingers = tuple(tuple(f) for f in fingers)
        self.spread = tuple(spread)
        self.feet = tuple(tuple(f) for f in feet)
        self.knees = tuple(knees)

    def but(self, **changes):
        """This pose with some parts changed."""
        values = {k: getattr(self, k) for k in self.FIELDS}
        values.update(changes)
        return Pose(**values)

    def lerp(self, other, t):
        def mix(a, b):
            if isinstance(a, (Hand, HandMix)):
                return a.lerp(b, t)
            if isinstance(a, tuple):
                return tuple(mix(x, y) for x, y in zip(a, b))
            return a + (b - a) * t
        return Pose(**{k: mix(getattr(self, k), getattr(other, k)) for k in self.FIELDS})

    def add(self, **offsets):
        """This pose with numbers added to some parts (for layering breathing, sway and the like); for
        hands, metres to move each by."""
        def plus(a, b):
            if isinstance(a, tuple):
                return tuple(plus(x, y) for x, y in zip(a, b))
            return a + b
        values = {k: getattr(self, k) for k in self.FIELDS}
        for k, v in offsets.items():
            if k == "hands":
                values[k] = tuple(h.moved(d) for h, d in zip(values[k], v))
            else:
                values[k] = plus(values[k], v)
        return Pose(**values)


def _two_bone(start, target, l1, l2, pole):
    """Where the middle joint goes, reaching from `start` towards `target`, bending towards `pole`;
    and where the end gets to (the target, or as near as the bones reach)."""
    d = vsub(target, start)
    dist = vlen(d)
    u = vnorm(d) if dist > 1e-6 else (0.0, -1.0, 0.0)
    dist = min(max(dist, abs(l1 - l2) + 1e-3), (l1 + l2) * 0.9995)
    a = (l1 * l1 - l2 * l2 + dist * dist) / (2 * dist)
    h = math.sqrt(max(l1 * l1 - a * a, 0.0))
    side = vsub(pole, vscale(u, vdot(pole, u)))
    if vlen(side) < 1e-6:
        side = vsub((0.0, 0.0, -1.0), vscale(u, -u[2]))
    v = vnorm(side)
    middle = vadd(vadd(start, vscale(u, a)), vscale(v, h))
    end = vadd(start, vscale(u, dist))
    return middle, end


def _frame_map(rest, now):
    """The rotation taking two (orthogonal) rest directions to two current ones."""
    return qnorm(qmul(qframe(now[0], now[1]), qinv(qframe(rest[0], rest[1]))))


def _limb(start, target, l1, l2, pole, rest_axis, rest_hinge):
    """Two-bone inverse kinematics: the upper bone's world turn and the joint's bend (degrees)."""
    middle, end = _two_bone(start, target, l1, l2, pole)
    du, dl = vnorm(vsub(middle, start)), vnorm(vsub(end, middle))
    hinge = vcross(du, dl)
    if vlen(hinge) < 1e-5:
        hinge = vcross(du, vnorm(pole))
    hinge = vnorm(hinge)
    bend = math.degrees(math.acos(max(-1.0, min(1.0, vdot(du, dl)))))
    return _frame_map((rest_axis, rest_hinge), (du, hinge)), bend, dl


def solve(pose):
    """The pose as normalised bone rotations, and the hips' movement (metres)."""
    rot = {"hips": turn(*pose.pelvis)}
    # The body: spine, chest and upper chest share the torso's turn; the neck and head the head's.
    t_turn, t_bend, t_side = pose.torso
    for name, share in (("spine", 0.35), ("chest", 0.35), ("upperChest", 0.30)):
        rot[name] = turn(t_turn * share, t_bend * share, t_side * share)
    h_turn, h_down, h_tilt = pose.head
    rot["neck"] = turn(h_turn * 0.4, h_down * 0.4, h_tilt * 0.4)
    rot["head"] = turn(h_turn * 0.6, h_down * 0.6, h_tilt * 0.6)
    for (side, s), (up, fwd) in zip(SIDES, pose.shoulders):
        rot[side + "Shoulder"] = qnorm(qmul(rz(s * up), ry(-s * fwd)))
    world_rot, world_pos = forward(rot, pose.hips)

    # Arms: each hand placed, the elbow finding its own place. At rest an arm lies along +-x, its
    # elbow's hinge along -+y (the forearm swings forward), its palm down.
    for (side, s), hand, curls, spread in zip(SIDES, pose.hands, pose.fingers, pose.spread):
        target, pole, palm, flex, tilt = hand.resolve(s, world_rot, world_pos)
        g_upper, bend, dl = _limb(world_pos[side + "UpperArm"], target, UPPER_ARM, LOWER_ARM, pole, (s, 0.0, 0.0), (0.0, -s, 0.0))
        rot[side + "UpperArm"] = qnorm(qmul(qinv(world_rot[side + "Shoulder"]), g_upper))
        elbow = ry(-s * bend)
        # The palm faces the hinge's way unless told otherwise; turning it is shared between the
        # forearm and the wrist, about the forearm's own length (local +-x).
        twist = 0.0
        if palm:
            have = qrot(qmul(g_upper, elbow), (0.0, -1.0, 0.0))
            want = vsub(palm, vscale(dl, vdot(palm, dl)))
            if vlen(want) > 1e-4:
                want = vnorm(want)
                twist = math.degrees(math.atan2(vdot(vcross(have, want), dl), vdot(have, want)))
        half = qaxis((s, 0.0, 0.0), twist * 0.5)
        rot[side + "LowerArm"] = qnorm(qmul(elbow, half))
        rot[side + "Hand"] = qnorm(qmul(half, qmul(rz(-s * flex), ry(-s * tilt))))
        # Fingers curl towards the palm (0 straight, 1 a fist); spread fans them.
        thumb, *others = curls
        for finger, curl, fan in zip(FINGERS[1:], others, (-1.0, -0.3, 0.4, 1.0)):
            for joint, angle in (("Proximal", 70.0), ("Intermediate", 95.0), ("Distal", 60.0)):
                q = rz(-s * curl * angle)
                if joint == "Proximal":
                    q = qmul(ry(s * fan * spread * 8.0), q)
                rot[side + finger + joint] = q
        rot[side + "ThumbMetacarpal"] = qnorm(qmul(ry(-s * thumb * 25.0), rx(-thumb * 20.0)))
        rot[side + "ThumbProximal"] = ry(-s * thumb * 35.0)
        rot[side + "ThumbDistal"] = ry(-s * thumb * 40.0)

    # Legs: each foot stays where it is put, flat on the ground, the knee bending forward. At rest a
    # leg points down, its knee's hinge along +x.
    world_rot, world_pos = forward(rot, pose.hips)
    for (side, s), (fx, fz, foot_turn, toes_up), knee_out in zip(SIDES, pose.feet, pose.knees):
        out = math.radians(s * (8.0 + knee_out))
        pole = (math.sin(out), 0.0, math.cos(out))
        g_upper, bend, _ = _limb(world_pos[side + "UpperLeg"], (fx, ANKLE, fz), UPPER_LEG, LOWER_LEG, pole,
                                 (0.0, -1.0, 0.0), (1.0, 0.0, 0.0))
        rot[side + "UpperLeg"] = qnorm(qmul(qinv(world_rot["hips"]), g_upper))
        rot[side + "LowerLeg"] = rx(bend)
        rot[side + "Foot"] = qnorm(qmul(qinv(qmul(g_upper, rx(bend))), qmul(ry(foot_turn), rx(-toes_up))))
    return rot, pose.hips


# ---------------------------------------------------------------- timing


def smooth(t):
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def ease(t, kind="inout"):
    t = min(1.0, max(0.0, t))
    if kind == "in":
        return t * t
    if kind == "out":
        return 1 - (1 - t) * (1 - t)
    return smooth(t)


class Keys:
    """Poses at times, eased between: Keys([(0, rest), (0.4, raised, 'out'), ...]). A key's easing is
    how the move into it goes ('inout' unless given)."""

    def __init__(self, keys):
        self.keys = [(k[0], k[1], k[2] if len(k) > 2 else "inout") for k in keys]

    @property
    def duration(self):
        return self.keys[-1][0]

    def __call__(self, t):
        keys = self.keys
        if t <= keys[0][0]:
            return keys[0][1]
        for (t0, a, _), (t1, b, kind) in zip(keys, keys[1:]):
            if t <= t1:
                return a.lerp(b, ease((t - t0) / max(t1 - t0, 1e-6), kind))
        return keys[-1][1]


def wave_of(t, period, phase=0.0):
    """A smooth back-and-forth, -1 to 1."""
    return math.sin(2 * math.pi * (t / period + phase))


# ---------------------------------------------------------------- writing .vrma files


def _accessor(blob, views, accessors, values, kind, count, minmax=False):
    while len(blob) % 4:
        blob.append(0)
    offset = len(blob)
    blob.extend(struct.pack("<%df" % len(values), *values))
    views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(values) * 4})
    acc = {"bufferView": len(views) - 1, "componentType": 5126, "count": count, "type": kind}
    if minmax:
        acc["min"], acc["max"] = [min(values)], [max(values)]
    accessors.append(acc)
    return len(accessors) - 1


def write_vrma(path, clip, duration, title="", still_tolerance=0.05):
    """Sample `clip(t) -> Pose` at 30 frames a second for `duration` seconds and write a .vrma file."""
    frames = int(round(duration * RATE)) + 1
    times = [min(k / RATE, duration) for k in range(frames)]
    tracks = {name: [] for name in ORDER}
    hips = []
    for t in times:
        rot, offset = solve(clip(t))
        for name in ORDER:
            tracks[name].append(qnorm(rot.get(name, (0, 0, 0, 1))))
        hips.append(offset)
    nodes = []
    index = {}
    for name, parent, pos in SKELETON:
        index[name] = len(nodes)
        local = pos if parent is None else vsub(pos, REST[parent])
        nodes.append({"name": name, "translation": [round(c, 5) for c in local]})
    for name, parent, _ in SKELETON:
        if parent is not None:
            nodes[index[parent]].setdefault("children", []).append(index[name])
    blob = bytearray()
    views, accessors, samplers, channels = [], [], [], []
    time_acc = _accessor(blob, views, accessors, times, "SCALAR", frames, minmax=True)
    first_acc = _accessor(blob, views, accessors, [0.0], "SCALAR", 1, minmax=True)
    for name in ORDER:
        if name.endswith("Eye") or name == "jaw":
            continue
        qs = tracks[name]
        # Make each frame the nearest to the one before (no flips through the long way round).
        for k in range(1, len(qs)):
            if sum(a * b for a, b in zip(qs[k], qs[k - 1])) < 0:
                qs[k] = tuple(-c for c in qs[k])
        if all(qangle(q, qs[0]) < still_tolerance for q in qs):
            if qangle(qs[0]) < still_tolerance:
                continue
            out = _accessor(blob, views, accessors, list(qs[0]), "VEC4", 1)
            samplers.append({"input": first_acc, "output": out, "interpolation": "LINEAR"})
        else:
            out = _accessor(blob, views, accessors, [c for q in qs for c in q], "VEC4", frames)
            samplers.append({"input": time_acc, "output": out, "interpolation": "LINEAR"})
        channels.append({"sampler": len(samplers) - 1, "target": {"node": index[name], "path": "rotation"}})
    if any(vlen(h) > 1e-5 for h in hips):
        out = _accessor(blob, views, accessors, [c for h in hips for c in vadd(REST["hips"], h)], "VEC3", frames)
        samplers.append({"input": time_acc, "output": out, "interpolation": "LINEAR"})
        channels.append({"sampler": len(samplers) - 1, "target": {"node": index["hips"], "path": "translation"}})
    doc = {
        "asset": {"version": "2.0", "generator": "companion vrma_kit"},
        "extensionsUsed": ["VRMC_vrm_animation"],
        "scene": 0,
        "scenes": [{"nodes": [index["hips"]]}],
        "nodes": nodes,
        "animations": [{"name": title or "clip", "samplers": samplers, "channels": channels}],
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": len(blob)}],
        "extensions": {"VRMC_vrm_animation": {
            "specVersion": "1.0",
            "humanoid": {"humanBones": {name: {"node": index[name]} for name in ORDER}},
        }},
    }
    text = json.dumps(doc, separators=(",", ":")).encode()
    text += b" " * (-len(text) % 4)
    blob.extend(b"\x00" * (-len(blob) % 4))
    total = 12 + 8 + len(text) + 8 + len(blob)
    with open(path, "wb") as f:
        f.write(struct.pack("<4sII", b"glTF", 2, total))
        f.write(struct.pack("<I4s", len(text), b"JSON") + text)
        f.write(struct.pack("<I4s", len(blob), b"BIN\x00") + bytes(blob))
    return frames
