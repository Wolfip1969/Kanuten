// Rendert die Szene Bild für Bild und schickt die Frames direkt an ffmpeg (keine Zwischendateien).
// Aufruf durch fotokugel.py:  node render.js <url> <job.json> video|stills
const { chromium } = require('playwright');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

(async () => {
  const [url, jobPath, mode] = process.argv.slice(2);
  const job = JSON.parse(fs.readFileSync(jobPath, 'utf8'));
  const browser = await chromium.launch({
    executablePath: process.env.FOTOKUGEL_CHROMIUM || undefined,
    args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'],
  });
  const page = await browser.newPage({ viewport: { width: 400, height: 400 } });
  page.on('pageerror', e => console.error('Seitenfehler:', e.message));
  await page.goto(url);
  await page.waitForFunction('window.ready === true', null, { timeout: 300000 });
  const grab = async t => {
    const d = await page.evaluate(t => window.frameJPEG(t), t);
    return Buffer.from(d.split(',')[1], 'base64');
  };

  if (mode === 'stills') {
    for (const t of job.stills) {
      const file = path.join(job.stillsDir, `standbild_${t.toFixed(1).padStart(4, '0')}s.jpg`);
      fs.writeFileSync(file, await grab(t));
      console.log('Standbild', file);
    }
  } else {
    const ff = spawn(job.ffmpeg, [
      '-y', '-loglevel', 'error',
      '-f', 'image2pipe', '-framerate', String(job.fps), '-c:v', 'mjpeg', '-i', '-',
      ...job.videoArgs, job.videoOut,
    ], { stdio: ['pipe', 'inherit', 'inherit'] });
    const N = Math.round(job.duration * job.fps);
    for (let i = 0; i < N; i++) {
      const buf = await grab(i / job.fps);
      if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once('drain', r));
      if (i % job.fps === 0) process.stdout.write(`\r  Bild ${i + 1}/${N}`);
    }
    ff.stdin.end();
    const code = await new Promise(r => ff.on('close', r));
    process.stdout.write(`\r  Bild ${N}/${N}\n`);
    if (code !== 0) { console.error('ffmpeg ist fehlgeschlagen'); process.exitCode = 1; }
  }
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
