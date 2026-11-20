"""Ed25519 signatures in plain Python (RFC 8032), for device/release.py.

The release tool signs updates on the owner's own computer. A Mac's `openssl` command is LibreSSL,
which may lack Ed25519, so the tool does not depend on it: this file makes and checks the same
signatures OpenSSL 3 does (Ed25519 is deterministic, so they are byte for byte the same; see
core/tests/test_updates.py). Devices still check with OpenSSL (core/companion/updates.py).

Key files are the usual PEM files: the private key as PKCS #8 ("BEGIN PRIVATE KEY"), the public key
as SubjectPublicKeyInfo ("BEGIN PUBLIC KEY"), as `openssl genpkey -algorithm ed25519` writes them.

This is written for clarity, not speed or secrecy from timing: signing a few updates on your own
computer is its only job. Never use it on a server that signs for others.
"""
import base64
import hashlib
import os

P = 2 ** 255 - 19
L = 2 ** 252 + 27742317777372353535851937790883648493
D = -121665 * pow(121666, P - 2, P) % P
SQRT_M1 = pow(2, (P - 1) // 4, P)

# DER prefixes of the two key files (RFC 8410): the 32 key bytes follow each.
PRIVATE_PREFIX = bytes.fromhex("302e020100300506032b657004220420")
PRIVATE_PREFIX_V2 = bytes.fromhex("3051020101300506032b657004220420")
PUBLIC_PREFIX = bytes.fromhex("302a300506032b6570032100")


def _inv(x):
    return pow(x, P - 2, P)


def _recover_x(y, sign):
    if y >= P:
        return None
    x2 = (y * y - 1) * _inv(D * y * y + 1) % P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (P + 3) // 8, P)
    if (x * x - x2) % P:
        x = x * SQRT_M1 % P
    if (x * x - x2) % P:
        return None
    if (x & 1) != sign:
        x = P - x
    return x


# Points in extended coordinates (X, Y, Z, T): x = X/Z, y = Y/Z, x*y = T/Z.
_GY = 4 * _inv(5) % P
_GX = _recover_x(_GY, 0)
BASE = (_GX, _GY, 1, _GX * _GY % P)
ZERO = (0, 1, 1, 0)


def _add(p, q):
    a = (p[1] - p[0]) * (q[1] - q[0]) % P
    b = (p[1] + p[0]) * (q[1] + q[0]) % P
    c = 2 * p[3] * q[3] * D % P
    d = 2 * p[2] * q[2] % P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % P, g * h % P, f * g % P, e * h % P)


def _times(s, p):
    out = ZERO
    while s:
        if s & 1:
            out = _add(out, p)
        p = _add(p, p)
        s >>= 1
    return out


def _same(p, q):
    return (p[0] * q[2] - q[0] * p[2]) % P == 0 and (p[1] * q[2] - q[1] * p[2]) % P == 0


def _encode(p):
    zi = _inv(p[2])
    x, y = p[0] * zi % P, p[1] * zi % P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _decode(data):
    if len(data) != 32:
        raise ValueError("a point is 32 bytes")
    y = int.from_bytes(data, "little")
    sign, y = y >> 255, y & ((1 << 255) - 1)
    x = _recover_x(y, sign)
    if x is None:
        raise ValueError("not a point on the curve")
    return (x, y, 1, x * y % P)


def _hash_int(*parts):
    return int.from_bytes(hashlib.sha512(b"".join(parts)).digest(), "little")


def _expand(seed):
    if len(seed) != 32:
        raise ValueError("an Ed25519 private key is 32 bytes")
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def public_key(seed):
    """The 32-byte public key of a 32-byte private key."""
    a, _ = _expand(seed)
    return _encode(_times(a, BASE))


def sign(seed, message):
    """The 64-byte signature of `message`."""
    a, prefix = _expand(seed)
    public = _encode(_times(a, BASE))
    r = _hash_int(prefix, message) % L
    big_r = _encode(_times(r, BASE))
    s = (r + _hash_int(big_r, public, message) % L * a) % L
    return big_r + s.to_bytes(32, "little")


def verify(public, message, signature):
    """Whether `signature` is the key's signature of `message`."""
    if len(public) != 32 or len(signature) != 64:
        return False
    try:
        a = _decode(public)
        r = _decode(signature[:32])
    except ValueError:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= L:
        return False
    h = _hash_int(signature[:32], public, message) % L
    return _same(_times(s, BASE), _add(r, _times(h, a)))


# ----- key files

def _pem(kind, der):
    body = base64.encodebytes(der).decode().replace("\n", "")
    lines = [body[i:i + 64] for i in range(0, len(body), 64)]
    return ("-----BEGIN %s-----\n%s\n-----END %s-----\n" % (kind, "\n".join(lines), kind)).encode()


def _unpem(data, kind):
    text = data.decode("ascii", "replace") if isinstance(data, bytes) else data
    begin, end = "-----BEGIN %s-----" % kind, "-----END %s-----" % kind
    if begin not in text or end not in text:
        return None
    body = text.split(begin, 1)[1].split(end, 1)[0]
    return base64.b64decode("".join(body.split()))


def new_private_key():
    """A new private key file's contents (PKCS #8 PEM)."""
    return _pem("PRIVATE KEY", PRIVATE_PREFIX + os.urandom(32))


def read_private_key(data):
    """The 32-byte private key in a PEM file's contents. Raises ValueError saying what is wrong."""
    text = data.decode("ascii", "replace") if isinstance(data, bytes) else data
    if "ENCRYPTED PRIVATE KEY" in text:
        raise ValueError("this private key is protected by a passphrase; make one without "
                         "(device/release.py keygen does)")
    if "OPENSSH PRIVATE KEY" in text:
        raise ValueError("this is an SSH key, not an update key; make one with device/release.py keygen")
    der = _unpem(text, "PRIVATE KEY")
    if der is None:
        raise ValueError("this is not a private key file (no 'BEGIN PRIVATE KEY')")
    if len(der) == 48 and der[:16] == PRIVATE_PREFIX:
        return der[16:]
    # Version 2, which some tools write, has the public key after the private one.
    if len(der) == 83 and der[:16] == PRIVATE_PREFIX_V2:
        return der[16:48]
    raise ValueError("this private key is not an Ed25519 key")


def public_pem(public):
    """A public key file's contents (SubjectPublicKeyInfo PEM)."""
    return _pem("PUBLIC KEY", PUBLIC_PREFIX + public)


def read_public_key(data):
    """The 32-byte public key in a PEM file's contents. Raises ValueError saying what is wrong."""
    der = _unpem(data, "PUBLIC KEY")
    if der is None or len(der) != 44 or der[:12] != PUBLIC_PREFIX:
        raise ValueError("this is not an Ed25519 public key file")
    return der[12:]


def fingerprint(public):
    """A short name for a public key, to tell keys apart without opening them."""
    digest = hashlib.sha256(public).hexdigest()[:16].upper()
    return " ".join(digest[i:i + 4] for i in range(0, 16, 4))
