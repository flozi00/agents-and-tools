#!/usr/bin/env node
// Adds an app exported from EU-Prompt (app page → Download template) to the catalog.
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { APP_ID, APP_LOCAL_KEYS, HUB, generateIndex } from './generate_index.mjs';

export function appId(text) {
	return String(text)
		.normalize('NFKD')
		.replace(/[̀-ͯ]/g, '')
		.toLowerCase()
		.replace(/[^a-z0-9]+/g, '-')
		.replace(/^-+|-+$/g, '')
		.slice(0, 64)
		.replace(/-+$/, '');
}

/** Writes `apps/<id>/app.json` without installation-local keys, then regenerates the index. */
export function addApp(root, exported, { id, version } = {}) {
	if (exported === null || typeof exported !== 'object' || Array.isArray(exported))
		throw new Error('the exported app must be a JSON object');
	const app = { ...exported };
	for (const key of APP_LOCAL_KEYS) delete app[key];
	app.id = appId(id || exported.id || exported.name || '');
	if (!APP_ID.test(app.id)) throw new Error(`cannot derive a valid app id from "${app.id}"`);
	app.version = String(version || exported.version || '1.0.0');
	if (!app.description) app.description = app.name ? String(app.name) : '';
	mkdirSync(join(root, 'apps', app.id), { recursive: true });
	writeFileSync(join(root, 'apps', app.id, 'app.json'), JSON.stringify(app, null, '\t') + '\n');
	generateIndex(root);
	return app;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
	try {
		const [file, id, version] = process.argv.slice(2);
		if (!file) throw new Error('usage: node scripts/add_app.mjs <exported.json> [app-id] [version]');
		const app = addApp(HUB, JSON.parse(readFileSync(file, 'utf8')), { id, version });
		const records = Array.isArray(app.records) ? app.records.length : 0;
		console.log(`apps/${app.id}/app.json written (version ${app.version})`);
		if (records > 0)
			console.warn(
				`warning: ${records} records are included — publish only sample data, never client data`
			);
	} catch (error) {
		console.error(`error: ${error.message}`);
		process.exitCode = 1;
	}
}
