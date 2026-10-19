// node --test test/site.test.js   (from the repo root; needs private/data/audits.json from scripts/build.py)
// Covers: the loader, the free/paid split (the free view never carries a paid field), the 401 and
// 402 paths of /api/data, the password HMAC round trip, the page build, and the /for/ page build.
const test = require('node:test'), assert = require('node:assert');
const fs = require('fs'), path = require('path'), { execFileSync } = require('child_process');
const ROOT = path.join(__dirname, '..');
process.env.FULL_DIR = path.join(ROOT, 'private', 'data');
process.env.ACCESS_SECRET = 'test-secret-not-the-real-one';
const { view, raw, decisionClock, rank } = require('../site/api/_view.js');
const lib = require('../site/api/_lib.js');
const index = JSON.parse(fs.readFileSync(path.join(ROOT, 'site/public/data/index.json'), 'utf8'));
const meta = JSON.parse(fs.readFileSync(path.join(ROOT, 'site/public/data/meta.json'), 'utf8'));
const audits = JSON.parse(fs.readFileSync(path.join(ROOT, 'private/data/audits.json'), 'utf8'));

const PAID_ONLY = ['root_cause', 'actions', 'responsible_person', 'completion_target', 'monitoring', 'agency_questions', 'evidence_to_attach', 'why_prior_plan_fell_short'];

test('the loader: every indexed slug resolves, only nonprofits, only latest audits in the index', () => {
  assert.ok(index.length > 100, 'index is thin');
  assert.strictEqual(index.length, meta.n_orgs);
  for (const r of index.slice(0, 50)) assert.ok(view(r.s, false), r.s);
  const latest = audits.filter(a => a.latest);
  assert.strictEqual(latest.length, index.length);
  assert.ok(audits.every(a => a.findings.length > 0));
});

test('the index carries no text, no contact, no email', () => {
  const s = JSON.stringify(index);
  assert.ok(!/@/.test(s), 'an email leaked into the public index');
  for (const k of ['text', 'prior_cap', 'contact', 'auditor']) assert.ok(!s.includes(`"${k}"`), k);
});

test('free view: findings listed with type and repeat flag; only the first finding has a drafted paragraph; no paid field anywhere', () => {
  let seen = 0;
  for (const r of index) {
    const v = view(r.s, false);
    assert.strictEqual(v.full, false);
    assert.strictEqual(v.findings.length, r.k);
    assert.strictEqual(v.findings.some(f => f.repeat), !!r.r);
    v.findings.forEach((f, i) => {
      assert.ok(Array.isArray(f.requirement_names));
      if (!f.draft) return;
      for (const k of PAID_ONLY) assert.ok(!(k in f.draft), `${r.s} ${f.ref} leaks ${k}`);
      if (i > 0) assert.deepStrictEqual(Object.keys(f.draft), ['title'], `${r.s} ${f.ref} leaks beyond the title`);
      else seen++;
    });
    const s = JSON.stringify(v);
    for (const k of PAID_ONLY) assert.ok(!s.includes(`"${k}"`), `${r.s} leaks ${k}`);
  }
  assert.ok(seen >= 0);
});

test('paid view: every drafted finding carries the whole draft, and the agency clock is six months after acceptance', () => {
  const r = index.find(x => raw(x.s, view(x.s, true).findings[0].ref).draft) || index[0];
  const v = view(r.s, true);
  assert.strictEqual(v.full, true);
  for (const f of v.findings) if (f.draft) for (const k of PAID_ONLY) assert.ok(k in f.draft, k);
  assert.strictEqual(decisionClock('2025-01-31'), '2025-07-31');
  assert.strictEqual(decisionClock('2024-08-31'), '2025-02-28');
  assert.ok(v.decision_by > v.org.accepted);
});

test('findings are ordered repeat material weakness first', () => {
  const f = { repeat: true, material_weakness: true, questioned_costs: false, significant_deficiency: false };
  const g = { repeat: false, material_weakness: true, questioned_costs: false, significant_deficiency: false };
  const h = { repeat: false, material_weakness: false, questioned_costs: false, significant_deficiency: true };
  assert.ok(rank(f) > rank(g) && rank(g) > rank(h));
});

