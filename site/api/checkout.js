// POST /api/checkout {token?} -> { clientSecret } for Stripe embedded Checkout. One price, once
// (README "## Price"). The buyer's password is minted here so it rides in the invoice footer
// (Stripe's own invoice email is a second copy of it); the webhook, via the shared stripe-router,
// emails it when the session completes. A /for/<token>/ page returns to itself after paying.
const { SITE, PRODUCT, TOOL, stripe, newPassword } = require("./_lib");
const meta = require("../public/data/meta.json");

module.exports = async (req, res) => {
  if (req.method !== "POST") return res.status(405).json({ error: "POST only" });
  try {
    const { nonce, password } = newPassword();
    const b = typeof req.body === "object" && req.body ? req.body : {};
    const token = /^[a-z0-9]{6,16}$/.test(b.token || "") ? b.token : "";
    const name = TOOL.name;
    const s = await stripe("checkout/sessions", {
      method: "POST",
      form: {
        ui_mode: "embedded_page",
        mode: "payment",
        "line_items[0][quantity]": "1",
        "line_items[0][price_data][currency]": "usd",
        "line_items[0][price_data][unit_amount]": String(TOOL.price_usd * 100),
        "line_items[0][price_data][product_data][name]": name,
        "line_items[0][price_data][product_data][description]": `${TOOL.checkout_line} Any of ${meta.n_orgs.toLocaleString("en-US")} Minnesota nonprofits with a finding on file.`,
        "payment_method_types[0]": "card",
        "payment_method_types[1]": "link",
        customer_creation: "always",
        "invoice_creation[enabled]": "true",
        "invoice_creation[invoice_data][description]": name,
        "invoice_creation[invoice_data][custom_fields][0][name]": "Password",
        "invoice_creation[invoice_data][custom_fields][0][value]": password,
        "invoice_creation[invoice_data][custom_fields][1][name]": "Open at",
        "invoice_creation[invoice_data][custom_fields][1][value]": SITE.replace("https://", ""),
        "invoice_creation[invoice_data][footer]": `Your password: ${password}. Open the full plan at ${SITE}/?pw=${password}. Brick & Mortar · aidan@brickandmortar.dev`,
        "invoice_creation[invoice_data][metadata][product]": PRODUCT,
        "metadata[product]": PRODUCT,
        "metadata[site]": SITE,
        "metadata[handler]": `${SITE}/api/session-status`,
        "metadata[pw_nonce]": nonce,
        "metadata[password]": password,
        "metadata[token]": token,
        "payment_intent_data[metadata][product]": PRODUCT,
        "payment_intent_data[metadata][pw_nonce]": nonce,
        "payment_intent_data[description]": name,
        return_url: `${SITE}/${token ? `for/${token}/` : ""}?paid={CHECKOUT_SESSION_ID}`,
      },
    });
    res.status(200).json({ clientSecret: s.client_secret });
  } catch (e) {
    console.error("[checkout]", e.message);
    res.status(502).json({ error: "Checkout could not start. Please try again in a minute." });
  }
};
