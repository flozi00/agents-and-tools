import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import test from 'node:test';
import { generateIndex } from '../scripts/generate_index.mjs';
import { checkTools } from '../scripts/check_tools.mjs';
import { addApp, appId } from '../scripts/add_app.mjs';

function fixture(t) {
	const root = mkdtempSync(join(tmpdir(), 'hub-catalog-'));
	t.after(() => rmSync(root, { recursive: true, force: true }));
	return root;
}
function write(root, file, text) {
	const path = join(root, file);
	mkdirSync(dirname(path), { recursive: true });
	writeFileSync(path, text);
}
const python =
	'"""\ntitle: Legacy tool\ndescription: Kept legacy description\nversion: 2.0\nrequirements: requests\n"""\nclass Tools: pass\n';
const native = '{"runtime":"primeline-native","version":1,"tool":"calculator"}';
const metadata = { title: 'Rechner', description: 'Exakte Rechnung', version: '1.0.1' };
function tool(root, id = 'calculator') {
	write(root, `tools/${id}/tool.json`, native);
	write(root, `tools/${id}/metadata.json`, JSON.stringify(metadata));
}

test('standalone index preserves Python metadata and adds an explicit native format', (t) => {
	const root = fixture(t);
	tool(root);
	write(root, 'tools/legacy/tool.py', python);
	write(
		root,
		'assistants/finance/assistant.json',
		JSON.stringify({
			id: 'finance',
			name: 'Finance',
			description: 'Helper',
			version: '1.0',
			system_prompt: 'Help',
			tools: ['calculator', 'legacy']
		})
	);
	const result = generateIndex(root);
	assert.deepEqual(result, {
		version: 1,
		assistants: [
			{
				id: 'finance',
				name: 'Finance',
				description: 'Helper',
				version: '1.0',
				tools: ['calculator', 'legacy']
			}
		],
		tools: [
			{
				id: 'calculator',
				name: 'Rechner',
				description: 'Exakte Rechnung',
				version: '1.0.1',
				format: 'primeline-native'
			},
			{
				id: 'legacy',
				name: 'Legacy tool',
				description: 'Kept legacy description',
				version: '2.0',
				requirements: 'requests'
			}
		],
		apps: []
	});
	assert.equal(
		readFileSync(join(root, 'index.json'), 'utf8'),
		JSON.stringify(result, null, 2) + '\n'
	);
});

test('index refuses broken source metadata and ambiguous formats without overwriting prior output', (t) => {
	for (const kind of [
		'missing-metadata',
		'missing-version',
		'extra-manifest-field',
		'unsupported-version',
		'ambiguous-source'
	]) {
		const root = fixture(t);
		tool(root);
		write(root, 'index.json', 'previous');
		if (kind === 'missing-metadata') rmSync(join(root, 'tools/calculator/metadata.json'));
		if (kind === 'missing-version') write(root, 'tools/calculator/metadata.json', '{}');
		if (kind === 'extra-manifest-field')
			write(root, 'tools/calculator/tool.json', native.slice(0, -1) + ',"command":"private"}');
		if (kind === 'unsupported-version')
			write(root, 'tools/calculator/tool.json', native.replace('"version":1', '"version":2'));
		if (kind === 'ambiguous-source') write(root, 'tools/calculator/tool.py', python);
		assert.throws(() => generateIndex(root));
		assert.equal(readFileSync(join(root, 'index.json'), 'utf8'), 'previous');
	}
});

test('index keeps assistant portability, identifier and dependency refusals', (t) => {
	for (const change of [
		{ base_model_id: 'forbidden' },
		{ access_grants: [] },
		{ knowledgeBaseIds: [] },
		{ tools: ['missing'] },
		{ id: 'other' },
		{ system_prompt: '' }
	]) {
		const root = fixture(t);
		tool(root);
		write(
			root,
			'assistants/finance/assistant.json',
			JSON.stringify({
				id: 'finance',
				name: 'Finance',
				description: 'Helper',
				version: '1',
				system_prompt: 'Help',
				tools: ['calculator'],
				...change
			})
		);
		assert.throws(() => generateIndex(root));
	}
	const root = fixture(t);
	write(root, 'tools/Bad-ID/tool.py', python);
	assert.throws(() => generateIndex(root), /identifier/);
});

