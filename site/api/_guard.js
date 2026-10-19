// The number guard, the same function as scripts/prompt.py scrub(): every figure in a draft must
// already appear in what the model was shown, or be a regulation citation. Anything else becomes
// [number], so a number the model made up never reaches the page.
const NUM = /(?<![\w.])\$?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?/g;
const CITE = /\b\d+\s*(?:CFR|C\.F\.R\.|U\.S\.C\.)\s*(?:part\s*|§\s*)?\d+(?:\.\d+)*(?:\([a-z0-9]+\))*|\b200\.\d+(?:\([a-z0-9]+\))*|§\s*\d+(?:\.\d+)*/gi;
const WORDNUM = /\b(?:three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand)\b/gi;
const norm = (t) => { const x = t.replace(/[$,]/g, "").replace(/%$/, ""); return x.replace(/\.$/, "") || x; };

function allowedNumbers(source, system) {
  const ok = new Set([...source.matchAll(NUM)].map((m) => norm(m[0])));
  for (const c of (source + "\n" + system).matchAll(CITE)) for (const m of c[0].matchAll(NUM)) ok.add(norm(m[0]));
  for (const m of source.matchAll(WORDNUM)) ok.add(m[0].toLowerCase());
  return ok;
}

function scrub(v, ok, removed) {
  if (Array.isArray(v)) return v.map((x) => scrub(x, ok, removed));
  if (v && typeof v === "object") return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, k.startsWith("_") ? x : scrub(x, ok, removed)]));
  if (typeof v !== "string") return v;
  const cites = [...v.matchAll(CITE)].map((m) => [m.index, m.index + m[0].length]);
  return v.replace(NUM, (m, off) => {
    if (cites.some(([a, b]) => a <= off && off < b) || ok.has(norm(m))) return m;
    removed.push(m);
    return "[number]";
  }).replace(WORDNUM, (m) => {
    if (ok.has(m.toLowerCase())) return m;
    removed.push(m);
    return "[number]";
  }).replace(/\ball \[number\](?=[\s:.,;])/g, "all of these");
}

module.exports = { allowedNumbers, scrub };
