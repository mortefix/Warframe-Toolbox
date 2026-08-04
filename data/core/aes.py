"""AES-128 decryption in pure Python - no third-party package, no OS calls.

This replaces a ctypes binding to Windows' CNG (bcrypt.dll). The DLL was only
ever supplying the AES primitive, and being a Windows system binary it pinned
the app to Windows for no benefit; see core/arcane_inv.py for the one caller.

Decrypt-only on purpose. Nothing here protects a secret - the single key in
the codebase is AlecaFrame's published constant - so there is no encrypt path
to get wrong and no key material to handle carefully.

Implementation note: this uses the T-table form of the inverse cipher, where
InvSubBytes/InvShiftRows/InvMixColumns for a whole column collapse into four
table lookups and four XORs. The obvious byte-at-a-time implementation is
roughly 20x slower, which matters because the one caller feeds it 1.3 MB
(83k blocks). Measured here: ~1.5 MB/s, about 850 ms for that file - fine
behind arcane_inv's mtime-gated cache, but do not call it on a UI thread.

Verified against the FIPS-197 C.1 known-answer vector and, on real data,
byte-identical over all 1,328,720 bytes to the bcrypt.dll code it replaces.
"""

from __future__ import annotations


def _build():
    """Derive the S-box and T-tables from the GF(2^8) field rather than
    pasting 1,280 hex literals nobody can review. Runs once at import
    (~2 ms) and self-checks against published S-box entries."""
    exp, log = [0] * 256, [0] * 256
    x = 1
    for i in range(255):                    # 3 is a generator of GF(2^8)*
        exp[i] = x
        log[x] = i
        x ^= ((x << 1) ^ 0x1b) & 0xff if x & 0x80 else (x << 1)

    def mul(a, b):
        return 0 if a == 0 or b == 0 else exp[(log[a] + log[b]) % 255]

    def rotl8(b, n):
        return ((b << n) | (b >> (8 - n))) & 0xff

    sbox = [0] * 256
    for a in range(256):
        # the % 255 is load-bearing: log[1] is 0, so without it inv(1) reads
        # exp[255], which the loop above never fills. That one wrong entry
        # collides sbox[0] with sbox[1] and corrupts about one byte in 256 -
        # subtle enough to survive a CBC self-consistency check, which is
        # exactly how it was caught here (only the FIPS vector saw it).
        inv = 0 if a == 0 else exp[(255 - log[a]) % 255]
        sbox[a] = (inv ^ rotl8(inv, 1) ^ rotl8(inv, 2) ^ rotl8(inv, 3)
                   ^ rotl8(inv, 4) ^ 0x63)
    if (sbox[0x00], sbox[0x01], sbox[0x53], sbox[0xff]) != (0x63, 0x7c,
                                                            0xed, 0x16):
        raise RuntimeError("AES S-box generation is wrong")

    isbox = [0] * 256
    for a, s in enumerate(sbox):
        isbox[s] = a
    if sorted(isbox) != list(range(256)):
        raise RuntimeError("AES inverse S-box is not a permutation")

    # Td0[x] = Si[x] . [0e 09 0d 0b]; Td1..Td3 are byte rotations of it
    td0 = [(mul(isbox[x], 14) << 24) | (mul(isbox[x], 9) << 16)
           | (mul(isbox[x], 13) << 8) | mul(isbox[x], 11) for x in range(256)]

    def ror(w, n):
        return ((w >> n) | (w << (32 - n))) & 0xffffffff

    return (sbox, mul, td0, [ror(w, 8) for w in td0],
            [ror(w, 16) for w in td0], [ror(w, 24) for w in td0],
            [s * 0x01010101 for s in isbox])


_SBOX, _MUL, _TD0, _TD1, _TD2, _TD3, _TD4 = _build()
_RCON = (0x01000000, 0x02000000, 0x04000000, 0x08000000, 0x10000000,
         0x20000000, 0x40000000, 0x80000000, 0x1b000000, 0x36000000)

BLOCK = 16