test('native checker delegates actual descriptor creation for every catalog source', async (t) => {
	const root = fixture(t);
	tool(root);
	write(root, 'tools/legacy/tool.py', python);
	const calls = [];
	const result = await checkTools(root, {
		describe: async (request) => {
			calls.push(request);
			return {
				status: 200,
				body: {
					type: 'tool',
					specs: [{ name: 'run', parameters: { type: 'object', properties: {} } }]
				}
			};
		}
	});
	assert.equal(result.failures.length, 0);
	assert.equal(result.skipped.length, 0);
	assert.equal(calls.length, 2);
	assert.deepEqual(calls[0], { kind: 'tool', id: 'calculator', content: native });
	assert.equal(calls[1].content, python);
});

test('checker refuses dead host imports, failed constructors, empty specs and malformed replies', async (t) => {
	for (const reply of [
		{ status: 400, body: { detail: "No module named 'open_webui.dead'" } },
		{ status: 400, body: { detail: 'constructor failed' } },
		{ status: 200, body: { specs: [] } },
		{ status: 200, body: {} },
		null
	]) {
		const root = fixture(t);
		tool(root);
		const result = await checkTools(root, { describe: async () => reply });
		assert.equal(result.failures.length, 1);
		assert.equal(result.skipped.length, 0);
	}
});

test('checker preserves missing external-dependency notices while continuing other tools', async (t) => {
	const root = fixture(t);
	tool(root);
	write(root, 'tools/legacy/tool.py', python);
	const result = await checkTools(root, {
		describe: async (request) =>
			request.id === 'legacy'
				? { status: 400, body: { detail: "No module named 'requests'" } }
				: {
						status: 200,
						body: {
							type: 'tool',
							specs: [
								{
									name: 'calculate',
									parameters: { properties: { expression: { type: 'string' } } }
								}
							]
						}
					}
	});
	assert.equal(result.failures.length, 0);
	assert.deepEqual(result.skipped, ['legacy']);
	assert.equal(result.checked, 2);
});

const app = {
	id: 'notary',
	name: 'Notary',
	description: 'Property purchases',
	version: '1.0.0',
	category: 'Legal',
	record_types: [{ key: 'case', name: 'Case', fields: [] }],
	views: [],
	records: []
};

test('index lists apps and the apps an assistant brings along', (t) => {
	const root = fixture(t);
	write(root, 'apps/notary/app.json', JSON.stringify(app));
	write(
		root,
		'assistants/notar/assistant.json',
		JSON.stringify({
			id: 'notar',
			name: 'Notar',
			description: 'Helper',
			version: '1',
			system_prompt: 'Help',
			apps: ['notary']
		})
	);
	const result = generateIndex(root);
	assert.deepEqual(result.apps, [
		{
			id: 'notary',
			name: 'Notary',
			description: 'Property purchases',
			version: '1.0.0',
			category: 'Legal'
		}
	]);
	assert.deepEqual(result.assistants[0].apps, ['notary']);
});

test('index refuses non-portable, unnamed or mismatched apps and unknown app dependencies', (t) => {
	for (const change of [
		{ id: 'other' },
		{ version: '' },
		{ record_types: [] },
		{ access_grants: [] },
		{ source_project_id: null },
		{ exported_at: 1 }
	]) {
		const root = fixture(t);
		write(root, 'apps/notary/app.json', JSON.stringify({ ...app, ...change }));
		assert.throws(() => generateIndex(root));
	}
	const root = fixture(t);
	write(
		root,
		'assistants/notar/assistant.json',
		JSON.stringify({
			id: 'notar',
			name: 'Notar',
			description: 'Helper',
			version: '1',
			system_prompt: 'Help',
			apps: ['missing']
		})
	);
	assert.throws(() => generateIndex(root), /unknown hub app/);
});

test('add_app turns an exported app into a portable catalog entry', (t) => {
	const root = fixture(t);
	const exported = {
		...app,
		id: 'notariat_grundstückskauf',
		version: undefined,
		exported_at: 1791360000,
		source_project_id: 'p-1',
		source_project_name: 'Mine',
		access_grants: [{ principal_id: '*' }]
	};
	const written = addApp(root, exported);
	assert.equal(written.id, 'notariat-grundstuckskauf');
	assert.equal(written.version, '1.0.0');
	const stored = JSON.parse(readFileSync(join(root, 'apps', written.id, 'app.json'), 'utf8'));
	for (const key of ['exported_at', 'source_project_id', 'source_project_name', 'access_grants'])
		assert.equal(Object.hasOwn(stored, key), false, key);
	const index = JSON.parse(readFileSync(join(root, 'index.json'), 'utf8'));
	assert.deepEqual(
		index.apps.map((entry) => entry.id),
		['notariat-grundstuckskauf']
	);
	assert.equal(appId('  Ünïcode App!! '), 'unicode-app');
	assert.throws(() => addApp(root, [], {}));
	assert.throws(() => addApp(root, { ...app, id: '---' }, {}));
});
