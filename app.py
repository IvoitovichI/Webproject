"""Study Quest REST API: aiohttp, SQLAlchemy and PostgreSQL/SQLite."""
import asyncio
import json
import logging
import os
import socket
from datetime import datetime, timezone
from pathlib import Path

from aiohttp import web
from sqlalchemy import (BigInteger, Boolean, CheckConstraint, Column, DateTime,
                        ForeignKey, Identity, Integer, MetaData, String, Table,
                        create_engine, event, inspect, select, text)
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

BASE = Path(__file__).resolve().parent
metadata = MetaData()


def identity():
    return Column('id', BigInteger().with_variant(Integer, 'sqlite'), Identity(), primary_key=True)


def timestamp():
    return Column('created_at', DateTime(timezone=True), nullable=False,
                  server_default=text('CURRENT_TIMESTAMP'))


courses = Table('courses', metadata, identity(),
                Column('name', String(120), nullable=False),
                Column('description', String(1000), nullable=False, server_default=''),
                timestamp(), CheckConstraint('length(trim(name)) BETWEEN 1 AND 120'),
                CheckConstraint('length(description) <= 1000'))
quests = Table('quests', metadata, identity(),
               Column('title', String(120), nullable=False),
               Column('subject', String(60), nullable=False),
               Column('completed', Boolean, nullable=False, server_default=text('false')),
               Column('course_id', BigInteger, ForeignKey('courses.id', ondelete='RESTRICT'), index=True),
               timestamp(), CheckConstraint('length(trim(title)) BETWEEN 1 AND 120'),
               CheckConstraint('length(trim(subject)) BETWEEN 1 AND 60'))
steps = Table('steps', metadata, identity(),
              Column('quest_id', BigInteger, ForeignKey('quests.id', ondelete='RESTRICT'), nullable=False, index=True),
              Column('title', String(120), nullable=False),
              Column('completed', Boolean, nullable=False, server_default=text('false')),
              timestamp(), CheckConstraint('length(trim(title)) BETWEEN 1 AND 120'))
TABLES = {'courses': courses, 'quests': quests, 'steps': steps}
FIELDS = {
    'courses': {'name': ('text', 120), 'description': ('description', 1000)},
    'quests': {'title': ('text', 120), 'subject': ('text', 60),
               'completed': ('bool', None), 'course_id': ('nullable_id', None)},
    'steps': {'quest_id': ('id', None), 'title': ('text', 120), 'completed': ('bool', None)},
}
REQUIRED = {'courses': {'name'}, 'quests': {'title', 'subject'}, 'steps': {'quest_id', 'title'}}
ENGINE = web.AppKey('engine', object)


class APIError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def valid_id(value):
    if type(value) is not int or not 1 <= value <= 9223372036854775807:
        raise APIError(400, 'IDs must be positive 64-bit integers')
    return value


def path_id(value):
    if not value.isascii() or not value.isdigit() or len(value) > 19:
        raise APIError(400, 'IDs must be positive 64-bit integers')
    return valid_id(int(value))


def validate(resource, payload, partial=False):
    if not isinstance(payload, dict):
        raise APIError(400, 'JSON body must be an object')
    rules = FIELDS[resource]
    if set(payload) - rules.keys():
        raise APIError(400, 'Unknown or read-only fields: ' + ', '.join(sorted(set(payload) - rules.keys())))
    if not partial and REQUIRED[resource] - payload.keys():
        raise APIError(400, 'Missing required fields: ' + ', '.join(sorted(REQUIRED[resource] - payload.keys())))
    if partial and not payload:
        raise APIError(400, 'PATCH must contain at least one editable field')
    result = {}
    for name, value in payload.items():
        kind, limit = rules[name]
        if kind in ('text', 'description'):
            if not isinstance(value, str) or len(value.strip()) > limit or (kind == 'text' and not value.strip()):
                raise APIError(400, f'{name} must be a string with {1 if kind == "text" else 0} to {limit} characters')
            value = value.strip()
        elif kind == 'bool':
            if type(value) is not bool:
                raise APIError(400, f'{name} must be a boolean')
        elif kind != 'nullable_id' or value is not None:
            valid_id(value)
        result[name] = value
    return result


