#!/usr/bin/env python3
"""The built-in full-body animations for 3D (VRM) avatars, written as VRM Animation clips into
stage/motions/vrma (docs/30-vrm.md).

    python3 stage/tools/vrma_library.py [NAME ...]

Idle loops (played round and round under everything else, chosen by what the character is doing and
its mood) are named idle, idle_<mood>, idle_listen, idle_think, idle_talk and idle_sleep. The others
are gestures and idle actions of the motion library (stage/motions/library.json) of the same name: the
stage plays the clip for the body and keeps the library's face movements. Head-only gestures (nods,
shakes, glances) stay with the library, which times them to speech.

Every clip is written here from scratch on the kit's reference skeleton (vrma_kit.py). Each gesture
starts and ends at REST, the plain standing pose, so it joins any idle loop.
"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from vrma_kit import (FIST, LOOSE_FIST, OPEN_FINGERS, RELAXED_FINGERS, Hand, Keys, Pose,  # noqa: E402
                      relaxed_hand, smooth, wave_of, write_vrma)

OUT = os.path.join(HERE, "..", "motions", "vrma")
REST = Pose()
CLIPS = {}
L, R = 1.0, -1.0


def clip(name, duration):
    def register(fn):
        CLIPS[name] = (fn, duration)
        return fn
    return register


def breathing(t, period=4.0, depth=1.0):
    """Breathing: the chest rises and the shoulders lift a little."""
    b = 0.5 - 0.5 * math.cos(2 * math.pi * t / period)
    return dict(torso=(0.0, -0.9 * depth * b, 0.0), shoulders=((0.6 * depth * b, 0.0), (0.6 * depth * b, 0.0)))


def both(fingers):
    return (fingers, fingers)


def bump(t, start, end):
    """0 outside (start, end), rising to 1 and back smoothly inside."""
    if t <= start or t >= end:
        return 0.0
    return math.sin(math.pi * (t - start) / (end - start)) ** 2


def envelope(t, duration, fade=0.6):
    """1 in the middle, easing from and to 0 at the ends (for movements that must end where they began)."""
    return smooth(t / fade) * smooth((duration - t) / fade)


# ---------------------------------------------------------------- idle loops


@clip("idle", 8.0)
def idle(t):
    """Standing easy: the weight drifts from foot to foot, the head turns a little, breathing."""
    sway = wave_of(t, 8.0)
    lag = wave_of(t, 8.0, -0.08)
    pose = REST.add(hips=(0.012 * sway, -0.004 * abs(sway), 0.0), pelvis=(0.0, 0.0, -1.2 * sway),
                    torso=(0.0, 0.0, 1.0 * sway), head=(1.5 * wave_of(t, 8.0, 0.25), 0.0, 0.8 * sway),
                    hands=((0.0, 0.0, 0.006 * lag), (0.0, 0.0, 0.006 * lag)))
    return pose.add(**breathing(t))


HAPPY = REST.but(torso=(0.0, -2.5, 0.0), head=(0.0, -2.0, 0.0), shoulders=((0.0, -2.0), (0.0, -2.0)),
                 hands=(Hand((0.06, -0.04, -0.15), "hips", pole=(1.0, -0.2, -0.6), palm=(0.0, 0.0, -1.0)),
                        Hand((-0.06, -0.04, -0.15), "hips", pole=(-1.0, -0.2, -0.6), palm=(0.0, 0.0, -1.0))),
                 fingers=both((0.3, 0.35, 0.4, 0.45, 0.5)))


@clip("idle_happy", 6.0)
def idle_happy(t):
    """Hands behind the back, rocking from side to side in time, a little bob at each side."""
    sway = wave_of(t, 3.0)
    lag = wave_of(t, 3.0, -0.06)
    bob = -math.cos(2 * math.pi * t / 1.5)
    pose = HAPPY.add(hips=(0.016 * sway, 0.004 * bob, 0.0), pelvis=(0.0, 0.0, -2.0 * sway),
                     torso=(1.5 * sway, 0.0, 3.0 * sway), head=(2.0 * lag, 0.0, 4.0 * lag))
    return pose.add(**breathing(t, 3.0, 0.8))


SAD = REST.but(hips=(0.0, -0.016, 0.005), torso=(0.0, 9.0, 0.0), head=(0.0, 14.0, 0.0),
               shoulders=((-2.5, 6.0), (-2.5, 6.0)),
               hands=(relaxed_hand(L, out=-0.025, forward=0.035), relaxed_hand(R, out=-0.025, forward=0.035)),
               fingers=both((0.3, 0.3, 0.36, 0.42, 0.48)))


@clip("idle_sad", 8.0)
def idle_sad(t):
    """Slumped, head down, arms hanging close; slow breathing with a sigh."""
    sway = wave_of(t, 8.0)
    sigh = bump(t, 4.0, 7.5)
    pose = SAD.add(hips=(0.006 * sway, 0.0, 0.0), pelvis=(0.0, 0.0, -0.6 * sway), head=(2.0 * wave_of(t, 8.0, 0.3), 0.0, 1.0 * sway),
                   torso=(0.0, -2.5 * sigh, 0.0), shoulders=((2.5 * sigh, 0.0), (2.5 * sigh, 0.0)))
    return pose.add(**breathing(t, 4.0, 0.7))


ANGRY = REST.but(hips=(0.022, -0.016, 0.0), pelvis=(0.0, 0.0, -3.0), torso=(0.0, 3.0, 2.5), head=(0.0, 5.0, -1.0),
                 shoulders=((4.0, 2.0), (4.0, 2.0)),
                 hands=(relaxed_hand(L, out=0.03, forward=0.02), relaxed_hand(R, out=0.03, forward=0.02)),
                 fingers=both(FIST))


@clip("idle_angry", 6.0)
def idle_angry(t):
    """Fists clenched, shoulders up, weight on one leg; the free foot taps, quick breathing."""
    pose = ANGRY.add(head=(1.5 * wave_of(t, 6.0), 0.0, 0.0))
    # Three quick taps of the right foot, twice a loop.
    tap = 0.0
    for start in (0.6, 3.6):
        if start <= t < start + 1.2:
            tap = abs(math.sin(math.pi * (t - start) / 0.4)) * 14.0
    pose = pose.but(feet=(pose.feet[0], (pose.feet[1][0], pose.feet[1][1], pose.feet[1][2], tap)))
    return pose.add(**breathing(t, 2.0, 1.1))


SHY = REST.but(hips=(0.0, -0.02, 0.0), torso=(0.0, 4.0, 0.0), head=(0.0, 9.0, 6.0), shoulders=((4.0, 5.0), (4.0, 5.0)),
               hands=(Hand((0.03, 0.04, 0.15), "hips", pole=(1.0, -0.6, -0.3), palm=(-0.3, 0.0, -1.0), flex=10.0),
                      Hand((-0.03, 0.04, 0.15), "hips", pole=(-1.0, -0.6, -0.3), palm=(0.3, 0.0, -1.0), flex=10.0)),
               fingers=both((0.2, 0.15, 0.2, 0.25, 0.3)),
               feet=((0.08, 0.0, -8.0, 0.0), (-0.08, 0.0, 8.0, 0.0)), knees=(-10.0, -10.0))


@clip("idle_embarrassed", 6.0)
def idle_embarrassed(t):
    """Shrinking: shoulders up, head down and tilted, hands together in front, toes in; a little fidget."""
    sway = wave_of(t, 3.0)
    pose = SHY.add(hips=(0.006 * sway, 0.0, 0.0), torso=(2.0 * wave_of(t, 6.0), 0.0, 1.0 * sway),
                   head=(3.0 * wave_of(t, 6.0, 0.2), 0.0, 1.5 * sway))
    return pose.add(**breathing(t, 3.0, 0.8))


LISTEN = REST.but(hips=(-0.012, -0.014, 0.0), pelvis=(0.0, 0.0, 1.5), torso=(0.0, 5.0, -1.0), head=(0.0, -1.0, 5.0),
                  hands=(relaxed_hand(L, forward=0.03), relaxed_hand(R, forward=0.03)))


@clip("idle_listen", 6.0)
def idle_listen(t):
    """Leaning in a little, head tilted, still and attentive."""
    pose = LISTEN.add(head=(1.5 * wave_of(t, 6.0, 0.1), 0.0, 1.0 * wave_of(t, 6.0)), torso=(0.0, 0.8 * wave_of(t, 6.0, 0.3), 0.0))
    return pose.add(**breathing(t, 3.0, 0.8))


CHIN = Hand((-0.02, 1.275, 0.125), "world", pole=(-0.2, -1.0, 0.1), palm=(0.4, 0.2, -1.0), flex=-20.0)
ELBOW_REST = Hand((-0.07, 1.04, 0.135), "world", pole=(1.0, -0.5, -0.3), palm=(0.0, 1.0, 0.0))
THINK = REST.but(torso=(-4.0, 1.5, -1.5), head=(-4.0, -3.0, 7.0), hands=(ELBOW_REST, CHIN),
                 fingers=((0.4, 0.35, 0.4, 0.45, 0.5), (0.5, 0.45, 0.65, 0.7, 0.75)))


@clip("idle_think", 6.0)
def idle_think(t):
    """Hand to the chin, the other arm across the waist under its elbow; head tilted, looking up."""
    pose = THINK.add(head=(2.0 * wave_of(t, 6.0), 0.0, 1.5 * wave_of(t, 6.0, 0.25)),
                     hands=((0.0, 0.0, 0.0), (0.0, 0.004 * wave_of(t, 1.5), 0.0)))
    return pose.add(**breathing(t, 3.0, 0.7))


TALK = REST.but(hands=(Hand((0.13, 0.98, 0.17), "world", pole=(1.0, -0.8, -0.4), palm=(-0.5, 0.8, 0.0), flex=-5.0),
                       Hand((-0.13, 0.98, 0.17), "world", pole=(-1.0, -0.8, -0.4), palm=(0.5, 0.8, 0.0), flex=-5.0)),
                fingers=both((0.15, 0.12, 0.18, 0.24, 0.3)))
TALK_LOW = REST.but(hands=(relaxed_hand(L, forward=0.05, up=0.03), Hand((-0.12, 0.97, 0.18), "world", pole=(-1.0, -0.8, -0.4),
                                                                      palm=(0.4, 0.9, 0.1), flex=-5.0)),
                    fingers=(RELAXED_FINGERS, (0.15, 0.12, 0.18, 0.24, 0.3)))
TALK_OPEN = TALK.but(hands=(TALK.hands[0], Hand((-0.24, 1.02, 0.19), "world", pole=(-1.0, -0.8, -0.4), palm=(-0.1, 1.0, 0.2))),
                     torso=(-3.0, 0.0, 0.0), fingers=(TALK.fingers[0], OPEN_FINGERS), spread=(0.0, 0.5))
TALK_BALL = TALK.but(hands=(Hand((0.11, 1.03, 0.19), "world", pole=(1.0, -0.8, -0.4), palm=(-1.0, 0.2, 0.0)),
                            Hand((-0.11, 1.03, 0.19), "world", pole=(-1.0, -0.8, -0.4), palm=(1.0, 0.2, 0.0))),
                     torso=(2.0, 0.0, 0.0), fingers=both((0.12, 0.1, 0.15, 0.2, 0.25)))


@clip("idle_talk", 8.0)
def idle_talk(t):
    """Talking: one hand up and moving with the words, then both, opening out and coming together."""
    keys = Keys([(0.0, TALK_LOW), (1.8, TALK_LOW), (2.6, TALK), (3.6, TALK_OPEN), (4.6, TALK), (5.6, TALK_BALL),
                 (6.6, TALK), (8.0, TALK_LOW)])
    pose = keys(t)
    # Small beats of the hands, not quite together.
    beat_r = 0.012 * wave_of(t, 0.8) * (0.6 + 0.4 * wave_of(t, 8.0))
    beat_l = 0.010 * wave_of(t, 0.8, 0.3) * smooth((t - 2.0) / 0.6) * smooth((7.2 - t) / 0.6)
    pose = pose.add(hands=((0.0, beat_l, 0.0), (0.0, beat_r, 0.0)), torso=(2.5 * wave_of(t, 8.0, 0.1), 0.0, 0.0),
                    hips=(0.008 * wave_of(t, 8.0), 0.0, 0.0), pelvis=(0.0, 0.0, -0.8 * wave_of(t, 8.0)))
    return pose.add(**breathing(t, 4.0, 0.9))


ASLEEP = REST.but(hips=(0.0, -0.02, 0.0), torso=(0.0, 10.0, 0.0), head=(0.0, 26.0, 10.0), shoulders=((-3.0, 6.0), (-3.0, 6.0)),
                  hands=(relaxed_hand(L, out=-0.015, forward=0.04), relaxed_hand(R, out=-0.015, forward=0.04)),
                  fingers=both((0.3, 0.35, 0.4, 0.45, 0.5)))


@clip("idle_sleep", 8.0)
def idle_sleep(t):
    """Dozing on its feet: slumped, head drooping, deep slow breaths."""
    b = 0.5 - 0.5 * math.cos(2 * math.pi * t / 4.0)
    pose = ASLEEP.add(head=(0.0, -3.0 * b, 0.0), torso=(0.0, -1.5 * b, 0.0), shoulders=((1.2 * b, 0.0), (1.2 * b, 0.0)),
                      hips=(0.004 * wave_of(t, 8.0), 0.0, 0.0))
    return pose


# ---------------------------------------------------------------- gestures


RAISED_RIGHT = Hand((-0.34, 1.40, 0.08), "world", pole=(-1.0, -0.8, -0.2), palm=(0.0, 0.0, 1.0), flex=-8.0)


@clip("wave", 2.1)
def wave(t):
    """Hand up beside the head, palm to the viewer, the forearm swinging at the elbow."""
    up = REST.but(hands=(relaxed_hand(L), RAISED_RIGHT), fingers=(RELAXED_FINGERS, OPEN_FINGERS), spread=(0.0, 0.6),
                  head=(4.0, 0.0, -5.0), torso=(0.0, 0.0, 3.0), shoulders=((0.0, 0.0), (2.0, 0.0)))
    pose = Keys([(0.0, REST), (0.45, up, "out"), (1.65, up), (2.1, REST)])(t)
    w = smooth((t - 0.35) / 0.15) * smooth((1.75 - t) / 0.2)
    x = 0.075 * wave_of(t - 0.45, 0.5) * w
    return pose.add(hands=((0.0, 0.0, 0.0), (x, -abs(x) * 0.35, 0.0)))


@clip("greet", 1.6)
def greet(t):
    """A small hello: the hand up at the shoulder, palm out, a quick wiggle."""
    hi = REST.but(hands=(relaxed_hand(L), Hand((-0.25, 1.24, 0.17), "world", pole=(-1.0, -1.0, -0.2), palm=(0.0, 0.0, 1.0))),
                  fingers=(RELAXED_FINGERS, OPEN_FINGERS), spread=(0.0, 0.5), head=(3.0, -2.0, -6.0), torso=(0.0, -1.0, 2.0))
    pose = Keys([(0.0, REST), (0.35, hi, "out"), (1.15, hi), (1.6, REST)])(t)
    x = 0.03 * wave_of(t - 0.35, 0.35) * smooth((t - 0.3) / 0.1) * smooth((1.15 - t) / 0.15)
    return pose.add(hands=((0.0, 0.0, 0.0), (x, 0.0, 0.0)))


BOWED = REST.but(hips=(0.0, -0.022, -0.05), pelvis=(0.0, 18.0, 0.0), torso=(0.0, 14.0, 0.0), head=(0.0, 10.0, 0.0),
                 hands=(Hand((0.065, -0.17, 0.13), "hips", pole=(1.0, 0.0, -0.4), palm=(-0.3, 0.0, -1.0)),
                        Hand((-0.065, -0.17, 0.13), "hips", pole=(-1.0, 0.0, -0.4), palm=(0.3, 0.0, -1.0))),
                 fingers=both((0.1, 0.08, 0.1, 0.12, 0.15)))


@clip("bow", 2.4)
def bow(t):
    """A polite bow from the hips, hands sliding to the front of the thighs."""
    tall = REST.add(torso=(0.0, -1.5, 0.0), head=(0.0, -1.0, 0.0))
    return Keys([(0.0, REST), (0.25, tall), (0.95, BOWED), (1.45, BOWED.add(torso=(0.0, 1.0, 0.0))), (2.4, REST)])(t)


@clip("bounce", 1.0)
def bounce(t):
    """A happy little bounce on the spot, arms swinging out."""
    dip = REST.add(hips=(0.0, -0.035, 0.0), torso=(0.0, 4.0, 0.0), hands=((0.0, 0.02, -0.03), (0.0, 0.02, -0.03)))
    up = REST.add(hips=(0.0, 0.004, 0.0), torso=(0.0, -2.0, 0.0), head=(0.0, -3.0, 0.0), shoulders=((4.0, 0.0), (4.0, 0.0)),
                  hands=((0.04, 0.05, 0.02), (-0.04, 0.05, 0.02))).but(fingers=both(OPEN_FINGERS))
    small = REST.add(hips=(0.0, -0.014, 0.0), torso=(0.0, 1.5, 0.0))
    return Keys([(0.0, REST), (0.2, dip), (0.45, up, "out"), (0.7, small), (1.0, REST)])(t)


@clip("laugh", 1.5)
def laugh(t):
    """Head back on the first laugh, then folding forward a little, shoulders shaking."""
    back = REST.add(torso=(0.0, -3.0, 0.0), head=(0.0, -8.0, 0.0), shoulders=((3.0, 0.0), (3.0, 0.0)))
    folded = REST.but(hands=(Hand((0.09, 0.12, 0.13), "hips", pole=(1.0, -0.6, -0.4), palm=(-0.4, 0.0, -1.0)),
                             relaxed_hand(R, forward=0.04, up=0.04)),
                      torso=(2.0, 8.0, 0.0), head=(0.0, 6.0, 3.0))
    pose = Keys([(0.0, REST), (0.2, back, "out"), (0.55, folded), (1.1, folded), (1.5, REST)])(t)
    shake = math.sin(2 * math.pi * t * 5.0) * bump(t, 0.15, 1.25)
    return pose.add(torso=(0.0, 1.5 * shake, 0.0), shoulders=((1.5 * shake, 0.0), (1.5 * shake, 0.0)))


@clip("sigh", 2.4)
def sigh(t):
    """A deep breath in, chest and shoulders up, then out: slumping, head dropping."""
    breath = REST.add(torso=(0.0, -3.0, 0.0), shoulders=((6.0, -1.0), (6.0, -1.0)), head=(0.0, -4.0, 0.0))
    out = REST.add(torso=(0.0, 6.0, 0.0), shoulders=((-3.0, 3.0), (-3.0, 3.0)), head=(0.0, 8.0, 0.0),
                   hips=(0.0, -0.006, 0.0), hands=((-0.01, -0.01, 0.01), (0.01, -0.01, 0.01)))
    return Keys([(0.0, REST), (0.9, breath), (1.7, out), (2.4, REST)])(t)


@clip("sway", 3.4)
def sway(t):
    """One slow sway to the side and back."""
    side = REST.add(hips=(0.03, -0.006, 0.0), pelvis=(0.0, 0.0, -3.0), torso=(0.0, 0.0, 4.0), head=(0.0, 0.0, 5.0),
                    hands=((0.01, 0.0, 0.0), (0.01, 0.0, 0.0)))
    over = REST.add(hips=(-0.008, 0.0, 0.0), pelvis=(0.0, 0.0, 1.0), torso=(0.0, 0.0, -1.0), head=(0.0, 0.0, -1.5))
    return Keys([(0.0, REST), (1.3, side), (2.5, over), (3.4, REST)])(t)


@clip("lean_in", 1.8)
def lean_in(t):
    """Leaning in towards the person, eyes kept on them."""
    leaning = REST.add(hips=(0.0, -0.004, -0.012), pelvis=(0.0, 2.0, 0.0), torso=(0.0, 10.0, 0.0), head=(0.0, -7.0, 2.0),
                       hands=((-0.01, 0.0, 0.03), (0.01, 0.0, 0.03)))
    return Keys([(0.0, REST), (0.6, leaning), (1.2, leaning), (1.8, REST)])(t)


@clip("lean_back", 1.5)
def lean_back(t):
    """Leaning back a little, shoulders back."""
    back = REST.add(hips=(0.0, 0.0, 0.012), torso=(0.0, -6.0, 0.0), head=(0.0, 3.0, -2.0), shoulders=((0.0, -3.0), (0.0, -3.0)),
                    hands=((0.0, 0.0, -0.015), (0.0, 0.0, -0.015)))
    return Keys([(0.0, REST), (0.5, back), (1.0, back), (1.5, REST)])(t)


@clip("surprise", 1.4)
def surprise(t):
    """A start: shoulders jump, hands come up in front of the chest, the body pulls back."""
    jolt = REST.but(torso=(0.0, -4.0, 0.0), head=(0.0, -6.0, 0.0), shoulders=((8.0, 0.0), (8.0, 0.0)),
                    hands=(Hand((0.10, -0.13, 0.17), "chest", pole=(1.0, -0.8, -0.2), palm=(0.0, 0.0, 1.0)),
                           Hand((-0.10, -0.13, 0.17), "chest", pole=(-1.0, -0.8, -0.2), palm=(0.0, 0.0, 1.0))),
                    fingers=both(OPEN_FINGERS), spread=(1.0, 1.0), hips=(0.0, -0.016, 0.006))
    held = jolt.add(shoulders=((-2.0, 0.0), (-2.0, 0.0)), hands=((0.0, -0.01, 0.0), (0.0, -0.01, 0.0)))
    return Keys([(0.0, REST), (0.13, jolt, "out"), (0.65, held), (1.4, REST)])(t)


@clip("think", 2.6)
def think(t):
    """A hand to the chin for a moment, head tilted."""
    pose = REST.but(hands=(relaxed_hand(L, forward=0.02), CHIN), fingers=(RELAXED_FINGERS, THINK.fingers[1]),
                    head=(-3.0, -3.0, 7.0), torso=(-2.0, 1.0, 0.0))
    pose_t = Keys([(0.0, REST), (0.6, pose), (2.0, pose), (2.6, REST)])(t)
    return pose_t.add(hands=((0.0, 0.0, 0.0), (0.0, 0.004 * wave_of(t, 0.7) * bump(t, 0.7, 1.9), 0.0)))


ON_HIPS = REST.but(hips=(0.012, -0.012, 0.0), pelvis=(0.0, 0.0, -1.5), torso=(0.0, -3.0, 1.0), head=(0.0, -2.0, -2.0),
                   shoulders=((0.0, -3.0), (0.0, -3.0)),
                   hands=(Hand((0.165, 0.10, -0.01), "hips", pole=(1.0, 0.1, -0.4), palm=(-1.0, 0.0, 0.0), flex=-15.0),
                          Hand((-0.165, 0.10, -0.01), "hips", pole=(-1.0, 0.1, -0.4), palm=(1.0, 0.0, 0.0), flex=-15.0)),
                   fingers=both((0.3, 0.15, 0.2, 0.25, 0.3)))


@clip("hands_on_hips", 3.0)
def hands_on_hips(t):
    """Both hands on the hips, chest out, a shift of the weight."""
    shifted = ON_HIPS.add(hips=(-0.02, 0.0, 0.0), pelvis=(0.0, 0.0, 2.5), torso=(0.0, 0.0, -2.0), head=(0.0, 0.0, 3.0))
    return Keys([(0.0, REST), (0.5, ON_HIPS, "out"), (1.5, shifted), (2.4, ON_HIPS), (3.0, REST)])(t)


SHRUG = REST.but(shoulders=((10.0, 1.0), (10.0, 1.0)), head=(0.0, 0.0, 6.0), torso=(0.0, -1.0, 0.0),
                 hands=(Hand((0.30, -0.24, 0.12), "chest", pole=(0.6, -1.0, -0.4), palm=(0.0, 1.0, 0.2)),
                        Hand((-0.30, -0.24, 0.12), "chest", pole=(-0.6, -1.0, -0.4), palm=(0.0, 1.0, 0.2))),
                 fingers=both(OPEN_FINGERS), spread=(0.5, 0.5))


@clip("shrug", 1.4)
def shrug(t):
    """Shoulders up, forearms out, palms up: who knows?"""
    return Keys([(0.0, REST), (0.35, SHRUG, "out"), (0.8, SHRUG.add(shoulders=((-1.5, 0.0), (-1.5, 0.0)))), (1.4, REST)])(t)


# ---------------------------------------------------------------- idle actions


@clip("stretch", 3.6)
def stretch(t):
    """Arms up over the head, a lean to one side, then the arms down wide."""
    up = REST.but(hands=(Hand((0.035, 1.70, 0.02), "world", pole=(1.0, 0.0, -0.3), palm=(0.0, 1.0, 0.0)),
                         Hand((-0.035, 1.70, 0.02), "world", pole=(-1.0, 0.0, -0.3), palm=(0.0, 1.0, 0.0))),
                  fingers=both(LOOSE_FIST), hips=(0.0, 0.002, 0.0), torso=(0.0, -4.0, 0.0), head=(0.0, -8.0, 0.0),
                  shoulders=((8.0, -1.0), (8.0, -1.0)))
    lean = up.add(torso=(0.0, 0.0, 9.0), pelvis=(0.0, 0.0, -2.0), hips=(-0.015, -0.01, 0.0), head=(0.0, 0.0, 6.0))
    wide = REST.but(hands=(Hand((0.36, -0.08, 0.05), "hang", pole=(1.0, -1.0, -0.3), palm=(0.0, -1.0, 0.3)),
                           Hand((-0.36, -0.08, 0.05), "hang", pole=(-1.0, -1.0, -0.3), palm=(0.0, -1.0, 0.3))),
                    fingers=both(OPEN_FINGERS), torso=(0.0, -1.0, 0.0))
    return Keys([(0.0, REST), (0.9, up), (1.3, up), (2.0, lean), (2.5, up), (3.05, wide), (3.6, REST)])(t)


@clip("look_around", 4.5)
def look_around(t):
    """Turning to look one way, then the other, the head leading."""
    one = REST.add(pelvis=(5.0, 0.0, 0.0), torso=(16.0, 0.0, 0.0), head=(24.0, -2.0, 0.0))
    other = REST.add(pelvis=(-4.0, 0.0, 0.0), torso=(-13.0, 0.0, 0.0), head=(-22.0, 1.0, 0.0))
    return Keys([(0.0, REST), (1.0, one), (1.7, one), (2.8, other), (3.5, other), (4.5, REST)])(t)


@clip("look_out_window", 6.8)
def look_out_window(t):
    """Turning to gaze into the distance a while, weight on one leg."""
    gaze = REST.add(hips=(0.018, -0.004, 0.0), pelvis=(8.0, 0.0, -2.0), torso=(20.0, 0.0, 1.5), head=(28.0, -4.0, 2.0),
                    hands=((0.0, 0.0, 0.02), (0.02, 0.02, 0.06)))
    pose = Keys([(0.0, REST), (1.4, gaze), (5.4, gaze), (6.8, REST)])(t)
    return pose.add(head=(1.5 * wave_of(t, 3.4) * bump(t, 1.2, 5.6), 0.0, 0.0), **breathing(t, 3.4, 0.6))


MOUTH = Hand((-0.02, 1.30, 0.135), "world", pole=(-0.6, -1.0, 0.0), palm=(0.2, 0.0, -1.0), flex=-25.0)


@clip("yawn", 3.2)
def yawn(t):
    """Head back and a hand over the mouth, shoulders up, then down again."""
    inhale = REST.add(head=(0.0, -6.0, 0.0), shoulders=((4.0, 0.0), (4.0, 0.0)), torso=(0.0, -2.0, 0.0))
    covered = REST.but(hands=(relaxed_hand(L), MOUTH), fingers=(RELAXED_FINGERS, (0.1, 0.05, 0.05, 0.08, 0.12)),
                       head=(0.0, -13.0, 4.0), shoulders=((6.0, 0.0), (6.0, 0.0)), torso=(0.0, -4.0, 0.0))
    after = covered.add(head=(0.0, 6.0, 0.0), shoulders=((-4.0, 0.0), (-4.0, 0.0)))
    return Keys([(0.0, REST), (0.6, inhale), (1.05, covered), (2.0, covered), (2.4, after), (3.2, REST)])(t)


@clip("hum_sway", 6.0)
def hum_sway(t):
    """Swaying in time to a tune, head tilting with it."""
    e = envelope(t, 6.0, 0.9)
    sway = wave_of(t, 2.0) * e
    lag = wave_of(t, 2.0, -0.06) * e
    bob = (-math.cos(2 * math.pi * t / 1.0)) * e
    return REST.add(hips=(0.02 * sway, 0.003 * bob, 0.0), pelvis=(0.0, 0.0, -2.5 * sway), torso=(1.5 * lag, 0.0, 3.0 * sway),
                    head=(0.0, 0.0, 5.0 * lag), hands=((0.012 * lag, 0.0, 0.0), (0.012 * lag, 0.0, 0.0)))


@clip("settle", 2.2)
def settle(t):
    """Shifting the weight to the other foot and rolling a shoulder."""
    shift = REST.add(hips=(0.025, -0.006, 0.0), pelvis=(0.0, 0.0, -3.0), torso=(0.0, 0.0, 2.0),
                     shoulders=((5.0, -2.0), (0.0, 0.0)), head=(0.0, 0.0, 1.5))
    roll = shift.add(shoulders=((-5.0, 3.0), (0.0, 0.0)))
    return Keys([(0.0, REST), (0.7, shift), (1.2, roll), (2.2, REST)])(t)


@clip("nod_off", 4.5)
def nod_off(t):
    """The head sinks slowly as sleep comes, then jerks up."""
    drooping = REST.add(head=(0.0, 24.0, 6.0), torso=(0.0, 6.0, 0.0), shoulders=((-3.0, 3.0), (-3.0, 3.0)), hips=(0.0, -0.006, 0.0))
    caught = REST.add(head=(0.0, -4.0, 0.0), shoulders=((5.0, 0.0), (5.0, 0.0)), torso=(0.0, -2.0, 0.0))
    return Keys([(0.0, REST), (2.9, drooping, "in"), (3.1, caught, "out"), (3.6, caught), (4.5, REST)])(t)


@clip("wake", 1.4)
def wake(t):
    """Waking with a start: shoulders up, straightening, looking up."""
    jolt = REST.add(shoulders=((10.0, 0.0), (10.0, 0.0)), torso=(0.0, -4.0, 0.0), head=(0.0, -6.0, 0.0),
                    hands=((0.03, 0.03, 0.02), (-0.03, 0.03, 0.02)), hips=(0.0, -0.01, 0.0))
    return Keys([(0.0, REST), (0.12, jolt, "out"), (0.6, jolt.add(shoulders=((-4.0, 0.0), (-4.0, 0.0)))), (1.4, REST)])(t)


def main(names):
    os.makedirs(OUT, exist_ok=True)
    for name, (fn, duration) in sorted(CLIPS.items()):
        if names and name not in names:
            continue
        frames = write_vrma(os.path.join(OUT, name + ".vrma"), fn, duration, title=name)
        print("%-18s %5.2f s  %3d frames  %6d bytes" % (name, duration, frames, os.path.getsize(os.path.join(OUT, name + ".vrma"))))


if __name__ == "__main__":
    main(sys.argv[1:])
