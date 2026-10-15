"""Study Quest: a PostgreSQL-backed study-goal tracker."""
import json
import os
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
from psycopg.rows import dict_row


def connect():
    return psycopg.connect(
        host=os.environ['DB_HOST'], port=os.getenv('DB_PORT', '5432'),
        dbname=os.environ['DB_NAME'], user=os.environ['DB_USER'],
        password=os.environ['DB_PASSWORD'], connect_timeout=3,
        options='-c statement_timeout=5000', row_factory=dict_row,
    )


def initialize_database():
    with connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS quests (
            id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            title VARCHAR(120) NOT NULL CHECK (length(trim(title)) > 0),
            subject VARCHAR(60) NOT NULL CHECK (length(trim(subject)) > 0),
            completed BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )''')


class RequestHandler(BaseHTTPRequestHandler):
    server_version = 'StudyQuest/2.0'

    def send_body(self, status, body, content_type):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False, default=str).encode('utf-8')
        self.send_body(status, body, 'application/json; charset=utf-8')

    def read_json(self):
        if self.headers.get_content_type() != 'application/json':
            raise ValueError('Content-Type must be application/json')
        length = int(self.headers.get('Content-Length', '0'))
        if not 1 <= length <= 8192:
            raise ValueError('JSON body must be between 1 and 8192 bytes')
        payload = json.loads(self.rfile.read(length))
        if not isinstance(payload, dict):
            raise ValueError('JSON body must be an object')
        return payload

    def handle_api(self, method):
        route = urlsplit(self.path).path
        try:
            if method == 'GET' and route == '/':
                self.send_body(200, Path('index.html').read_bytes(), 'text/html; charset=utf-8')
                return
            if method == 'GET' and route == '/api/info':
                self.send_json(200, {
                    'app': os.getenv('APP_NAME', 'Study Quest'),
                    'message': os.getenv('APP_MESSAGE', 'Turn study goals into completed quests.'),
                    'hostname': socket.gethostname(),
                })
                return
            if method == 'GET' and route == '/health':
                with connect() as db:
                    db.execute('SELECT 1')
                self.send_json(200, {'status': 'healthy', 'database': 'connected'})
                return
            if route == '/api/quests' and method == 'GET':
                with connect() as db:
                    quests = db.execute('SELECT * FROM quests ORDER BY id DESC').fetchall()
                self.send_json(200, {'quests': quests})
                return
            if route == '/api/quests' and method == 'POST':
                payload = self.read_json()
                fields = {}
                for name, limit in (('title', 120), ('subject', 60)):
                    value = payload.get(name)
                    if not isinstance(value, str) or not 1 <= len(value.strip()) <= limit:
                        raise ValueError(f'{name} must contain 1 to {limit} characters')
                    fields[name] = value.strip()
                with connect() as db:
                    quest = db.execute(
                        'INSERT INTO quests (title, subject) VALUES (%s, %s) RETURNING *',
                        (fields['title'], fields['subject']),
                    ).fetchone()
                self.send_json(201, quest)
                return
            parts = route.strip('/').split('/')
            if len(parts) == 3 and parts[:2] == ['api', 'quests'] and method == 'PATCH':
                if not parts[2].isascii() or not parts[2].isdigit() or not 1 <= int(parts[2]) <= 9223372036854775807:
                    raise ValueError('Quest id must be a positive 64-bit integer')
                payload = self.read_json()
                if type(payload.get('completed')) is not bool:
                    raise ValueError('completed must be a boolean')
                with connect() as db:
                    quest = db.execute(
                        'UPDATE quests SET completed = %s WHERE id = %s RETURNING *',
                        (payload['completed'], int(parts[2])),
                    ).fetchone()
                self.send_json(200 if quest else 404, quest or {'error': 'Quest not found'})
                return
            self.send_json(404, {'error': 'Not found'})
        except (ValueError, UnicodeDecodeError) as error:
            self.send_json(400, {'error': str(error)})
        except psycopg.Error:
            # Never expose credentials or database connection details.
            self.send_json(503, {'error': 'Database temporarily unavailable'})

    def do_GET(self):
        self.handle_api('GET')

    def do_POST(self):
        self.handle_api('POST')

    def do_PATCH(self):
        self.handle_api('PATCH')


def main():
    port = int(os.getenv('PORT', '8080'))
    if not 1 <= port <= 65535:
        raise SystemExit('PORT must be between 1 and 65535')
    try:
        initialize_database()
    except psycopg.Error:
        raise SystemExit('Database initialization failed; check configuration and readiness.') from None
    host = os.getenv('HOST', '0.0.0.0')
    server = ThreadingHTTPServer((host, port), RequestHandler)
    print(f'Listening on http://{host}:{port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
