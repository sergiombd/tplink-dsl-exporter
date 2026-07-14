// Reusable router webui helpers (Playwright + system Chrome, headless, LAN-only).
const { chromium } = require('playwright-core');
const CHROME = '/usr/bin/google-chrome-stable';
async function open() {
  const browser = await chromium.launch({ headless:true, executablePath:CHROME, args:['--no-sandbox'] });
  const page = await (await browser.newContext()).newPage();
  page._browser = browser;
  return page;
}
async function login(page, pw) {
  await page.goto('http://192.168.1.1/', { waitUntil:'networkidle', timeout:20000 });
  await page.waitForTimeout(800);
  await page.fill('#pc-login-password', pw);
  await page.click('#pc-login-btn').catch(()=>{});
  await page.waitForTimeout(1200);
  // Handle "another session active -> log in anyway?" confirm
  const conf = await page.$('#confirm-yes');
  if (conf && await conf.isVisible()) { await conf.click(); await page.waitForTimeout(1200); }
  await page.waitForTimeout(2500);
  // sanity: menu present?
  const ok = await page.evaluate(()=>!!Array.from(document.querySelectorAll('a,span')).find(e=>e.offsetParent!==null && /Advanced/.test(e.innerText||'')));
  return ok;
}
async function clickText(page, txt, tags='a,span,li,div,button') {
  return page.evaluate(([t,sel])=>{
    const el = Array.from(document.querySelectorAll(sel)).find(e=>e.offsetParent!==null && (e.innerText||'').trim()===t);
    if(el){ el.click(); return true;} return false;
  }, [txt,tags]);
}
async function logout(page) {
  await clickText(page,'Log out').catch(()=>{});
  await page.waitForTimeout(800);
  const y = await page.$('#confirm-yes'); if(y && await y.isVisible()){ await y.click(); await page.waitForTimeout(800);}    
}
module.exports = { open, login, clickText, logout };