def encode(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=value.tzinfo or timezone.utc).isoformat()
    raise TypeError(f'Cannot serialize {type(value)}')


def response(payload, status=200, headers=None):
    return web.Response(text=json.dumps(payload, default=encode), status=status,
                        content_type='application/json', headers=headers)


@web.middleware
async def errors(request, handler):
    try:
        return await handler(request)
    except APIError as error:
        return response({'error': error.message}, error.status)
    except web.HTTPException as error:
        return response({'error': error.reason}, error.status,
                        {'Allow': error.headers['Allow']} if 'Allow' in error.headers else None)
    except IntegrityError:
        return response({'error': 'Relationship constraint failed; remove dependent records before deleting a parent'}, 409)
    except SQLAlchemyError:
        logging.exception('Database request failed')
        return response({'error': 'Database temporarily unavailable'}, 503)


async def body(request):
    if request.content_type != 'application/json':
        raise APIError(400, 'Content-Type must be application/json')
    try:
        return json.loads(await request.text())
    except (ValueError, UnicodeDecodeError):
        raise APIError(400, 'Malformed JSON') from None


def existing(connection, table, identifier):
    row = connection.execute(select(table).where(table.c.id == identifier)).mappings().first()
    if row is None:
        raise APIError(404, f'{table.name} record not found')
    return dict(row)


def check_references(connection, resource, values):
    for field, parent in (('course_id', courses), ('quest_id', quests)):
        if field in values and values[field] is not None:
            if connection.execute(select(parent.c.id).where(parent.c.id == values[field])).first() is None:
                raise APIError(400, f'{field} references a missing {parent.name} record')


async def crud(request):
    resource = request.match_info['resource']
    if resource not in TABLES:
        raise APIError(404, 'Not found')
    table = TABLES[resource]
    identifier = path_id(request.match_info['id']) if 'id' in request.match_info else None
    if request.query:
        raise APIError(400, 'Query parameters are not supported')
    values = validate(resource, await body(request), request.method == 'PATCH') if request.method in ('POST', 'PATCH') else None

    def execute():
        with request.app[ENGINE].begin() as connection:
            if identifier is None and request.method == 'GET':
                return response({resource: [dict(row) for row in connection.execute(select(table).order_by(table.c.id.desc())).mappings()]})
            if request.method == 'POST':
                check_references(connection, resource, values)
                row = dict(connection.execute(table.insert().values(**values).returning(table)).mappings().one())
                return response(row, 201, {'Location': f'/api/{resource}/{row["id"]}'})
            row = existing(connection, table, identifier)
            if request.method == 'GET':
                return response(row)
            if request.method == 'PATCH':
                check_references(connection, resource, values)
                row = dict(connection.execute(table.update().where(table.c.id == identifier).values(**values).returning(table)).mappings().one())
                return response(row)
            if resource == 'courses':
                children, key = quests, quests.c.course_id
            elif resource == 'quests':
                children, key = steps, steps.c.quest_id
            else:
                children, key = None, None
            if children is not None and connection.execute(select(children.c.id).where(key == identifier).limit(1)).first():
                raise APIError(409, 'Remove or reassign dependent records before deleting this record')
            connection.execute(table.delete().where(table.c.id == identifier))
            # Preserve the existing browser/API DELETE contract.
            return response(row)

    return await asyncio.to_thread(execute)


