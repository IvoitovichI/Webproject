"""Generate the portable Postman v2.1 contract and local environment."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
items = []


def add(name, method, path, status=200, body=None, checks=(), raw=None, content_type='application/json', html=False):
    scripts = [f"pm.test('HTTP {status}', () => pm.response.to.have.status({status}));"]
    if not html:
        scripts.append('const apiResponse = pm.response.json();')
    if status >= 400:
        scripts.append("pm.test('JSON error', () => pm.expect(apiResponse.error).to.be.a('string').and.not.empty);")
    scripts.extend(checks)
    request = {'method': method, 'header': [], 'url': '{{baseUrl}}' + path,
               'description': f'{method} {path}; expected HTTP {status}. See API.md for field constraints and response schemas.'}
    if body is not None or raw is not None:
        request['header'] = [{'key': 'Content-Type', 'value': content_type}]
        request['body'] = {'mode': 'raw', 'raw': raw if raw is not None else json.dumps(body),
                           'options': {'raw': {'language': 'json'}}}
    items.append({'name': name, 'request': request,
                  'event': [{'listen': 'test', 'script': {'type': 'text/javascript', 'exec': scripts}}]})


add('Browser page', 'GET', '/', html=True, checks=["pm.test('HTML study form', () => { pm.expect(pm.response.headers.get('Content-Type')).to.include('text/html'); pm.expect(pm.response.text()).to.include('quest-form'); });"])
add('Database health', 'GET', '/health', checks=["pm.test('Database connected', () => pm.expect(apiResponse.database).to.equal('connected'));"])
add('Application info', 'GET', '/api/info', checks=["pm.test('Application name', () => pm.expect(apiResponse.app).to.be.a('string').and.not.empty);"])
add('Existing demonstration route', 'GET', '/Test', checks=["pm.test('Demo response', () => pm.expect(apiResponse.title).to.equal('New page'));"])
for resource in ('courses', 'quests', 'steps'):
    add('List ' + resource, 'GET', '/api/' + resource, checks=[f"pm.test('List envelope', () => pm.expect(apiResponse.{resource}).to.be.an('array'));"])

def save(key):
    return [f"pm.collectionVariables.set('{key}', apiResponse.id);",
            "pm.test('Generated ID and timestamp', () => { pm.expect(apiResponse.id).to.be.a('number').above(0); pm.expect(Number.isNaN(Date.parse(apiResponse.created_at))).to.equal(false); });",
            "pm.test('Location', () => pm.expect(pm.response.headers.get('Location')).to.match(new RegExp('/'+apiResponse.id+'$')));"]


add('Create course', 'POST', '/api/courses', 201, {'name': 'Postman course', 'description': 'Temporary API test'}, save('courseId'))
add('Read course', 'GET', '/api/courses/{{courseId}}', checks=["pm.test('Saved name', () => pm.expect(apiResponse.name).to.equal('Postman course'));"])
add('Update course', 'PATCH', '/api/courses/{{courseId}}', body={'name': 'REST APIs'}, checks=["pm.test('Partial update preserves description', () => { pm.expect(apiResponse.name).to.equal('REST APIs'); pm.expect(apiResponse.description).to.equal('Temporary API test'); });"])
add('Course starts empty', 'GET', '/api/courses/{{courseId}}/quests', checks=["pm.test('No quests yet', () => pm.expect(apiResponse.quests).to.eql([]));"])
add('Create related quest', 'POST', '/api/courses/{{courseId}}/quests', 201, {'title': 'Build API', 'subject': 'Web'}, save('questId') + ["pm.test('Course relationship', () => pm.expect(apiResponse.course_id).to.equal(Number(pm.collectionVariables.get('courseId'))));"])
add('Read quest', 'GET', '/api/quests/{{questId}}', checks=["pm.test('Initially incomplete', () => pm.expect(apiResponse.completed).to.equal(false));", "pm.collectionVariables.set('questCreatedAt', apiResponse.created_at);"])
add('Update quest', 'PATCH', '/api/quests/{{questId}}', body={'completed': True}, checks=["pm.test('Partial update persisted', () => { pm.expect(apiResponse.completed).to.equal(true); pm.expect(apiResponse.title).to.equal('Build API'); pm.expect(apiResponse.created_at).to.equal(pm.collectionVariables.get('questCreatedAt')); });"])
add('List course quests', 'GET', '/api/courses/{{courseId}}/quests', checks=["pm.test('Exact relationship', () => pm.expect(apiResponse.quests.map(q=>q.id)).to.eql([Number(pm.collectionVariables.get('questId'))]));"])
add('Create step through quest', 'POST', '/api/quests/{{questId}}/steps', 201, {'title': 'Document endpoints'}, save('stepId') + ["pm.test('Quest relationship', () => pm.expect(apiResponse.quest_id).to.equal(Number(pm.collectionVariables.get('questId'))));"])
add('Read step', 'GET', '/api/steps/{{stepId}}', checks=["pm.test('Saved title', () => pm.expect(apiResponse.title).to.equal('Document endpoints'));"])
add('Update step', 'PATCH', '/api/steps/{{stepId}}', body={'completed': True}, checks=["pm.test('Step completion', () => { pm.expect(apiResponse.completed).to.equal(true); pm.expect(apiResponse.title).to.equal('Document endpoints'); });"])
add('List quest steps', 'GET', '/api/quests/{{questId}}/steps', checks=["pm.test('Exact step relationship', () => pm.expect(apiResponse.steps.map(s=>s.id)).to.eql([Number(pm.collectionVariables.get('stepId'))]));"])
add('Create standalone quest with reference', 'POST', '/api/quests', 201, raw='{"title":"Second quest","subject":"Web","course_id":{{courseId}}}', checks=save('secondQuestId'))
add('Create standalone step with reference', 'POST', '/api/steps', 201, raw='{"title":"Second step","quest_id":{{secondQuestId}}}', checks=save('secondStepId'))
add('Prevent deleting nonempty course', 'DELETE', '/api/courses/{{courseId}}', 409)
add('Prevent deleting nonempty quest', 'DELETE', '/api/quests/{{questId}}', 409)
for name, method, path, value in [
    ('Blank course name', 'POST', '/api/courses', {'name': ' '}),
    ('Long course name', 'POST', '/api/courses', {'name': 'x'*121}),
    ('Missing subject', 'POST', '/api/quests', {'title': 'Missing'}),
    ('Invalid boolean', 'PATCH', '/api/quests/{{questId}}', {'completed': 'true'}),
    ('Unknown field', 'PATCH', '/api/steps/{{stepId}}', {'unknown': 1}),
    ('Empty update', 'PATCH', '/api/courses/{{courseId}}', {}),
    ('Read-only timestamp', 'PATCH', '/api/quests/{{questId}}', {'created_at': '2000-01-01'}),
    ('Missing course reference', 'POST', '/api/quests', {'title': 'Invalid', 'subject': 'Web', 'course_id': 9223372036854775807}),
    ('Missing quest reference', 'POST', '/api/steps', {'title': 'Invalid', 'quest_id': 9223372036854775807}),
    ('Boolean reference', 'POST', '/api/steps', {'title': 'Invalid', 'quest_id': True}),
    ('Nested reference supplied by URL', 'POST', '/api/quests/{{questId}}/steps', {'title': 'Invalid', 'quest_id': 1}),
    ('Array body', 'POST', '/api/courses', []),
]:
    add(name, method, path, 400, value)
add('Malformed JSON', 'POST', '/api/courses', 400, raw='{broken')
add('Wrong content type', 'POST', '/api/courses', 400, raw='{}', content_type='text/plain')
add('Oversized JSON', 'POST', '/api/courses', 413, {'name': 'x'*9000})
for identifier in ('0', '-1', 'abc', '9223372036854775808'):
    add('Invalid identifier ' + identifier, 'GET', '/api/quests/' + identifier, 400)
add('Missing resource', 'GET', '/api/courses/9223372036854775807', 404)
add('Missing related parent', 'GET', '/api/quests/9223372036854775807/steps', 404)
add('Unsupported query', 'GET', '/api/quests?unknown=1', 400)
add('Unsupported method', 'PUT', '/api/courses/{{courseId}}', 405, {})
add('Unknown route', 'GET', '/api/unknown', 404)
for resource, key in [('steps', 'stepId'), ('steps', 'secondStepId'), ('quests', 'questId'), ('quests', 'secondQuestId'), ('courses', 'courseId')]:
    add('Delete temporary ' + key, 'DELETE', '/api/' + resource + '/{{' + key + '}}', checks=[f"pm.test('Deleted ID', () => pm.expect(apiResponse.id).to.equal(Number(pm.collectionVariables.get('{key}'))));"])
    add('Confirm deletion of ' + key, 'GET', '/api/' + resource + '/{{' + key + '}}', 404)
add('Repeat deletion', 'DELETE', '/api/courses/{{courseId}}', 404)

collection = {'info': {'name': 'Study Quest REST API',
    'description': 'Run all requests in order. Covers every endpoint and negative cases. Creates temporary course/quests/steps and deletes them in dependency order. Existing data is preserved. See API.md.',
    'schema': 'https://schema.getpostman.com/json/collection/v2.1.0/collection.json'},
    'variable': [{'key': 'baseUrl', 'value': 'http://localhost:8080'}], 'item': items}
(HERE / 'StudyQuest.postman_collection.json').write_text(json.dumps(collection, indent=2) + '\n', encoding='utf-8')
(HERE / 'StudyQuest.local.postman_environment.json').write_text(json.dumps({
    'name': 'Study Quest - Local', '_postman_variable_scope': 'environment',
    'values': [{'key': 'baseUrl', 'value': 'http://localhost:8080', 'enabled': True}],
}, indent=2) + '\n', encoding='utf-8')
print(f'Generated {len(items)} requests')
