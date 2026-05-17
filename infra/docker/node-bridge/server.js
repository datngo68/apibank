// Minimal HTTP bridge to CookieGMVN/MBBank node lib so the Python adapter can call it
// when mbbank-lib (Python) is broken. Single-tenant by env vars.
const express = require("express");
const { MB } = require("mbbank");

const app = express();
app.use(express.json());

const username = process.env.MB_USERNAME;
const password = process.env.MB_PASSWORD;
if (!username || !password) {
  console.error("MB_USERNAME and MB_PASSWORD env vars required");
  process.exit(1);
}

const client = new MB({ username, password, preferredOCRMethod: "default", saveWasm: true });
let loggedIn = false;

async function ensureLogin() {
  if (!loggedIn) {
    await client.login();
    loggedIn = true;
  }
}

app.post("/login", async (_req, res, next) => {
  try {
    await client.login();
    loggedIn = true;
    res.json({ status: "ok" });
  } catch (err) {
    loggedIn = false;
    next(err);
  }
});

app.get("/balance/:accountNumber", async (req, res, next) => {
  try {
    await ensureLogin();
    const balance = await client.getBalance();
    res.json({ balance });
  } catch (err) {
    loggedIn = false;
    next(err);
  }
});

app.get("/transactions/:accountNumber", async (req, res, next) => {
  try {
    await ensureLogin();
    const { from, to } = req.query;
    const txs = await client.getTransactionsHistory({
      accountNumber: req.params.accountNumber,
      fromDate: from,
      toDate: to,
    });
    res.json({ transactions: txs });
  } catch (err) {
    loggedIn = false;
    next(err);
  }
});

app.use((err, _req, res, _next) => {
  console.error(err);
  res.status(500).json({ error: err.message || String(err) });
});

const port = process.env.PORT || 3001;
app.listen(port, () => console.log(`mb-bridge listening on ${port}`));
