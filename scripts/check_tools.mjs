#!/usr/bin/env node
// Delegate constructors, imports and schemas to the actual private native runtime.
import { spawnSync } from 'node:child_process';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { HUB, directories, readTool } from './generate_index.mjs';

function describe(request) {
	const result = spawnSync(
		process.env.PRIMELINE_EXEC_RUNNER_BIN || 'primeline-exec-runner',
		['--describe-tool'],
		{
			input: JSON.stringify(request),
			encoding: 'utf8',
			maxBuffer: 32 * 1024 * 1024,
			timeout: 120000
		}
	);
	if (result.error)
		throw new Error(`native descriptor runtime failed: ${result.error.code || 'unavailable'}`);
	let reply;
	try {
		reply = JSON.parse(result.stdout);
	} catch {
		throw new Error('native descriptor runtime did not return a JSON reply');
	}
	if (result.status !== 0 && reply.status < 400)
		throw new Error('native descriptor runtime exited unsuccessfully');
	return reply;
}
function specsValid(specs) {
	return (
		Array.isArray(specs) &&
		specs.length > 0 &&
		specs.every(
			(spec) =>
				spec &&
				typeof spec.name === 'string' &&
				spec.name &&
				spec.parameters &&
				typeof spec.parameters === 'object' &&
				!Array.isArray(spec.parameters) &&
				spec.parameters.properties &&
				typeof spec.parameters.properties === 'object' &&
				!Array.isArray(spec.parameters.properties)
		)
	);
}
export async function checkTools(root = HUB, { describe: inspect = describe } = {}) {
	const failures = [];
	const skipped = [];
	const messages = [];
	let checked = 0;
	for (const id of directories(root, 'tools')) {
		checked++;
		try {
			const record = readTool(root, id);
			const metadata = record.frontmatter;
			if (record.format === 'python' && record.content.split(/\r\n?|\n/, 1)[0].trim() !== '"""')
				throw new Error('file must start with a bare triple quote');
			for (const key of ['title', 'description', 'version'])
				if (!metadata[key]) throw new Error(`frontmatter is missing "${key}"`);
			const reply = await inspect({ kind: 'tool', id, content: record.content });
			if (
				!reply ||
				!Number.isInteger(reply.status) ||
				!reply.body ||
				typeof reply.body !== 'object'
			)
				throw new Error('malformed native descriptor reply');
			if (reply.status !== 200) {
				const detail =
					typeof reply.body.detail === 'string' ? reply.body.detail : 'tool descriptor failed';
				const missing = /^No module named ['"]([^'"]+)['"]$/.exec(detail);
				if (record.format === 'python' && missing && !missing[1].startsWith('open_webui')) {
					skipped.push(id);
					messages.push(`SKIP ${id.padEnd(16)} dep ${missing[1]} not installed locally`);
					continue;
				}
				throw new Error(detail);
			}
			if (reply.body.type !== 'tool' || !specsValid(reply.body.specs))
				throw new Error('Tools exposes no valid callable function specs');
			messages.push(
				`OK   ${id.padEnd(16)} v${String(metadata.version).padEnd(8)} ${reply.body.specs.length} tools  (${metadata.license || '-'})`
			);
		} catch (error) {
			failures.push({ id, error: error.message });
			messages.push(`FAIL ${id.padEnd(16)} ${error.message}`);
		}
	}
	return { checked, failures, skipped, messages };
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
	try {
		if (process.argv.length !== 2) throw new Error('usage: node scripts/check_tools.mjs');
		const report = await checkTools();
		for (const message of report.messages) console.log(message);
		console.log();
		if (report.skipped.length)
			console.log(
				`${report.skipped.length} skipped (missing local deps): ${report.skipped.join(', ')}`
			);
		console.log(`${report.failures.length} failure(s)`);
		process.exitCode = report.failures.length ? 1 : 0;
	} catch (error) {
		console.error(error.message);
		process.exitCode = 1;
	}
}