def _expand(key: bytes) -> list[int]:
    """Forward AES-128 key schedule - 11 round keys of four 32-bit words."""
    w = [int.from_bytes(key[i:i + 4], "big") for i in range(0, 16, 4)]
    for i in range(4, 44):
        t = w[i - 1]
        if i % 4 == 0:                      # RotWord + SubWord + Rcon
            t = ((_SBOX[(t >> 16) & 0xff] << 24)
                 | (_SBOX[(t >> 8) & 0xff] << 16)
                 | (_SBOX[t & 0xff] << 8)
                 | _SBOX[(t >> 24) & 0xff]) ^ _RCON[i // 4 - 1]
        w.append(w[i - 4] ^ t)
    return w


def _inv_mix(w: int) -> int:
    a0, a1 = (w >> 24) & 0xff, (w >> 16) & 0xff
    a2, a3 = (w >> 8) & 0xff, w & 0xff
    m = _MUL
    return (((m(a0, 14) ^ m(a1, 11) ^ m(a2, 13) ^ m(a3, 9)) << 24)
            | ((m(a0, 9) ^ m(a1, 14) ^ m(a2, 11) ^ m(a3, 13)) << 16)
            | ((m(a0, 13) ^ m(a1, 9) ^ m(a2, 14) ^ m(a3, 11)) << 8)
            | (m(a0, 11) ^ m(a1, 13) ^ m(a2, 9) ^ m(a3, 14)))


def _decrypt_schedule(key: bytes) -> list[int]:
    """Equivalent-inverse-cipher schedule: reverse the round-key order, then
    push InvMixColumns through every middle round so the decrypt loop has the
    same shape as encryption and can use the T-tables."""
    w = _expand(key)
    rk = [word for r in range(10, -1, -1) for word in w[r * 4:r * 4 + 4]]
    for i in range(4, 40):                  # all but the first and last round
        rk[i] = _inv_mix(rk[i])
    return rk


def decrypt_cbc(data: bytes, key: bytes, iv: bytes) -> bytes:
    """AES-128-CBC decrypt. Any padding is left in place - callers strip it,
    because the padding scheme belongs to whoever wrote the file."""
    if len(key) != 16:
        raise ValueError("AES-128 needs a 16-byte key")
    if len(iv) != BLOCK:
        raise ValueError("IV must be one block")
    if len(data) % BLOCK:
        raise ValueError("ciphertext is not a whole number of blocks")

    rk = _decrypt_schedule(key)
    # Bind every hot name to a local. Global and attribute lookups dominate
    # the inner loop otherwise, and it runs 83k times on the real input.
    td0, td1, td2, td3, td4 = _TD0, _TD1, _TD2, _TD3, _TD4
    rk0, rk1, rk2, rk3 = rk[0], rk[1], rk[2], rk[3]
    rkA, rkB, rkC, rkD = rk[40], rk[41], rk[42], rk[43]
    frm, pack = int.from_bytes, int.to_bytes
    mv = memoryview(data)
    out = bytearray(len(data))

    p_a, p_b = frm(iv[0:4], "big"), frm(iv[4:8], "big")
    p_c, p_d = frm(iv[8:12], "big"), frm(iv[12:16], "big")

    for off in range(0, len(data), BLOCK):
        c0 = frm(mv[off:off + 4], "big")
        c1 = frm(mv[off + 4:off + 8], "big")
        c2 = frm(mv[off + 8:off + 12], "big")
        c3 = frm(mv[off + 12:off + 16], "big")
        s0, s1, s2, s3 = c0 ^ rk0, c1 ^ rk1, c2 ^ rk2, c3 ^ rk3

        k = 4
        for _ in range(9):                  # rounds 1..9
            t0 = (td0[s0 >> 24] ^ td1[(s3 >> 16) & 0xff]
                  ^ td2[(s2 >> 8) & 0xff] ^ td3[s1 & 0xff] ^ rk[k])
            t1 = (td0[s1 >> 24] ^ td1[(s0 >> 16) & 0xff]
                  ^ td2[(s3 >> 8) & 0xff] ^ td3[s2 & 0xff] ^ rk[k + 1])
            t2 = (td0[s2 >> 24] ^ td1[(s1 >> 16) & 0xff]
                  ^ td2[(s0 >> 8) & 0xff] ^ td3[s3 & 0xff] ^ rk[k + 2])
            t3 = (td0[s3 >> 24] ^ td1[(s2 >> 16) & 0xff]
                  ^ td2[(s1 >> 8) & 0xff] ^ td3[s0 & 0xff] ^ rk[k + 3])
            s0, s1, s2, s3 = t0, t1, t2, t3
            k += 4

        # last round is InvSubBytes + InvShiftRows only, no InvMixColumns,
        # so it reads the plain inverse S-box (broadcast into Td4)
        out[off:off + BLOCK] = (
            pack(((td4[s0 >> 24] & 0xff000000)
                  ^ (td4[(s3 >> 16) & 0xff] & 0xff0000)
                  ^ (td4[(s2 >> 8) & 0xff] & 0xff00)
                  ^ (td4[s1 & 0xff] & 0xff) ^ rkA) ^ p_a, 4, "big")
            + pack(((td4[s1 >> 24] & 0xff000000)
                    ^ (td4[(s0 >> 16) & 0xff] & 0xff0000)
                    ^ (td4[(s3 >> 8) & 0xff] & 0xff00)
                    ^ (td4[s2 & 0xff] & 0xff) ^ rkB) ^ p_b, 4, "big")
            + pack(((td4[s2 >> 24] & 0xff000000)
                    ^ (td4[(s1 >> 16) & 0xff] & 0xff0000)
                    ^ (td4[(s0 >> 8) & 0xff] & 0xff00)
                    ^ (td4[s3 & 0xff] & 0xff) ^ rkC) ^ p_c, 4, "big")
            + pack(((td4[s3 >> 24] & 0xff000000)
                    ^ (td4[(s2 >> 16) & 0xff] & 0xff0000)
                    ^ (td4[(s1 >> 8) & 0xff] & 0xff00)
                    ^ (td4[s0 & 0xff] & 0xff) ^ rkD) ^ p_d, 4, "big"))
        p_a, p_b, p_c, p_d = c0, c1, c2, c3

    return bytes(out)


def decrypt_block_ecb(block: bytes, key: bytes) -> bytes:
    """A single ECB block. CBC with an all-zero IV is exactly ECB for one
    block, so this is a naming convenience, not a second implementation."""
    return decrypt_cbc(block, key, b"\0" * BLOCK)


def strip_pkcs7(data: bytes) -> bytes:
    """Remove PKCS#7 padding if it is present and self-consistent. Returns
    the input untouched otherwise - a foreign file's trailer is not something
    to raise over."""
    if not data:
        return data
    n = data[-1]
    if 1 <= n <= BLOCK and len(data) >= n and data[-n:] == bytes([n]) * n:
        return data[:-n]
    return data
