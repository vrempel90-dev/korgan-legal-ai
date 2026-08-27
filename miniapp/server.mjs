import http from 'node:http';
import https from 'node:https';
import { createReadStream, statSync } from 'node:fs';
import path from 'node:path';

const root = path.resolve(process.cwd(), 'dist');
const port = Number(process.env.PORT || 4173);
const apiPrefix = '/korgan-api';
const configuredApiTarget = String(
  process.env.KORGAN_API_PROXY_TARGET || process.env.VITE_KORGAN_API_BASE || '',
).trim();

let apiTarget = null;
try {
  const parsed = new URL(configuredApiTarget);
  if (parsed.protocol === 'https:' && !parsed.username && !parsed.password) apiTarget = parsed;
} catch {
  apiTarget = null;
}

const mime = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.webp': 'image/webp',
  '.ico': 'image/x-icon',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
};

function sendFile(req, res, filePath) {
  try {
    const stat = statSync(filePath);
    if (!stat.isFile()) return false;

    const ext = path.extname(filePath).toLowerCase();
    const isAsset = filePath.includes(`${path.sep}assets${path.sep}`);
    res.writeHead(200, {
      'Content-Type': mime[ext] || 'application/octet-stream',
      'Content-Length': stat.size,
      'Cache-Control': isAsset ? 'public, max-age=31536000, immutable' : 'no-cache',
      'X-Content-Type-Options': 'nosniff',
    });

    if (req.method === 'HEAD') {
      res.end();
      return true;
    }

    createReadStream(filePath).pipe(res);
    return true;
  } catch {
    return false;
  }
}

function proxyApi(req, res, incomingUrl) {
  if (!apiTarget) {
    res.writeHead(503, { 'Content-Type': 'application/json; charset=utf-8' });
    res.end(JSON.stringify({ detail: 'KORGAN API proxy is not configured' }));
    return;
  }

  const suffix = incomingUrl.pathname.slice(apiPrefix.length) || '/';
  const upstream = new URL(apiTarget.toString());
  const basePath = upstream.pathname.replace(/\/$/, '');
  upstream.pathname = `${basePath}${suffix.startsWith('/') ? suffix : `/${suffix}`}`;
  upstream.search = incomingUrl.search;

  const headers = { ...req.headers, host: upstream.host };
  // Browser-origin headers are intentionally stripped. The browser talks only
  // to this same-origin Mini App server; CORS is no longer part of the trusted
  // API path. Telegram auth and content headers are preserved verbatim.
  delete headers.origin;
  delete headers.referer;
  delete headers['sec-fetch-site'];
  delete headers['sec-fetch-mode'];
  delete headers['sec-fetch-dest'];

  const upstreamRequest = https.request(
    upstream,
    { method: req.method, headers },
    (upstreamResponse) => {
      const responseHeaders = { ...upstreamResponse.headers };
      delete responseHeaders['access-control-allow-origin'];
      delete responseHeaders['access-control-allow-credentials'];
      delete responseHeaders['access-control-allow-methods'];
      delete responseHeaders['access-control-allow-headers'];
      res.writeHead(upstreamResponse.statusCode || 502, responseHeaders);
      upstreamResponse.pipe(res);
    },
  );

  upstreamRequest.on('error', () => {
    if (res.headersSent) {
      res.destroy();
      return;
    }
    res.writeHead(502, { 'Content-Type': 'application/json; charset=utf-8' });
    res.end(JSON.stringify({ detail: 'KORGAN API proxy is temporarily unavailable' }));
  });

  req.pipe(upstreamRequest);
}

const server = http.createServer((req, res) => {
  let incomingUrl;
  try {
    incomingUrl = new URL(req.url || '/', 'http://localhost');
  } catch {
    res.writeHead(400);
    res.end('Bad Request');
    return;
  }

  if (
    incomingUrl.pathname === apiPrefix
    || incomingUrl.pathname.startsWith(`${apiPrefix}/`)
  ) {
    proxyApi(req, res, incomingUrl);
    return;
  }

  if (req.method !== 'GET' && req.method !== 'HEAD') {
    res.writeHead(405, { Allow: 'GET, HEAD' });
    res.end('Method Not Allowed');
    return;
  }

  let pathname = '/';
  try {
    pathname = decodeURIComponent(incomingUrl.pathname);
  } catch {
    res.writeHead(400);
    res.end('Bad Request');
    return;
  }

  const requested = path.resolve(root, `.${pathname}`);
  if (requested.startsWith(root) && sendFile(req, res, requested)) return;

  if (sendFile(req, res, path.join(root, 'index.html'))) return;

  res.writeHead(503, { 'Content-Type': 'text/plain; charset=utf-8' });
  res.end('Mini App build is unavailable');
});

server.listen(port, '0.0.0.0', () => {
  const proxyStatus = apiTarget ? ` proxy=${apiTarget.origin}` : ' proxy=unconfigured';
  console.log(`KORGAN Mini App serving dist on 0.0.0.0:${port}${proxyStatus}`);
});
