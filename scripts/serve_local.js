// Local preview of the deployed shape: site/public/ as static files, site/api/*.js as functions,
// private/data/ standing in for api/_full/. Reads ACCESS_SECRET from ./.env.
//   node scripts/serve_local.js [port]
const http = require("http"), fs = require("fs"), path = require("path"), url = require("url");
const ROOT = path.join(__dirname, "..");
process.env.FULL_DIR = path.join(ROOT, "private", "data");
for (const l of fs.readFileSync(path.join(ROOT, ".env"), "utf8").split("\n")) { const m = /^([A-Z_]+)=(.*)$/.exec(l); if (m && !process.env[m[1]]) process.env[m[1]] = m[2]; }
const SITE = path.join(ROOT, "site");
const TYPES = { ".html": "text/html", ".js": "text/javascript", ".json": "application/json", ".css": "text/css" };
http.createServer(async (req, res) => {
  const u = url.parse(req.url, true);
  res.status = (c) => (res.statusCode = c, res);
  res.json = (o) => { res.setHeader("Content-Type", "application/json"); res.end(JSON.stringify(o)); };
  req.query = u.query;
  if (u.pathname.startsWith("/api/") && !u.pathname.startsWith("/api/_")) {
    try { return await require(path.join(SITE, u.pathname + ".js"))(req, res); } catch (e) { console.error(e); return res.status(500).json({ error: e.message }); }
  }
  // Only site/public/ is static, exactly as on Vercel (outputDirectory "public"); /for/ comes from private/for.
  const PUB = u.pathname.startsWith("/for/") ? path.join(ROOT, "private") : path.join(SITE, "public");
  let f = path.join(PUB, decodeURIComponent(u.pathname));
  if (!f.startsWith(PUB) || u.pathname.startsWith("/api/")) return res.status(404).end();
  if (fs.existsSync(f) && fs.statSync(f).isDirectory()) f = path.join(f, "index.html");
  if (!fs.existsSync(f)) return res.status(404).end("not found");
  res.setHeader("Content-Type", TYPES[path.extname(f)] || "application/octet-stream");
  fs.createReadStream(f).pipe(res);
}).listen(+process.argv[2] || 4710, () => console.log("http://localhost:" + (+process.argv[2] || 4710)));
