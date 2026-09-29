// Internal Homepage helper. Serves only the published JSON, never host paths.
'use strict';
const http = require('node:http');
const fs = require('node:fs');
const fallbackKeys = ['root'];
const blank = (status) => ({status, identity_valid: false, total_bytes: null,
  used_bytes: null, free_bytes: null, used_pct: null,
  display: {status, total: 'N/A', used: 'N/A', free: 'N/A', percent: 'N/A'}});

function loadReport() {
  try {
    const data = JSON.parse(fs.readFileSync('/metrics/status.json', 'utf8'));
    const keys = Object.keys(data.drives || {});
    const age = Date.now() / 1000 - Number(data.generated_unix);
    if (!Number.isFinite(age) || age < -30 || age > 150) {
      return {generated_at: data.generated_at, drives: Object.fromEntries(keys.map(k => [k, blank('STALE')]))};
    }
    for (const key of keys) {
      const row = data.drives?.[key];
      if (!row || row.identity_valid !== true) {
        data.drives[key] = {...blank(row?.status || 'UNAVAILABLE'), errors: row?.errors || []};
      }
    }
    return data;
  } catch {
    return {drives: Object.fromEntries(fallbackKeys.map(k => [k, blank('UNAVAILABLE')]))};
  }
}

const server = http.createServer((req, res) => {
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('X-Content-Type-Options', 'nosniff');
  if (req.method !== 'GET') {res.writeHead(405); return res.end('{"error":"GET required"}');}
  if (req.url === '/healthz') {res.writeHead(200); return res.end('{"status":"ok"}');}
  const match = /^\/v1\/storage\/([a-z][a-z0-9_-]*)$/.exec(req.url);
  if (!match) {res.writeHead(404); return res.end('{"error":"not found"}');}
  const report = loadReport();
  res.writeHead(200);
  res.end(JSON.stringify({...report.drives[match[1]] || blank('UNAVAILABLE'), generated_at: report.generated_at || null}));
});
server.requestTimeout = 5000;
server.headersTimeout = 5000;
server.listen(9079, '0.0.0.0');
