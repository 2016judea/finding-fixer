// GET /api/preview?n=<slug> -> the free view of one nonprofit's latest flagged audit: every
// finding with type, severity and repeat flag, the auditor's text, the filed CAP, and the
// drafted CAP paragraph for the first finding. No password. The rest is /api/data.
const { view } = require("./_view");

module.exports = (req, res) => {
  try {
    const v = view(req.query.n, false);
    if (!v) return res.status(404).json({ error: "No nonprofit by that name has a finding on file." });
    res.setHeader("Cache-Control", "public, s-maxage=3600, max-age=300");
    res.status(200).json(v);
  } catch (e) {
    console.error("[preview]", e.message);
    res.status(500).json({ error: "Couldn't load that audit. Try again in a minute." });
  }
};
