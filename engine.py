"""Engine of the SatNav Voice pack creator: stock export, pack storage, build, install."""
import csv
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import uuid
import wave
import zipfile
from pathlib import Path

import numpy as np

import fsb5

APP_NAME = 'SatNav Voice pack creator'
APP_VERSION = '1.0.2'
GAME_FOLDER_NAME = 'Anthem_1.0.0.64_x64__8wekyb3d8bbwe'
BANK_REL = Path('Mount') / 'media' / 'audio' / 'fmodanthem' / 'durango'
BANK_PATTERN = re.compile(r'^HZ2_DX_SatNav_([A-Z]{2})\.bank$')
ALLOWED_EXT = ('.mp3', '.wav', '.ogg')
SHARED_LINE = 'HZ2_VO_ANNA_SatNav_Imperial_Destination_Default_1'
BUILD_REV = 1  # bump when the conversion changes, so old builds count as outdated

RATES = {9: 48000, 8: 44100, 7: 32000, 6: 24000, 5: 22050, 4: 16000}
LEAD_MS = 30
TAIL_MS = 120
FADE_MS = 40
MAX_PAUSE_MS = 700

LANG_NAMES = {
    'EN': 'English', 'PL': 'Polish', 'DE': 'German', 'FR': 'French', 'ES': 'Spanish',
    'IT': 'Italian', 'JP': 'Japanese', 'BR': 'Portuguese (Brazil)', 'MX': 'Spanish (Mexico)',
    'RU': 'Russian',
}

NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def frozen():
    return getattr(sys, 'frozen', False)


def app_dir():
    return Path(sys.executable).parent if frozen() else Path(__file__).resolve().parent


def resource_dir():
    base = Path(getattr(sys, '_MEIPASS', '')) if frozen() else Path(__file__).resolve().parent
    return base / 'resources'


def data_dir():
    override = os.environ.get('SATNAV_TOOL_DATA')
    return Path(override) if override else app_dir() / 'data'


class Paths:
    def __init__(self):
        self.data = data_dir()
        self.stock = self.data / 'stock'
        self.packs = self.data / 'packs'
        self.sources = self.data / 'sources'
        self.previews = self.data / 'cache' / 'preview'
        self.builds = self.data / 'builds'
        self.settings = self.data / 'settings.json'

    def make(self):
        for p in (self.stock, self.packs, self.sources, self.previews, self.builds):
            p.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------- settings

def load_settings(paths):
    try:
        return json.loads(paths.settings.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def save_settings(paths, settings):
    paths.data.mkdir(parents=True, exist_ok=True)
    paths.settings.write_text(json.dumps(settings, indent=2), encoding='utf-8')


def validate_game_dir(path):
    """Return an error text, or None when `path` is the Forza Horizon 2 game folder."""
    if not path:
        return 'Choose the game folder.'
    p = Path(path)
    if p.name.lower() != GAME_FOLDER_NAME.lower():
        return 'The folder must be named "%s".' % GAME_FOLDER_NAME
    if not p.is_dir():
        return 'The folder does not exist.'
    if not (p / 'Mount').is_dir():
        return 'The "Mount" folder was not found inside the game folder.'
    if not (p / BANK_REL).is_dir():
        return 'The SatNav banks were not found in Mount\\media\\audio\\fmodanthem\\durango.'
    return None


def validate_mods_dir(path):
    if not path:
        return 'Choose the fh2-mods folder.'
    p = Path(path)
    if p.name.lower() != 'fh2-mods':
        return 'The folder must be named "fh2-mods".'
    if not p.is_dir():
        return 'The folder does not exist.'
    return None


def game_languages(game_dir):
    langs = []
    try:
        for f in sorted(Path(game_dir, BANK_REL).iterdir()):
            m = BANK_PATTERN.match(f.name)
            if m:
                langs.append(m.group(1))
    except OSError:
        pass
    return langs


def lang_label(lang):
    return '%s - %s' % (lang, LANG_NAMES[lang]) if lang in LANG_NAMES else lang


def game_running():
    try:
        out = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq azimuth.exe', '/NH'],
                             stdout=subprocess.PIPE, creationflags=NO_WINDOW).stdout
        return b'azimuth.exe' in out.lower()
    except OSError:
        return False


