const { chromium } = require('playwright-core');
const SS = process.env.SS_DIR;
(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: '/usr/bin/google-chrome-stable', args:['--no-sandbox'] });
  const ctx = await browser.newContext({ ignoreHTTPSErrors: true });
  const page = await ctx.newPage();
  page.on('console', m => console.log('  [page]', m.type(), m.text().slice(0,200)));
  await page.goto('http://192.168.1.1/', { waitUntil: 'networkidle', timeout: 20000 }).catch(e=>console.log('goto:',e.message));
  await page.waitForTimeout(1500);
  await page.screenshot({ path: SS + '/login.png', fullPage: true });
  const els = await page.evaluate(() => {
    const info = (e) => ({ tag:e.tagName, type:e.type||'', id:e.id||'', name:e.name||'', cls:(e.className||'').toString().slice(0,60), ph:e.placeholder||'', txt:(e.innerText||e.value||'').slice(0,40), vis: !!(e.offsetParent!==null) });
    const q = (s)=>Array.from(document.querySelectorAll(s)).map(info);
    return { title: document.title, url: location.href,
      inputs: q('input'), buttons: q('button'),
      links: Array.from(document.querySelectorAll('a')).slice(0,40).map(a=>({id:a.id,txt:(a.innerText||'').slice(0,30),href:a.getAttribute('href')})) };
  });
  console.log(JSON.stringify(els, null, 1));
  await browser.close();
})().catch(e=>{console.error('FATAL', e); process.exit(1);});