async def related(request):
    parent = request.match_info['parent']
    child = request.match_info['child']
    if (parent, child) not in (('courses', 'quests'), ('quests', 'steps')):
        raise APIError(404, 'Not found')
    identifier = path_id(request.match_info['id'])
    if request.query:
        raise APIError(400, 'Query parameters are not supported')
    field = 'course_id' if parent == 'courses' else 'quest_id'
    values = None
    if request.method == 'POST':
        payload = await body(request)
        if not isinstance(payload, dict):
            raise APIError(400, 'JSON body must be an object')
        if field in payload:
            raise APIError(400, f'{field} is supplied by the URL; omit it from the body')
        values = validate(child, {**payload, field: identifier})

    def execute():
        with request.app[ENGINE].begin() as connection:
            existing(connection, TABLES[parent], identifier)
            table = TABLES[child]
            if request.method == 'GET':
                rows = connection.execute(select(table).where(table.c[field] == identifier).order_by(table.c.id.desc())).mappings()
                return response({child: [dict(row) for row in rows]})
            row = dict(connection.execute(table.insert().values(**values).returning(table)).mappings().one())
            return response(row, 201, {'Location': f'/api/{child}/{row["id"]}'})

    return await asyncio.to_thread(execute)


async def health(request):
    def check():
        with request.app[ENGINE].connect() as connection:
            connection.execute(text('SELECT 1'))
    await asyncio.to_thread(check)
    return response({'status': 'healthy', 'database': 'connected'})


async def info(request):
    return response({'app': os.getenv('APP_NAME', 'Study Quest'),
                     'message': os.getenv('APP_MESSAGE', 'Turn study goals into completed quests.'),
                     'hostname': socket.gethostname()})


async def page(request):
    return web.FileResponse(BASE / 'index.html')


async def test_page(request):
    return response({'title': 'New page', 'message': 'I get it'})


def database_url():
    if os.getenv('DATABASE_URL'):
        return os.environ['DATABASE_URL']
    if os.getenv('DB_HOST'):
        return URL.create('postgresql+psycopg', username=os.environ['DB_USER'],
                          password=os.environ['DB_PASSWORD'], host=os.environ['DB_HOST'],
                          port=int(os.getenv('DB_PORT', '5432')), database=os.environ['DB_NAME'])
    data = BASE / 'instance'
    data.mkdir(exist_ok=True)
    return URL.create('sqlite', database=str(data / 'study_quest.db'))


def create_app(url=None):
    engine = create_engine(url if url is not None else database_url(), pool_pre_ping=True)
    if engine.dialect.name == 'sqlite':
        @event.listens_for(engine, 'connect')
        def sqlite_foreign_keys(connection, _):
            connection.execute('PRAGMA foreign_keys=ON')
    try:
        metadata.create_all(engine)
        # Add the new optional relationship without replacing legacy quests.
        if 'course_id' not in {c['name'] for c in inspect(engine).get_columns('quests')}:
            with engine.begin() as connection:
                connection.execute(text('ALTER TABLE quests ADD COLUMN course_id BIGINT REFERENCES courses(id) ON DELETE RESTRICT'))
                connection.execute(text('CREATE INDEX IF NOT EXISTS ix_quests_course_id ON quests(course_id)'))
    except Exception:
        engine.dispose()
        raise
    app = web.Application(middlewares=[errors], client_max_size=8192)
    app[ENGINE] = engine
    app.router.add_get('/', page)
    app.router.add_get('/health', health)
    app.router.add_get('/api/info', info)
    app.router.add_get('/Test', test_page)
    for resource in TABLES:
        # Fixed resource names prevent user input from selecting arbitrary tables.
        pattern = '{resource:' + resource + '}'
        app.router.add_get('/api/' + pattern, crud)
        app.router.add_post('/api/' + pattern, crud)
        for method in ('GET', 'PATCH', 'DELETE'):
            app.router.add_route(method, '/api/' + pattern + '/{id}', crud)
    for parent, child in (('courses', 'quests'), ('quests', 'steps')):
        path = '/api/{parent:' + parent + '}/{id}/{child:' + child + '}'
        app.router.add_get(path, related)
        app.router.add_post(path, related)

    async def cleanup(application):
        application[ENGINE].dispose()
    app.on_cleanup.append(cleanup)
    return app


if __name__ == '__main__':
    port = int(os.getenv('PORT', '8080'))
    if not 1 <= port <= 65535:
        raise SystemExit('PORT must be between 1 and 65535')
    web.run_app(create_app(), host=os.getenv('HOST', '0.0.0.0'), port=port)
