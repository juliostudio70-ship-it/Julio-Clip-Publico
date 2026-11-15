"""Rutas y procesos compatibles con Windows y macOS."""
import os
from pathlib import Path
import ssl
import subprocess
import sys

CA_BUNDLE = Path(__file__).resolve().parent / 'resources/certifi-cacert.pem'


def verified_tls_context():
    context = ssl.create_default_context()
    if CA_BUNDLE.is_file():
        context.load_verify_locations(cafile=str(CA_BUNDLE))
    return context

def default_data_dir(system=None, environ=None, home=None, public=False):
    system = os.name if system is None else system
    environ = os.environ if environ is None else environ
    home = Path.home() if home is None else Path(home)
    if system == 'nt':
        name = 'Julio Clip Publico' if public else 'Julio Clip'
        return Path(environ.get('LOCALAPPDATA') or home / 'AppData/Local') / name
    return home / 'Library/Application Support/Julio Clip'

def child_options():
    # Oculta solo los procesos auxiliares; el lanzador conserva su consola.
    if os.name == 'nt':
        return {'creationflags': subprocess.CREATE_NO_WINDOW}
    if sys.platform == 'darwin' and CA_BUNDLE.is_file() and not os.environ.get('SSL_CERT_FILE'):
        # yt-dlp se ejecuta en otro intérprete y necesita su propia ruta de certificados.
        return {'env': dict(os.environ, SSL_CERT_FILE=str(CA_BUNDLE))}
    return {}
