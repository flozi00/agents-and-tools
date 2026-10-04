#!/usr/bin/env node
// This catalog helper is self-contained when the Hub is checked out separately.
import { existsSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export const HUB = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const object = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const truthy = (value) =>
	Array.isArray(value)
		? value.length > 0
		: object(value)
			? Object.keys(value).length > 0
			: Boolean(value);
const strip = (value) =>
	value.replace(
		/^[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+|[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/g,
		''
	);
function compare(left, right) {
	const a = Array.from(left, (char) => char.codePointAt(0));
	const b = Array.from(right, (char) => char.codePointAt(0));
	for (let index = 0; index < Math.min(a.length, b.length); index++)
		if (a[index] !== b[index]) return a[index] - b[index];
	return a.length - b.length;
}
function file(path) {
	return existsSync(path) && statSync(path).isFile();
}
function readJson(path) {
	return JSON.parse(readFileSync(path, 'utf8'));
}
export function directories(root, name) {
	const directory = join(root, name);
	if (!existsSync(directory) || !statSync(directory).isDirectory()) return [];
	return readdirSync(directory)
		.filter((entry) => statSync(join(directory, entry)).isDirectory())
		.sort(compare);
}
function toolId(id) {
	const identifier = /^[_\p{ID_Start}][_\p{ID_Continue}]*$/u;
	return identifier.test(id) && identifier.test(id.normalize('NFKC')) && id === id.toLowerCase();
}
function frontmatter(content) {
	const match = /^\s*("""|''')([\s\S]*?)\1/.exec(content);
	if (!match) return {};
	const result = {};
	for (const line of match[2].split(/\r\n?|\n/))
		if (line.includes(':')) {
			const colon = line.indexOf(':');
			Object.defineProperty(result, strip(line.slice(0, colon)), {
				value: strip(line.slice(colon + 1)),
				enumerable: true,
				writable: true,
				configurable: true
			});
		}
	return result;
}
export function readTool(root, id) {
	if (!toolId(id)) throw new Error(`tool id "${id}" must be a lowercase Python identifier`);
	const base = join(root, 'tools', id);
	const python = join(base, 'tool.py');
	const native = join(base, 'tool.json');
	if (file(python) && file(native))
		throw new Error(`tools/${id} has ambiguous Python and native sources`);
	if (file(native)) {
		const manifest = readJson(native);
		if (
			!object(manifest) ||
			Object.keys(manifest).sort().join(',') !== 'runtime,tool,version' ||
			manifest.runtime !== 'primeline-native' ||
			manifest.version !== 1 ||
			typeof manifest.tool !== 'string' ||
			!toolId(manifest.tool)
		)
			throw new Error(`tools/${id}/tool.json has an unsupported native manifest`);
		const metadata = readJson(join(base, 'metadata.json'));
		if (!object(metadata)) throw new Error(`tools/${id}/metadata.json must contain an object`);
		return {
			id,
			content: readFileSync(native, 'utf8'),
			frontmatter: metadata,
			format: 'primeline-native'
		};
	}
	if (!file(python)) throw new Error(`tools/${id}/tool.py or tool.json is missing`);
	const content = readFileSync(python, 'utf8');
	return { id, content, frontmatter: frontmatter(content), format: 'python' };
}
export function generateIndex(root = HUB) {
	const tools = directories(root, 'tools').map((id) => {
		const record = readTool(root, id);
		const metadata = record.frontmatter;
		if (!truthy(metadata.version)) throw new Error(`tools/${id} metadata needs a version`);
		const entry = {
			id,
			name: truthy(metadata.title) ? metadata.title : id,
			description: truthy(metadata.description) ? metadata.description : '',
			version: metadata.version
		};
		if (truthy(metadata.requirements)) entry.requirements = metadata.requirements;
		if (record.format === 'primeline-native') entry.format = record.format;
		return entry;
	});
	const known = new Set(tools.map((tool) => tool.id));
	const assistants = directories(root, 'assistants').map((id) => {
		if (!/^[a-z0-9][a-z0-9-]{0,63}$/.test(id))
			throw new Error(`assistant id "${id}" must be lowercase kebab-case`);
		const path = join(root, 'assistants', id, 'assistant.json');
		if (!file(path)) throw new Error(`assistants/${id}/assistant.json is missing`);
		const template = readJson(path);
		if (!object(template) || template.id !== id)
			throw new Error(`assistants/${id}: "id" must equal the directory name`);
		for (const key of ['name', 'version', 'description', 'system_prompt'])
			if (!truthy(template[key])) throw new Error(`assistants/${id}: "${key}" is required`);
		for (const key of ['base_model_id', 'access_grants', 'access_control', 'knowledgeBaseIds'])
			if (Object.hasOwn(template, key))
				throw new Error(`assistants/${id}: "${key}" is not portable and not allowed in templates`);
		const dependencies = Object.hasOwn(template, 'tools') ? template.tools : [];
		if (!Array.isArray(dependencies)) throw new Error(`assistants/${id}: tools must be an array`);
		for (const dependency of dependencies)
			if (!known.has(dependency))
				throw new Error(`assistants/${id}: references unknown hub tool "${dependency}"`);
		const entry = {
			id,
			name: template.name,
			description: template.description,
			version: template.version,
			tools: dependencies
		};
		if (truthy(template.profile_image_url)) entry.profile_image_url = template.profile_image_url;
		return entry;
	});
	const index = { version: 1, assistants, tools };
	writeFileSync(join(root, 'index.json'), JSON.stringify(index, null, 2) + '\n', 'utf8');
	return index;
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
	try {
		if (process.argv.length !== 2) throw new Error('usage: node scripts/generate_index.mjs');
		const index = generateIndex();
		console.log(
			`index.json written: ${index.assistants.length} assistants, ${index.tools.length} tools`
		);
	} catch (error) {
		console.error(`error: ${error.message}`);
		process.exitCode = 1;
	}
}