# ---------------------------------------------------------------- loader

def loader_info():
    try:
        info = json.loads((resource_dir() / 'loader.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        info = {}
    return info.get('name', 'SatNavVoice.dll'), info.get('version', '?')


# ---------------------------------------------------------------- audio

def ffmpeg_path():
    bundled = resource_dir() / 'ffmpeg.exe'
    if bundled.is_file():
        return str(bundled)
    found = shutil.which('ffmpeg')
    if found:
        return found
    raise RuntimeError('ffmpeg was not found.')


def decode(args, data=None):
    """Run ffmpeg and return mono 16-bit PCM."""
    cmd = [ffmpeg_path(), '-v', 'error'] + args + ['-f', 's16le', '-ac', '1', 'pipe:1']
    p = subprocess.run(cmd, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       creationflags=NO_WINDOW)
    if p.returncode != 0:
        raise RuntimeError('ffmpeg failed: ' + p.stderr.decode(errors='replace').strip()[-300:])
    return p.stdout


def to_float(pcm):
    return np.frombuffer(pcm, dtype='<i2').astype(np.float64)


def active_rms(a):
    """RMS over the speech only, so silence padding does not skew the level."""
    if len(a) == 0:
        return 0.0
    peak = np.max(np.abs(a))
    if peak <= 0:
        return 0.0
    speech = a[np.abs(a) > peak * 0.03]
    return float(np.sqrt(np.mean(speech * speech))) if len(speech) else 0.0


def trim(a, rate):
    """Cut silence from both ends, keeping a short lead/tail, and fade out."""
    if len(a) == 0:
        return a
    peak = np.max(np.abs(a))
    idx = np.nonzero(np.abs(a) > peak * 0.02)[0]
    if len(idx) == 0:
        return a
    # Some clips say the phrase twice with a long pause; keep the first part only.
    gaps = np.nonzero(np.diff(idx) > rate * MAX_PAUSE_MS // 1000)[0]
    if len(gaps):
        idx = idx[:gaps[0] + 1]
    lead = rate * LEAD_MS // 1000
    tail = rate * TAIL_MS // 1000
    a = a[max(0, idx[0] - lead):min(len(a), idx[-1] + 1 + tail)].copy()
    fade = min(len(a), rate * FADE_MS // 1000)
    a[-fade:] *= np.linspace(1.0, 0.0, fade)
    return a


def match_level(a, target_rms):
    r = active_rms(a)
    if r <= 0 or target_rms <= 0:
        return a
    gain = target_rms / r
    peak = np.max(np.abs(a)) * gain
    if peak > 30000:
        gain *= 30000 / peak
    return a * gain


def to_pcm(a):
    return np.clip(np.round(a), -32768, 32767).astype('<i2').tobytes()


def write_wav(path, pcm, rate):
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


def read_wav(path):
    with wave.open(str(path), 'rb') as w:
        if w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise RuntimeError('%s is not mono 16-bit' % Path(path).name)
        return w.readframes(w.getnframes()), w.getframerate()


# ---------------------------------------------------------------- stock banks

def line_category(name):
    if re.search(r'_Imperial_', name, re.I):
        return 'imperial'
    if re.search(r'_Metric_', name, re.I):
        return 'metric'
    if re.search(r'_Various_', name, re.I):
        return 'various'
    return 'other'


class Engine:
    def __init__(self):
        self.paths = Paths()
        self.paths.make()
        self.settings = load_settings(self.paths)
        self.packs = []

    # ---- settings
    @property
    def game_dir(self):
        return self.settings.get('game_dir', '')

    @property
    def mods_dir(self):
        return self.settings.get('mods_dir', '')

    def settings_valid(self):
        return validate_game_dir(self.game_dir) is None and validate_mods_dir(self.mods_dir) is None

    def set_dirs(self, game_dir, mods_dir):
        self.settings['game_dir'] = game_dir
        self.settings['mods_dir'] = mods_dir
        save_settings(self.paths, self.settings)

    # ---- stock
    def stock_dir(self, lang):
        return self.paths.stock / lang

    def stock_loaded(self, lang):
        d = self.stock_dir(lang)
        return (d / 'list.csv').is_file() and (d / 'stock.bank').is_file()

    def loaded_languages(self):
        return sorted(d.name for d in self.paths.stock.iterdir()
                      if d.is_dir() and BANK_PATTERN.match('HZ2_DX_SatNav_%s.bank' % d.name)
                      and self.stock_loaded(d.name))

    def stock_lines(self, lang):
        rows = []
        with open(self.stock_dir(lang) / 'list.csv', newline='', encoding='utf-8') as fh:
            for r in csv.DictReader(fh):
                rows.append({'index': int(r['#']), 'name': r['bank name'], 'file': r['file'],
                             'rate': int(r['sample rate']), 'seconds': float(r['seconds'])})
        return rows

    def stock_wav(self, lang, line):
        return self.stock_dir(lang) / line['file']

    def export_stock(self, lang, progress):
        """Decode the game's SatNav bank for `lang` to WAVs, a CSV list and a bank copy."""
        game_bank = Path(self.game_dir, BANK_REL, 'HZ2_DX_SatNav_%s.bank' % lang)
        if not game_bank.is_file():
            raise RuntimeError('%s was not found in the game folder.' % game_bank.name)
        bank = game_bank.read_bytes()
        _, _, fsb, _ = fsb5.split_bank(bank)
        parsed = fsb5.parse_fsb(fsb)
        if parsed['mode'] != 10:
            raise RuntimeError('Unexpected bank format (expected XMA).')
        samples, data = parsed['samples'], parsed['data']
        tmp = self.paths.stock / (lang + '.tmp')
        if tmp.exists():
            shutil.rmtree(tmp)
        tmp.mkdir(parents=True)
        rows = []
        try:
            for i, s in enumerate(samples):
                progress(i / len(samples), 'Decoding %d / %d: %s' % (i + 1, len(samples), s['name']))
                a = s['off']
                e = samples[i + 1]['off'] if i + 1 < len(samples) else len(data)
                rate = RATES[s['freq']]
                wav = fsb5.xma2_wav(data[a:e], rate, s['ns'], e - a)
                pcm = decode(['-i', 'pipe:0'], wav)
                name = '%03d_%s.wav' % (i + 1, re.sub(r'[^\w.\-]+', '_', s['name']))
                write_wav(tmp / name, pcm, rate)
                rows.append((i + 1, s['name'], name, rate, round(len(pcm) / 2 / rate, 2)))
            with open(tmp / 'list.csv', 'w', newline='', encoding='utf-8') as f:
                w = csv.writer(f)
                w.writerow(['#', 'bank name', 'file', 'sample rate', 'seconds'])
                w.writerows(rows)
            (tmp / 'stock.bank').write_bytes(bank)
            final = self.stock_dir(lang)
            if final.exists():
                shutil.rmtree(final)
            tmp.rename(final)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        progress(1.0, 'Done')
        return len(rows)

    def delete_stock(self, lang):
        shutil.rmtree(self.stock_dir(lang), ignore_errors=True)

    # ---- packs
    def load_packs(self):
        self.packs = []
        for f in sorted(self.paths.packs.glob('*.svpack')):
            try:
                self.packs.append(self._read_pack(f))
            except Exception:
                continue
        return self.packs

    def _read_pack(self, path):
        with zipfile.ZipFile(path) as z:
            meta = json.loads(z.read('pack.json'))
            for entry in set(v['file'] for v in meta['lines'].values()):
                dst = self.paths.sources / entry
                if not dst.exists():
                    dst.write_bytes(z.read('sources/' + entry))
        return Pack(meta['id'], meta['name'], meta['language'], meta.get('lines', {}),
                    meta.get('created'))

    def new_pack(self, name, lang):
        pack = Pack(uuid.uuid4().hex[:12], name, lang, {}, time.strftime('%Y-%m-%d %H:%M:%S'))
        self.packs.append(pack)
        self.save_pack(pack)
        return pack

    def pack_file(self, pack):
        return self.paths.packs / (pack.id + '.svpack')

    def _project_files(self, pack):
        return sorted(set(v['file'] for v in pack.lines.values()))

    def save_pack(self, pack, path=None):
        path = Path(path) if path else self.pack_file(pack)
        tmp = path.with_suffix('.tmp')
        with zipfile.ZipFile(tmp, 'w') as z:
            z.writestr('pack.json', pack.to_json(), compress_type=zipfile.ZIP_DEFLATED)
            for entry in self._project_files(pack):
                z.write(self.paths.sources / entry, 'sources/' + entry,
                        compress_type=zipfile.ZIP_STORED)  # already compressed audio
        os.replace(tmp, path)
        pack.dirty = False

    def delete_pack(self, pack):
        self.packs.remove(pack)
        self.pack_file(pack).unlink(missing_ok=True)
        shutil.rmtree(self.paths.builds / pack.id, ignore_errors=True)
        used = set()
        for p in self.packs:
            used.update(self._project_files(p))
        for f in self.paths.sources.iterdir():
            if f.name not in used:
                f.unlink(missing_ok=True)
                (self.paths.previews / (f.stem + '.wav')).unlink(missing_ok=True)

    def attach(self, pack, bank_name, src):
        src = Path(src)
        ext = src.suffix.lower()
        if ext not in ALLOWED_EXT:
            raise ValueError('Only .mp3, .wav and .ogg files are accepted.')
        digest = hashlib.sha1(src.read_bytes()).hexdigest()[:16]
        dst = self.paths.sources / (digest + ext)
        if not dst.exists():
            shutil.copyfile(src, dst)
        try:
            pcm = decode(['-i', str(dst), '-ar', '48000'])
        except RuntimeError:
            if not any(v['file'] == dst.name for p in self.packs for v in p.lines.values()):
                dst.unlink(missing_ok=True)
            raise ValueError('This file could not be read as audio.')
        if len(pcm) < 200:
            raise ValueError('This file contains no audio.')
        write_wav(self.paths.previews / (digest + '.wav'), pcm, 48000)
        seconds = len(trim(to_float(pcm), 48000)) / 48000
        pack.lines[bank_name] = {'file': dst.name, 'orig': src.name, 'dur': round(seconds, 2)}
        pack.dirty = True

    def detach(self, pack, bank_name):
        if pack.lines.pop(bank_name, None) is not None:
            pack.dirty = True

    def preview_wav(self, entry):
        """A 48 kHz mono WAV of an attached file, ready for winsound."""
        stem = Path(entry['file']).stem
        wav = self.paths.previews / (stem + '.wav')
        if not wav.exists():
            pcm = decode(['-i', str(self.paths.sources / entry['file']), '-ar', '48000'])
            write_wav(wav, pcm, 48000)
        return wav

    # ---- build
    def build_dir(self, pack):
        return self.paths.builds / pack.id

    def bank_name(self, pack):
        return 'HZ2_DX_SatNav_%s.bank' % pack.language

    def built_bank(self, pack):
        return self.build_dir(pack) / 'package' / 'fh2-mods' / 'SatNav' / self.bank_name(pack)

    def build_state(self, pack):
        """'none', 'outdated' or 'current'."""
        info = self.build_dir(pack) / 'build.json'
        if not info.is_file() or not self.built_bank(pack).is_file():
            return 'none'
        try:
            built = json.loads(info.read_text(encoding='utf-8')).get('hash')
        except (OSError, ValueError):
            return 'none'
        return 'current' if built == pack.mapping_hash() else 'outdated'

    def build_pack(self, pack, progress):
        lang = pack.language
        if not self.stock_loaded(lang):
            raise RuntimeError('The stock %s bank is not loaded.' % lang)
        stock = {l['name']: l for l in self.stock_lines(lang)}
        bank = (self.stock_dir(lang) / 'stock.bank').read_bytes()
        pos, start, fsb, tail = fsb5.split_bank(bank)
        parsed = fsb5.parse_fsb(fsb)
        samples = parsed['samples']
        progress(0.0, 'Stock %s bank: %d samples; %d lines replaced by custom files' % (lang, len(samples), len(pack.lines)))

        cache = {}
        pcm = []
        replaced = 0
        longer = []
        for i, s in enumerate(samples):
            progress(i / len(samples), 'Converting %d / %d: %s' % (i + 1, len(samples), s['name']))
            line = stock[s['name']]
            original, rate = read_wav(self.stock_wav(lang, line))
            result = original
            entry = pack.lines.get(s['name'])
            if entry:
                key = (entry['file'], rate)
                if key not in cache:
                    raw = decode(['-i', str(self.paths.sources / entry['file']), '-ar', str(rate)])
                    cache[key] = trim(to_float(raw), rate)
                new = match_level(cache[key], active_rms(to_float(original)))
                result = to_pcm(new)
                note = 'padded with silence to stock length'
                # Shorter than stock: pad with silence so the stock length is kept.
                if len(result) < len(original):
                    result += bytes(len(original) - len(result))
                else:
                    longer.append((s['name'], len(result) / 2 / rate, len(original) / 2 / rate))
                    note = 'LONGER than stock'
                progress(i / len(samples), '    %s: trimmed + level-matched, %.2f s (stock %.2f s), %s' % (
                    entry['orig'], len(to_pcm(new)) / 2 / rate, len(original) / 2 / rate, note))
                replaced += 1
            # Even sample counts keep the sample-count field's low bit clear of the offset field.
            if not entry:
                progress(i / len(samples), '    keeping the original game sound')
            if (len(result) // 2) % 2:
                result += bytes(2)
            pcm.append(result)

        progress(0.97, 'Writing the bank')
        out_bank = fsb5.join_bank(bank, pos, start, fsb5.build_pcm_fsb(parsed, pcm), tail)

        out = self.build_dir(pack)
        shutil.rmtree(out, ignore_errors=True)
        mods = out / 'package' / 'fh2-mods'
        (mods / 'SatNav').mkdir(parents=True)
        (mods / 'SatNav' / self.bank_name(pack)).write_bytes(out_bank)
        shutil.copyfile(resource_dir() / 'SatNavVoice.dll', mods / 'SatNavVoice.dll')
        (mods / 'SatNavVoice.ini').write_bytes(b'[SatNavVoice]\r\nCustomVoice=1\r\n')
        (out / 'package' / 'README.txt').write_text(self.package_readme(pack, replaced, len(samples)),
                                                    encoding='utf-8')
        (out / 'build.json').write_text(json.dumps({
            'hash': pack.mapping_hash(), 'time': time.strftime('%Y-%m-%d %H:%M:%S'),
            'replaced': replaced, 'total': len(samples),
            'longer': [n for n, _, _ in longer]}), encoding='utf-8')
        progress(1.0, 'Done: %d replaced, %d original, %d longer than stock' % (replaced, len(samples) - replaced, len(longer)))
        return {'replaced': replaced, 'total': len(samples), 'longer': longer}

    def package_readme(self, pack, replaced, total):
        name, version = loader_info()
        return (
            '%s - %s\r\n\r\n'
            'SatNav Voice pack for the %s SatNav bank (%s), made with %s %s.\r\n'
            '%d of %d lines are replaced; the others keep the stock game voice.\r\n\r\n'
            'Requirements\r\n'
            '- Forza Horizon 2 (PC, 1.0.0.64 x64) with the FH2 Mod Platform v2.7.1 or newer.\r\n'
            '- Game speech language set to %s.\r\n\r\n'
            'Install\r\n'
            'Copy the contents of the "fh2-mods" folder into the game\'s "fh2-mods" folder '
            '(%s v%s, SatNavVoice.ini and SatNav\\%s).\r\n'
            'The option "SatNavVoice" is under Pause > Settings > Mods (a restart is needed after '
            'changing it).\r\n'
            % (pack.name, lang_label(pack.language), pack.language, self.bank_name(pack),
               APP_NAME, APP_VERSION, replaced, total, LANG_NAMES.get(pack.language, pack.language),
               name, version, self.bank_name(pack)))

    # ---- install
    def installed_bank(self, pack):
        return Path(self.mods_dir, 'SatNav', self.bank_name(pack))

    def install_state(self, pack):
        """'none', 'different' or 'installed' (the installed bank is this pack's current build)."""
        dst = self.installed_bank(pack)
        if not dst.is_file():
            return 'none'
        src = self.built_bank(pack)
        if self.build_state(pack) == 'current' and src.is_file() \
                and src.stat().st_size == dst.stat().st_size:
            return 'installed'
        return 'different'

    def install_pack(self, pack):
        if self.build_state(pack) != 'current':
            raise RuntimeError('The pack has to be built first.')
        mods = Path(self.mods_dir)
        pkg = self.build_dir(pack) / 'package' / 'fh2-mods'
        try:
            (mods / 'SatNav').mkdir(exist_ok=True)
            shutil.copyfile(pkg / 'SatNavVoice.dll', mods / 'SatNavVoice.dll')
            if not (mods / 'SatNavVoice.ini').exists():
                shutil.copyfile(pkg / 'SatNavVoice.ini', mods / 'SatNavVoice.ini')
            shutil.copyfile(self.built_bank(pack), self.installed_bank(pack))
        except PermissionError:
            raise RuntimeError('A file in fh2-mods is in use. Close the game and try again.')

    # ---- export / import
    def export_pack(self, pack, zip_path):
        if self.build_state(pack) != 'current':
            raise RuntimeError('The pack has to be built first.')
        pkg = self.build_dir(pack) / 'package'
        with zipfile.ZipFile(zip_path, 'w') as z:
            for f in sorted(pkg.rglob('*')):
                if f.is_file():
                    z.write(f, f.relative_to(pkg).as_posix(), compress_type=zipfile.ZIP_DEFLATED)
            z.writestr('project/pack.json', pack.to_json(), compress_type=zipfile.ZIP_DEFLATED)
            for entry in self._project_files(pack):
                z.write(self.paths.sources / entry, 'project/sources/' + entry,
                        compress_type=zipfile.ZIP_STORED)

    def import_zip(self, zip_path, progress):
        """Import a pack exported by this tool, or any package holding a rebuilt SatNav bank."""
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
            base = Path(zip_path).stem
            if 'project/pack.json' in names:
                meta = json.loads(z.read('project/pack.json'))
                for entry in set(v['file'] for v in meta['lines'].values()):
                    dst = self.paths.sources / entry
                    if not dst.exists():
                        dst.write_bytes(z.read('project/sources/' + entry))
                pack = Pack(uuid.uuid4().hex[:12], meta['name'], meta['language'],
                            meta.get('lines', {}), time.strftime('%Y-%m-%d %H:%M:%S'))
                self.packs.append(pack)
                self.save_pack(pack)
                return pack
            bank_entry = None
            for n in names:
                m = BANK_PATTERN.match(Path(n).name)
                if m:
                    bank_entry, lang = n, m.group(1)
                    break
            if not bank_entry:
                raise ValueError('The archive contains neither a pack project nor a SatNav bank.')
            if not self.stock_loaded(lang):
                raise NeedStock(lang)
            bank = z.read(bank_entry)
        _, _, fsb, _ = fsb5.split_bank(bank)
        parsed = fsb5.parse_fsb(fsb)
        if parsed['mode'] != 2:
            raise ValueError('This bank is not a custom voice bank (it matches the stock format).')
        stock = {l['name']: l for l in self.stock_lines(lang)}
        pack = Pack(uuid.uuid4().hex[:12], base, lang, {}, time.strftime('%Y-%m-%d %H:%M:%S'))
        tmp = self.paths.data / 'cache' / 'import'
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        samples, data = parsed['samples'], parsed['data']
        try:
            for i, s in enumerate(samples):
                progress(i / len(samples), 'Reading %d / %d: %s' % (i + 1, len(samples), s['name']))
                line = stock.get(s['name'])
                if not line:
                    continue
                new = data[s['off']:s['off'] + s['ns'] * 2]
                original, _ = read_wav(self.stock_wav(lang, line))
                if new != original:
                    f = tmp / ('%03d.wav' % line['index'])
                    write_wav(f, new, RATES[s['freq']])
                    self.attach(pack, s['name'], f)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.packs.append(pack)
        self.save_pack(pack)
        return pack


class NeedStock(Exception):
    def __init__(self, lang):
        super().__init__(lang)
        self.lang = lang


class Pack:
    def __init__(self, pack_id, name, language, lines=None, created=None):
        self.id = pack_id
        self.name = name
        self.language = language
        self.lines = lines or {}
        self.created = created
        self.dirty = False

    def to_json(self):
        return json.dumps({'format': 1, 'id': self.id, 'name': self.name, 'language': self.language,
                           'created': self.created, 'lines': self.lines}, indent=1)

    def mapping_hash(self):
        payload = json.dumps([BUILD_REV, self.language,
                              sorted((n, v['file']) for n, v in self.lines.items())])
        return hashlib.sha1(payload.encode()).hexdigest()
