"""Minimal FMOD FEV bank / FSB5 helpers for the SatNav bank (XMA in, PCM16 out)."""
import struct

MODE_PCM16 = 2


def split_bank(bank):
    """Return (snd_chunk_pos, preamble_len, fsb, tail).

    The FEV bank is RIFF; the FSB5 sample container is inside the 'SND ' chunk.
    """
    pos = 12
    while pos < len(bank):
        tag = bank[pos:pos + 4]
        size = struct.unpack_from('<I', bank, pos + 4)[0]
        if tag == b'SND ':
            body = bank[pos + 8:pos + 8 + size]
            start = body.index(b'FSB5')
            return pos, start, body[start:], bank[pos + 8 + size:]
        pos += 8 + size
    raise ValueError('no SND chunk in bank')


def join_bank(bank, pos, start, fsb, tail):
    head = bytearray(bank[:pos + 8 + start])
    struct.pack_into('<I', head, pos + 4, start + len(fsb))
    out = bytearray(bytes(head) + fsb + tail)
    # The SNDH header records the FSB size; the game limits sample reads to it.
    sndh = out.index(b'SNDH', 0, pos)
    struct.pack_into('<I', out, sndh + 16, len(fsb))
    struct.pack_into('<I', out, 4, len(out) - 8)
    return bytes(out)


def parse_fsb(fsb):
    ver, n, shs, nts, ds, mode = struct.unpack_from('<6I', fsb, 4)
    base = 60
    samples = []
    p = base
    for _ in range(n):
        v = struct.unpack_from('<Q', fsb, p)[0]
        p += 8
        nxt = v & 1
        s = {'freq': (v >> 1) & 0xF, 'ch': ((v >> 5) & 3) + 1,
             'off': ((v >> 7) & 0x7FFFFFF) * 32, 'ns': v >> 34, 'chunks': []}
        while nxt:
            c = struct.unpack_from('<I', fsb, p)[0]
            p += 4
            nxt = c & 1
            size = (c >> 1) & 0xFFFFFF
            s['chunks'].append((c >> 25, fsb[p:p + size]))
            p += size
        samples.append(s)
    if p - base != shs:
        raise ValueError('sample header size mismatch')
    nt = base + shs
    name_offs = struct.unpack_from('<%dI' % n, fsb, nt)
    data = fsb[nt + nts:nt + nts + ds]
    for i, s in enumerate(samples):
        e = fsb.index(b'\0', nt + name_offs[i])
        s['name'] = fsb[nt + name_offs[i]:e].decode()
        s['end'] = samples[i + 1]['off'] if i + 1 < n else ds
    return {'ver': ver, 'mode': mode, 'samples': samples, 'data': data,
            'header': fsb[:base]}


def build_pcm_fsb(parsed, pcm_by_index):
    """Build an FSB5 where every sample is mono PCM16 at its original rate."""
    samples = parsed['samples']
    n = len(samples)
    heads = bytearray()
    blob = bytearray()
    for i, s in enumerate(samples):
        pcm = pcm_by_index[i]
        while len(blob) % 32:
            blob.append(0)
        off = len(blob)
        blob += pcm
        ns = len(pcm) // 2
        heads += struct.pack('<Q', (s['freq'] << 1) | ((off // 32) << 7) | (ns << 34))
    while len(blob) % 32:
        blob.append(0)
    names = bytearray()
    offs = []
    for s in samples:
        offs.append(n * 4 + len(names))
        names += s['name'].encode() + b'\0'
    while len(names) % 4:
        names.append(0)
    nametable = struct.pack('<%dI' % n, *offs) + bytes(names)
    hdr = bytearray(parsed['header'])
    struct.pack_into('<6I', hdr, 4, 1, n, len(heads), len(nametable), len(blob), MODE_PCM16)
    return bytes(hdr) + bytes(heads) + nametable + bytes(blob)


def xma2_wav(sample_data, freq, num_samples, block=2048):
    """Wrap raw XMA2 blocks in a RIFF/WAVE container ffmpeg can decode."""
    blocks = len(sample_data) // block
    extra = struct.pack('<HIIIIIIIBBH', 1, 4, num_samples, block, 0, num_samples,
                        0, 0, 0, 4, blocks)
    fmt = struct.pack('<HHIIHHH', 0x166, 1, freq, freq * 2, block, 16, len(extra)) + extra
    body = b'WAVE' + b'fmt ' + struct.pack('<I', len(fmt)) + fmt
    body += b'data' + struct.pack('<I', len(sample_data)) + sample_data
    return b'RIFF' + struct.pack('<I', len(body)) + body
