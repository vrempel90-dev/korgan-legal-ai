import http from 'node:http';
import { createReadStream, statSync } from 'node:fs';
import path from 'node:path';

const root = path.resolve(process.cwd(), 'dist');
const port = Number(process.env.PORT || 4173);
const telegramMiniAppUrl = 'https://t.me/KORGANLEGALAI_BOT?startapp=qr';

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
    const isHtml = ext === '.html';
    res.writeHead(200, {
      'Content-Type': mime[ext] || 'application/octet-stream',
      'Content-Length': stat.size,
      'Cache-Control': isAsset
        ? 'public, max-age=31536000, immutable'
        : isHtml
          ? 'no-store, max-age=0, must-revalidate'
          : 'no-cache',
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

const server = http.createServer((req, res) => {
  if (req.method !== 'GET' && req.method !== 'HEAD') {
    res.writeHead(405, { Allow: 'GET, HEAD' });
    res.end('Method Not Allowed');
    return;
  }

  let url;
  let pathname = '/';
  try {
    url = new URL(req.url || '/', 'http://localhost');
    pathname = decodeURIComponent(url.pathname);
  } catch {
    res.writeHead(400);
    res.end('Bad Request');
    return;
  }

  if (pathname === '/app' || pathname === '/go' || pathname === '/start') {
    res.writeHead(302, {
      Location: telegramMiniAppUrl,
      'Cache-Control': 'no-store, max-age=0',
      'X-Content-Type-Options': 'nosniff',
    });
    res.end();
    return;
  }

  if (pathname === '/__korgan_boot') {
    const stage = String(url.searchParams.get('stage') || 'unknown').slice(0, 120);
    const detail = String(url.searchParams.get('detail') || '').slice(0, 240);
    const ua = String(req.headers['user-agent'] || '').slice(0, 240);
    console.log(`KORGAN_BOOT stage=${stage} detail=${detail} ua=${ua}`);
    res.writeHead(204, {
      'Cache-Control': 'no-store, max-age=0',
      'Access-Control-Allow-Origin': '*',
    });
    res.end();
    return;
  }

  const userAgent = String(req.headers['user-agent'] || '');
  if (pathname === '/' && /Telegram/i.test(userAgent)) {
    console.log(`KORGAN_BOOT stage=server-root-index ua=${userAgent.slice(0, 240)}`);
  }

  const requested = path.resolve(root, `.${pathname}`);
  if (requested.startsWith(root) && sendFile(req, res, requested)) return;

  if (sendFile(req, res, path.join(root, 'index.html'))) return;

  res.writeHead(503, { 'Content-Type': 'text/plain; charset=utf-8' });
  res.end('Mini App build is unavailable');
});

server.listen(port, '0.0.0.0', () => {
  console.log(`KORGAN Mini App serving dist on 0.0.0.0:${port}`);
});