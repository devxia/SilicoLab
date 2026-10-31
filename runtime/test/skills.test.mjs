import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, symlink, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { SkillCatalog } from '../src/skills.ts';

test('catalog rejects changed content and symbolic links without loading arbitrary files', async () => {
  const root = await mkdtemp(join(tmpdir(), 'silicolab-skills-'));
  try {
    const skills = join(root, 'skills');
    await mkdir(join(skills, 'alpha'), { recursive: true });
    await writeFile(join(skills, 'alpha', 'SKILL.md'), '---\nname: alpha\ndescription: >\n  Artificial folded\n  description\n---\nBODY_ONE');
    const catalog = new SkillCatalog([{ path: skills, anchor: root, source: 'artificial' }]);
    const first = (await catalog.list()).skills[0];
    assert.equal(first.description, 'Artificial folded description');
    assert.equal((await catalog.load(first.id, first.sha256)).content.endsWith('BODY_ONE'), true);
    await writeFile(first.path, '---\nname: alpha\ndescription: changed\n---\nBODY_TWO');
    await assert.rejects(catalog.load(first.id, first.sha256), /改变/);
    await mkdir(join(root, 'outside'));
    await writeFile(join(root, 'outside', 'SKILL.md'), '---\nname: outside\ndescription: must not load\n---\nARTIFICIAL_PRIVATE_SENTINEL');
    await symlink(join(root, 'outside'), join(skills, 'linked'));
    const list = await catalog.list();
    const linked = list.skills.find(s => s.path.includes('/linked/'));
    assert.equal(linked.status, 'incompatible');
    assert.match(linked.reason, /symbolic/);
    assert.equal(JSON.stringify(list).includes('ARTIFICIAL_PRIVATE_SENTINEL'), false);
    await assert.rejects(catalog.load(linked.id, 'anything'), /改变|不兼容/);
  } finally { await rm(root, { recursive: true, force: true }); }
});

test('malformed high-priority single quote cannot shadow a valid lower-priority skill', async () => {
  const root = await mkdtemp(join(tmpdir(), 'silicolab-skill-quotes-'));
  try {
    for (const folder of ['high', 'low']) await mkdir(join(root, folder, 'alpha'), { recursive: true });
    await writeFile(join(root, 'high/alpha/SKILL.md'), "---\nname: alpha\ndescription: 'one'two'\n---\nBAD");
    await writeFile(join(root, 'low/alpha/SKILL.md'), "---\nname: alpha\ndescription: 'one''two'\n---\nGOOD");
    const catalog = new SkillCatalog(['high', 'low'].map(folder => ({ path: join(root, folder), anchor: root, source: folder })));
    const items = (await catalog.list()).skills;
    assert.equal(items[0].status, 'incompatible');
    assert.match(items[0].reason, /quoted/);
    assert.equal(items[1].status, 'available');
    assert.equal(items[1].description, "one'two");
    await writeFile(join(root, 'high/alpha/SKILL.md'), '---\nname: alpha\ndescription: # comment without a value\n---\nBAD');
    const comments = (await catalog.list()).skills;
    assert.equal(comments[0].status, 'incompatible');
    assert.equal(comments[1].status, 'available');
    await writeFile(join(root, 'high/alpha/SKILL.md'), '---\nname: alpha\ndescription: one # trailing comment\n---\nGOOD');
    assert.equal((await catalog.list()).skills[0].description, 'one');
  } finally { await rm(root, { recursive: true, force: true }); }
});
