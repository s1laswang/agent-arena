import contextlib
import ctypes
import json
import os
import tempfile

_MEM = {}


def get_secret(name, default=""):
    ev = os.environ.get(name)
    if ev is not None:
        return ev
    if name in _MEM and _MEM[name] is not None:
        return _MEM[name]
    return default


get = get_secret


def set_secret(**kw):
    for k, v in kw.items():
        if v is None:
            _MEM.pop(k, None)
        else:
            _MEM[k] = str(v)


def clear_secrets():
    _MEM.clear()


@contextlib.contextmanager
def scoped_secrets(**kw):
    prev = dict(_MEM)
    try:
        set_secret(**kw)
        yield
    finally:
        _MEM.clear()
        _MEM.update(prev)


def write_secrets_file(data, dir=None):
    payload = {str(k): str(v) for k, v in data.items() if v is not None}
    fd, path = tempfile.mkstemp(
        prefix="sleeper-secrets-",
        suffix=".json",
        dir=os.fspath(dir) if dir is not None else None,
    )
    try:
        os.fchmod(fd, 0o600)
    except OSError:
        pass
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return path


def load_secrets_file(path=None, unlink=None):
    p = path or os.environ.get("SLEEPER_SECRETS_FILE")
    if not p:
        return {}
    if not os.path.isfile(p):
        raise FileNotFoundError(f"secrets file not found: {p}")
    with open(p, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    if not isinstance(raw, dict):
        raise ValueError(f"secrets file must contain a JSON object: {p}")
    out = {str(k): str(v) for k, v in raw.items() if v is not None}
    do_unlink = (
        unlink
        if unlink is not None
        else (os.environ.get("SLEEPER_SECRETS_UNLINK", "").lower() in ("1", "true", "yes"))
    )
    if do_unlink:
        try:
            os.unlink(p)
        except OSError:
            pass
    return out


def _wipe_initial_environ(names):
    wipe = set(names)
    ptrs = []
    try:
        libc = ctypes.CDLL(None)
        env = ctypes.POINTER(ctypes.c_void_p).in_dll(libc, "environ")
        if env:
            i = 0
            while env[i]:
                s = ctypes.string_at(env[i])
                if s.partition(b"=")[0].decode(errors="ignore") in wipe:
                    ptrs.append((env[i], len(s)))
                i += 1
    except Exception:
        ptrs = []
    for k in wipe:
        os.environ.pop(k, None)
    for ptr, length in ptrs:
        if ptr and length > 0:
            try:
                ctypes.memset(ptr, 0, length)
            except Exception:
                pass


def _not_dumpable():
    try:
        ctypes.CDLL(None).prctl(4, 0, 0, 0, 0)
    except Exception:
        pass


def take(*names, secrets_file=None, unlink=None, not_dumpable=True):
    file_vals = load_secrets_file(secrets_file, unlink=unlink)
    vals = {}
    for n in names:
        ev = os.environ.get(n)
        vals[n] = ev if ev not in (None, "") else file_vals.get(n, ev)
    wipe = set(names) | {"SLEEPER_SECRETS_FILE", "SLEEPER_SECRETS_UNLINK"}
    _wipe_initial_environ(wipe)
    if not_dumpable:
        _not_dumpable()
    for n, v in vals.items():
        if v is not None:
            _MEM[n] = str(v)
        else:
            _MEM.pop(n, None)
    return vals
