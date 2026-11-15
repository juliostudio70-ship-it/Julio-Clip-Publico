"""Cupo de la edición pública por perfil de Windows."""
from contextlib import closing
from email.utils import parsedate_to_datetime
import http.client
import secrets
import sqlite3

WINDOW = 24 * 60 * 60
LIMIT = 2


def trusted_time():
    connection = http.client.HTTPSConnection('www.google.com', timeout=8)
    try:
        nonce = secrets.token_hex(12)
        connection.request('GET', '/generate_204?julio=' + nonce,
                           headers={'Cache-Control': 'no-cache, no-store'})
        response = connection.getresponse()
        date = response.getheader('Date')
        if response.status != 204 or not date or int(response.getheader('Age', '0')) > 0:
            raise ValueError('Respuesta horaria no válida.')
        remote = parsedate_to_datetime(date)
        if remote.tzinfo is None:
            raise ValueError('La respuesta horaria no indica una zona.')
        return int(remote.timestamp())
    except (OSError, ValueError, http.client.HTTPException) as error:
        raise ValueError('No se pudo verificar la hora en línea. Conéctate a internet y comprueba la fecha de Windows.') from error
    finally:
        connection.close()


class PublicQuota:
    def __init__(self, root, clock=trusted_time):
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / 'cupo.sqlite3'
        self.clock = clock

    def _connect(self):
        db = sqlite3.connect(self.path, isolation_level=None)
        db.execute('CREATE TABLE IF NOT EXISTS clips (name TEXT PRIMARY KEY, created INTEGER NOT NULL, mark INTEGER NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS time_floor (id INTEGER PRIMARY KEY, utc INTEGER NOT NULL)')
        return db

    def _window(self, db, now):
        previous = db.execute('SELECT utc FROM time_floor WHERE id = 1').fetchone()
        if previous:
            now = max(now, previous[0])
        db.execute('INSERT OR REPLACE INTO time_floor VALUES (1, ?)', (now,))
        db.execute('DELETE FROM clips WHERE created <= ?', (now - WINDOW,))
        return now, db.execute('SELECT mark FROM clips').fetchall()

    def status(self):
        now = self.clock()
        with closing(self._connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            _, records = self._window(db, now)
            return {'clips': LIMIT-len(records), 'watermark': not any(mark for mark, in records)}

    def reserve(self, name, watermark):
        now = self.clock()
        with closing(self._connect()) as db, db:
            db.execute('BEGIN IMMEDIATE')
            now, records = self._window(db, now)
            previous = db.execute('SELECT mark FROM clips WHERE name = ?', (name,)).fetchone()
            if previous:
                return bool(previous[0])
            if len(records) >= LIMIT:
                raise ValueError('Usaste los dos clips de las últimas 24 horas. El cupo se libera 24 horas después de cada clip.')
            applied = watermark and not any(mark for mark, in records)
            db.execute('INSERT INTO clips VALUES (?, ?, ?)', (name, now, applied))
        return applied

    def release(self, name):
        with closing(self._connect()) as db:
            db.execute('DELETE FROM clips WHERE name = ?', (name,))