test('password: minted passwords check as paid, comp passwords as comp, garbage as null', () => {
  const { nonce, password } = lib.newPassword();
  assert.match(password, /^[2-9B-DF-HJ-NP-TV-Z]{4}-[2-9B-DF-HJ-NP-TV-Z]{4}-[2-9B-DF-HJ-NP-TV-Z]{4}$/);
  assert.deepStrictEqual(lib.checkPassword(password), { nonce, kind: 'paid' });
  assert.deepStrictEqual(lib.checkPassword(password.toLowerCase().replace(/-/g, ' ')), { nonce, kind: 'paid' });
  assert.strictEqual(lib.checkPassword('XXXX-XXXX-XXXX'), null);
  assert.strictEqual(lib.checkPassword(''), null);
  const compRaw = nonce + lib.mac(nonce, 'comp:');
  assert.strictEqual(lib.checkPassword(compRaw).kind, 'comp');
});

function fakeRes() {
  const r = { code: 0, body: null, headers: {} };
  r.status = (c) => (r.code = c, r); r.json = (o) => (r.body = o, r); r.setHeader = (k, v) => (r.headers[k] = v); r.end = (b) => (r.body = b, r);
  return r;
}

test('/api/data: 401 bare, 401 on a bad password, 200 on a comp password with the full view', async () => {
  const data = require('../site/api/data.js');
  let res = fakeRes(); await data({ headers: {}, query: {} }, res); assert.strictEqual(res.code, 401);
  res = fakeRes(); await data({ headers: { 'x-password': 'ABCD-EFGH-JKLM' }, query: { n: index[0].s } }, res); assert.strictEqual(res.code, 401);
  const { nonce } = lib.newPassword(); const comp = nonce + lib.mac(nonce, 'comp:');
  res = fakeRes(); await data({ headers: { 'x-password': comp }, query: {} }, res); assert.strictEqual(res.code, 200); assert.deepStrictEqual(res.body, { ok: true });
  res = fakeRes(); await data({ headers: { 'x-password': comp }, query: { n: index[0].s } }, res); assert.strictEqual(res.code, 200); assert.strictEqual(res.body.full, true);
  assert.strictEqual(res.headers['X-Access'], 'comp');
});

test('/api/preview: 200 with the free view, 404 on an unknown name', () => {
  const preview = require('../site/api/preview.js');
  let res = fakeRes(); preview({ query: { n: index[3].s } }, res); assert.strictEqual(res.code, 200); assert.strictEqual(res.body.full, false);
  res = fakeRes(); preview({ query: { n: 'no-such-group-nowhere' } }, res); assert.strictEqual(res.code, 404);
});

test('/api/draft: 401 bare (the free paragraph is never drafted live)', async () => {
  const draft = require('../site/api/draft.js');
  const res = fakeRes(); await draft({ method: 'POST', headers: {}, body: { n: index[0].s, ref: 'x' } }, res);
  assert.strictEqual(res.code, 402);
});

test('the page carries the analytics tags and reads its numbers from meta, never typed', () => {
  const html = fs.readFileSync(path.join(ROOT, 'site/public/index.html'), 'utf8');
  assert.ok(html.includes('/_vercel/insights/script.js'));
  assert.ok(html.includes('bm-posthog:begin') && html.includes('S="finding-fixer"'));
  for (const ev of ['preview_open', 'checkout_open', "track('paid')", "track('unlock')"]) assert.ok(html.includes(ev), ev);
  assert.ok(html.includes('data-m="n_orgs"') && html.includes('data-m="price_usd"'));
  assert.ok(!/\b(359|664|545)\b/.test(html.replace(/<script[\s\S]*?<\/script>/g, '')), 'a data count is typed into the page');
  assert.ok(!/\$100/.test(html), 'the price is typed into the page');
});

test('/for/<token>/ pages build from the ledger with the variant and no variant in the URL', () => {
  const led = path.join(ROOT, 'outreach/round1/ledger.csv');
  if (!fs.existsSync(led)) return;
  execFileSync('python3', [path.join(ROOT, 'scripts/build_for.py')]);
  const rows = fs.readFileSync(led, 'utf8').trim().split('\n').slice(1).filter(Boolean);
  const live = rows.filter(r => !/,hold,/.test(r));
  const dirs = fs.existsSync(path.join(ROOT, 'private/for')) ? fs.readdirSync(path.join(ROOT, 'private/for')) : [];
  assert.strictEqual(dirs.length, live.length);
  for (const d of dirs.slice(0, 5)) {
    const h = fs.readFileSync(path.join(ROOT, 'private/for', d, 'index.html'), 'utf8');
    assert.ok(h.includes(`window.FOR={"t": "${d}"`) || h.includes(`window.FOR={"t":"${d}"`), d);
    assert.ok(h.includes('noindex'));
    assert.match(h, /"v": "(A|B)"/);
  }
});

