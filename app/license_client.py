"""Valida la suscripción pública sin usar la fecha local."""
import ctypes
from ctypes import wintypes
import hashlib
import json
import math
import os
import re
import secrets
from threading import Lock
import time
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

from runtime_support import verified_tls_context

LEASE_SECONDS = 45
ACTIVATION_ERRORS = {
    'invalid_code': 'El código de activación no es válido.',
    'used_code': 'Ese código ya fue utilizado. Introduce un código nuevo.',
    'revoked_code': 'Ese código fue revocado.',
}


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def windows_protect(data, decrypt=False):
    """Vincula el secreto a la cuenta de Windows de esta instalación."""
    if os.name != 'nt':
        raise OSError('Esta edición pública requiere Windows.')
    source_bytes = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(source_bytes, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    operation = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    operation.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                          ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    operation.restype = wintypes.BOOL
    if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ctypes.WinError(ctypes.get_last_error())
    free = ctypes.WinDLL('kernel32').LocalFree
    free.argtypes = [ctypes.c_void_p]
    free.restype = ctypes.c_void_p
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        free(target.data)


def installation_seed(raw):
    if raw[:1] in (b'\x01',b'\x03'):
        return windows_protect(raw[1:], decrypt=True)
    if raw[:1] in (b'\x02',b'\x04') and len(raw) == 33:
        return raw[1:]
    raise ValueError('La instalación guardada es inválida.')


def device_token(seed):
    import winreg
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Microsoft\Cryptography',
                       access=winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
        machine, _ = winreg.QueryValueEx(key, 'MachineGuid')
    return hashlib.sha256(seed + b'JulioClip/v1/' + machine.lower().encode('ascii')).hexdigest()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class LicenseGate:
    def __init__(self, config, folder):
        if (not re.fullmatch(r'https://[a-z0-9]{20}\.supabase\.co', config.get('url', ''))
                or not config.get('key', '').startswith('sb_publishable_')):
            raise ValueError('La configuración de licencias es inválida.')
        self.config = config
        self.folder = folder
        number = config.get('whatsapp', '')
        self.whatsapp = ('https://wa.me/'+number+'?text='+quote(config.get('message', ''))) if re.fullmatch(
            r'[1-9][0-9]{7,14}', number) else ''
        self.lock = Lock()
        self.token = None
        self.result = {'state': 'inactive'}
        self.subscription_end = self.lease_end = self.next_check = 0
        self.connection_failed = False

    def installation(self):
        if self.token is None:
            self.folder.mkdir(parents=True, exist_ok=True)
            file = self.folder/'instalacion.dat'
            try:
                encrypted = file.read_bytes()
            except FileNotFoundError:
                seed = secrets.token_bytes(32)
                try:
                    encrypted = b'\x03' + windows_protect(seed)
                except OSError:
                    # Algunos perfiles administrados de Windows no disponen de DPAPI.
                    encrypted = b'\x04' + seed
                try:
                    with file.open('xb') as handle:
                        handle.write(encrypted)
                except FileExistsError:
                    encrypted = file.read_bytes()
            seed=installation_seed(encrypted)
            self.token=(hashlib.sha256(b'JulioClip/random-installation/v2/'+seed).hexdigest() if encrypted[:1] in (b'\x03',b'\x04') else device_token(seed))
        return self.token

    def rpc(self, action, **data):
        payload = json.dumps({'p_installation': self.installation(), **data}).encode('utf-8')
        request = Request(self.config['url']+'/rest/v1/rpc/julio_clip_license_'+action, payload,
                          {'apikey': self.config['key'], 'Content-Type': 'application/json'})
        opener = build_opener(NoRedirect(), HTTPSHandler(context=verified_tls_context()))
        with opener.open(request, timeout=6) as response:
            result = json.loads(response.read(4096))
        if action == 'device' and isinstance(result, dict) and result.get('ok') is True:
            return result
        if not isinstance(result, dict) or not isinstance(result.get('state'), str):
            raise ValueError('Respuesta de licencias inválida.')
        return result

    def accept(self, result, requested):
        try:
            remaining = float(result.get('remaining_seconds', 0))
        except (TypeError, ValueError):
            remaining = 0
        if not math.isfinite(remaining) or not 0 <= remaining <= 30*86400:
            raise ValueError('Vigencia de licencia inválida.')
        if result['state'] not in ('active', 'inactive', 'expired', 'revoked'):
            raise ValueError('Estado de licencia inválido.')
        self.result = result
        self.subscription_end = requested+remaining
        self.lease_end = min(self.subscription_end, requested+LEASE_SECONDS)
        self.next_check = min(self.lease_end, requested+30) if result['state'] == 'active' else requested+45
        self.connection_failed = False

    def view(self):
        now = time.monotonic()
        state = self.result['state']
        remaining = max(0, self.subscription_end-now) if state == 'active' else 0
        if state == 'active' and not remaining:
            state = 'expired'
        elif self.connection_failed and (state == 'inactive' or (state == 'active' and now >= self.lease_end)):
            state = 'offline'
        return {'state': state, 'days_remaining': math.ceil(remaining/86400) if state == 'active' else 0,
                'whatsapp': self.whatsapp, 'price': 'RD$800 por 30 días','expires_at':self.result.get('expires_at')}

    def status(self):
        with self.lock:
            now = time.monotonic()
            if now >= self.next_check:
                try:
                    self.accept(self.rpc('status'), now)
                except (OSError, ValueError):
                    self.connection_failed = True
                    self.next_check = now+10
            return self.view()

    def activate(self, code):
        if not isinstance(code, str) or not 2 <= len(code.strip()) <= 64:
            raise ValueError(ACTIVATION_ERRORS['invalid_code'])
        code = re.sub(r'^\d{3}\.\s+', '', code.strip())
        with self.lock:
            try:
                now = time.monotonic()
                response = self.rpc('activate', p_code=code)
                if response['state'] == 'active':
                    self.accept(response, now)
            except (OSError, ValueError):
                raise ValueError('No se pudo verificar la licencia con Supabase. Reintenta con conexión.') from None
            if response['state'] != 'active':
                raise ValueError(ACTIVATION_ERRORS.get(response['state'], 'No se pudo activar ese código.'))
            message = 'Tu licencia actual sigue activa. Guarda el código nuevo para cuando venza.' if (
                response.get('activation') == 'already_active') else 'Licencia activa.'
            return dict(self.view(), message=message)

    def allowed(self):
        return self.status()['state'] == 'active'
