"""Exercise real HTTP handlers, SQL constraints, migration and persistence."""
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app import ENGINE, create_app


class APITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.url = 'sqlite:///' + (Path(self.temp.name) / 'test.db').as_posix()
        self.client = TestClient(TestServer(create_app(self.url)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.temp.cleanup()

    async def call(self, method, path, status=200, **kwargs):
        result = await self.client.request(method, path, **kwargs)
        payload = await result.json()
        self.assertEqual(result.status, status, payload)
        if status >= 400:
            self.assertIsInstance(payload['error'], str)
        return payload

    async def course(self):
        return await self.call('POST', '/api/courses', 201, json={'name': 'Web'})

    async def quest(self, course_id=None):
        return await self.call('POST', '/api/quests', 201,
                               json={'title': 'API', 'subject': 'Web', 'course_id': course_id})

    async def test_related_crud_and_delete_conflicts(self):
        course = await self.course()
        quest = await self.call('POST', f'/api/courses/{course["id"]}/quests', 201,
                                json={'title': 'API', 'subject': 'Web'})
        step = await self.call('POST', f'/api/quests/{quest["id"]}/steps', 201, json={'title': 'Test'})
        self.assertEqual(quest['course_id'], course['id'])
        self.assertEqual(step['quest_id'], quest['id'])
        for resource, entity, child, expected in [('courses', course, 'quests', quest), ('quests', quest, 'steps', step)]:
            related = await self.call('GET', f'/api/{resource}/{entity["id"]}/{child}')
            self.assertEqual(related[child], [expected])
            await self.call('DELETE', f'/api/{resource}/{entity["id"]}', 409)
        for resource, entity, values in [('courses', course, {'name': 'REST'}), ('quests', quest, {'completed': True}), ('steps', step, {'completed': True})]:
            updated = await self.call('PATCH', f'/api/{resource}/{entity["id"]}', json=values)
            self.assertEqual(updated['created_at'], entity['created_at'])
            for key, value in values.items():
                self.assertEqual(updated[key], value)
            self.assertEqual(await self.call('GET', f'/api/{resource}/{entity["id"]}'), updated)
        for resource, entity in [('steps', step), ('quests', quest), ('courses', course)]:
            await self.call('DELETE', f'/api/{resource}/{entity["id"]}')
            await self.call('GET', f'/api/{resource}/{entity["id"]}', 404)
            await self.call('DELETE', f'/api/{resource}/{entity["id"]}', 404)

    async def test_validation_and_protocol_errors(self):
        quest = await self.quest()
        for payload in ([], {}, {'title': 'x'}, {'title': ' ', 'subject': 'Web'},
                        {'title': 'x'*121, 'subject': 'Web'}, {'title': 'x', 'subject': 'Web', 'completed': 1},
                        {'title': 'x', 'subject': 'Web', 'course_id': True},
                        {'title': 'x', 'subject': 'Web', 'course_id': 9223372036854775807},
                        {'title': 'x', 'subject': 'Web', 'created_at': 'now'}):
            await self.call('POST', '/api/quests', 400, json=payload)
        for payload in ({}, {'completed': 'true'}, {'other': 1}, {'id': 1}):
            await self.call('PATCH', f'/api/quests/{quest["id"]}', 400, json=payload)
        await self.call('POST', '/api/quests', 400, data='{bad', headers={'Content-Type': 'application/json'})
        await self.call('POST', '/api/quests', 400, data='{}')
        await self.call('POST', '/api/courses', 413, json={'name': 'x'*9000})
        for identifier in ('0', '-1', 'abc', '9223372036854775808', '１'):
            await self.call('GET', '/api/quests/' + identifier, 400)
        await self.call('GET', '/api/courses/9223372036854775807/quests', 404)
        await self.call('GET', '/api/quests?x=1', 400)
        await self.call('PUT', f'/api/quests/{quest["id"]}', 405, json={})
        await self.call('GET', '/unknown', 404)

    async def test_reassignment_and_relationship_isolation(self):
        first, second = await self.course(), await self.course()
        quest = await self.quest(first['id'])
        await self.call('PATCH', f'/api/quests/{quest["id"]}', json={'course_id': second['id']})
        self.assertEqual((await self.call('GET', f'/api/courses/{first["id"]}/quests'))['quests'], [])
        self.assertEqual((await self.call('GET', f'/api/courses/{second["id"]}/quests'))['quests'][0]['id'], quest['id'])
        await self.call('PATCH', f'/api/quests/{quest["id"]}', json={'course_id': None})
        await self.call('POST', f'/api/courses/{first["id"]}/quests', 400, json={'title': 'x', 'subject': 'x', 'course_id': first['id']})
        await self.call('POST', '/api/steps', 400, json={'title': 'x', 'quest_id': 9223372036854775807})

    async def test_foreign_keys_enforced_in_database(self):
        course = await self.course()
        await self.quest(course['id'])
        with self.assertRaises(IntegrityError):
            with self.client.app[ENGINE].begin() as connection:
                connection.execute(text('DELETE FROM courses WHERE id=:id'), {'id': course['id']})
        with self.assertRaises(IntegrityError):
            with self.client.app[ENGINE].begin() as connection:
                connection.execute(text("INSERT INTO steps (quest_id,title) VALUES (999999,'invalid')"))

    async def test_persistence_after_app_restart(self):
        course = await self.course()
        quest = await self.quest(course['id'])
        step = await self.call('POST', '/api/steps', 201, json={'quest_id': quest['id'], 'title': 'Keep me'})
        await self.client.close()
        self.client = TestClient(TestServer(create_app(self.url)))
        await self.client.start_server()
        for resource, entity in [('courses', course), ('quests', quest), ('steps', step)]:
            self.assertEqual(await self.call('GET', f'/api/{resource}/{entity["id"]}'), entity)

    async def test_legacy_database_migration_and_page(self):
        await self.client.close()
        legacy = Path(self.temp.name) / 'legacy.db'
        with closing(sqlite3.connect(legacy)) as connection:
            connection.execute('CREATE TABLE quests (id INTEGER PRIMARY KEY, title VARCHAR(120) NOT NULL, subject VARCHAR(60) NOT NULL, completed BOOLEAN NOT NULL DEFAULT FALSE, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)')
            connection.execute("INSERT INTO quests(title,subject) VALUES ('Original goal','Docker')")
            connection.commit()
        self.client = TestClient(TestServer(create_app('sqlite:///' + legacy.as_posix())))
        await self.client.start_server()
        quest = await self.call('GET', '/api/quests/1')
        self.assertEqual(quest['title'], 'Original goal')
        self.assertIsNone(quest['course_id'])
        course = await self.course()
        await self.call('PATCH', '/api/quests/1', json={'course_id': course['id']})
        page = await self.client.get('/')
        self.assertIn('quest-form', await page.text())
        await self.call('GET', '/health')
        await self.call('GET', '/api/info')


if __name__ == '__main__':
    unittest.main()