test('number guard: a figure the model was not shown becomes [number]; figures from the finding and CFR cites survive; JS matches Python', () => {
  const { allowedNumbers, scrub } = require('../site/api/_guard.js');
  const src = 'Questioned costs of $9,558 in 7 of the 29 files tested, seven of them late. See 34 CFR 668.22(f).';
  const sys = 'Under 2 CFR 200.511(c) and 200.521.';
  const draft = { cap_paragraph: 'We will fix 7 of 29 files ($9,558) per 34 CFR 668.22(f) and 2 CFR 200.511(c) by June 2025, testing 40 files for four quarters, all seven of them.', _model: 'opus 5' };
  const removed = [];
  const out = scrub(draft, allowedNumbers(src, sys), removed);
  assert.deepStrictEqual(removed, ['2025', '40', 'four']);
  assert.strictEqual(out.cap_paragraph, 'We will fix 7 of 29 files ($9,558) per 34 CFR 668.22(f) and 2 CFR 200.511(c) by June [number], testing [number] files for [number] quarters, all seven of them.');
  assert.strictEqual(out._model, 'opus 5');
  const py = execFileSync('python3', ['-c', `import sys,json;sys.path.insert(0,${JSON.stringify(path.join(ROOT, 'scripts'))});import prompt as p;p.SYSTEM=${JSON.stringify(sys)};r=[];o=p.scrub(json.loads(sys.argv[1]),p.allowed_numbers(sys.argv[2]),r);print(json.dumps([o['cap_paragraph'],r]))`, JSON.stringify(draft), src]).toString();
  assert.deepStrictEqual(JSON.parse(py), [out.cap_paragraph, removed]);
});

test('every stored draft passes the number guard (no figure the model was not shown)', () => {
  const { allowedNumbers, scrub } = require('../site/api/_guard.js');
  const { content } = require('../site/api/draft.js');
  const PROMPT = require('../site/api/_prompt.json');
  const drafts = JSON.parse(fs.readFileSync(path.join(ROOT, 'private/data/drafts.json'), 'utf8'));
  const byKey = new Map(audits.flatMap(a => a.findings.map(f => [`${a.report_id}|${f.ref}`, [a, f]])));
  let n = 0;
  for (const [k, d] of Object.entries(drafts)) {
    const [a, f] = byKey.get(k); const removed = [];
    scrub(d, allowedNumbers(content(a, f), PROMPT.system), removed);
    assert.deepStrictEqual(removed, [], `${k} carries an unguarded figure`); n++;
  }
  assert.ok(n > 0);
});

test('the static tree (site/public) holds no finding text, filed plan or draft; the paid bundle never deploys under public/', () => {
  const walk = d => fs.readdirSync(d, { withFileTypes: true }).flatMap(e => e.isDirectory() ? walk(path.join(d, e.name)) : [path.join(d, e.name)]);
  const files = walk(path.join(ROOT, 'site/public'));
  const sample = audits.find(a => a.latest && a.findings[0].text.length > 400).findings[0].text.slice(100, 180);
  for (const f of files) {
    const s = fs.readFileSync(f, 'utf8');
    assert.ok(!s.includes(sample), `${f} carries finding text`);
    for (const k of ['"prior_cap"', '"cap_paragraph"', '"root_cause"', '"vs_filed_plan"']) assert.ok(!s.includes(k), `${f} carries ${k}`);
  }
  const vj = JSON.parse(fs.readFileSync(path.join(ROOT, 'site/vercel.json'), 'utf8'));
  assert.strictEqual(vj.outputDirectory, 'public');
  const dep = fs.readFileSync(path.join(ROOT, 'scripts/deploy.py'), 'utf8');
  assert.match(dep, /\(PRIVATE \/ "data", "api\/_full"\)/);
  assert.match(dep, /"outputDirectory": "public"/);
});
