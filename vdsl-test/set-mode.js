// Usage: MODE="Auto Sync-up" [DRY_RUN=1] node set-mode.js
// Logs into the Archer VR300 webui (LAN-only, headless) and sets DSL Modulation Type.
const R = require('./router');
const PW = process.env.ROUTER_PASSWORD, MODE = process.env.MODE, DRY = process.env.DRY_RUN==='1';
const SS = process.env.SS_DIR;
async function clickRow(page, txt){
  for (const sel of ['.click.more','.click','.text','li','a']) {
    const loc = page.locator(sel, { hasText:txt });
    const n = await loc.count();
    for (let i=0;i<n;i++){ const t=(await loc.nth(i).innerText().catch(()=>'')).trim(); if(t===txt){ await loc.nth(i).click({timeout:2500}).catch(()=>{}); return true; } }
  } return false;
}
const log = (...a)=>console.log(new Date().toISOString(), ...a);
(async () => {
  if(!MODE){ console.error('MODE required'); process.exit(2);}    
  const page = await R.open();
  const ok = await R.login(page, PW); log('login', ok);
  if(!ok) throw new Error('login failed');
  await clickRow(page,'Advanced'); await page.waitForTimeout(1000);
  await clickRow(page,'Network'); await page.waitForTimeout(1200);
  if(!await clickRow(page,'DSL Settings')) throw new Error('DSL Settings not found');
  await page.waitForTimeout(2500);
  const before = await page.evaluate(()=>document.querySelector('#_adslMod .select-box')?.innerText.trim());
  log('current mode:', JSON.stringify(before));
  // open dropdown
  await page.locator('#_adslMod .select-box, #_adslMod .tp-select').first().click(); await page.waitForTimeout(600);
  // click desired option
  const picked = await page.evaluate((m)=>{ const li=Array.from(document.querySelectorAll('#_adslMod .option-item, #_adslMod li')).find(e=>(e.innerText||'').trim()===m); if(li){li.click(); return true;} return false; }, MODE);
  if(!picked) throw new Error('option not found: '+MODE);
  await page.waitForTimeout(600);
  const after = await page.evaluate(()=>document.querySelector('#_adslMod .select-box')?.innerText.trim());
  log('selected mode now shows:', JSON.stringify(after));
  if(after!==MODE) throw new Error('selection did not stick: '+after);
  if(DRY){ log('DRY_RUN: NOT clicking Save'); if(SS) await page.screenshot({path:SS+'/setmode-dry.png'}); await R.logout(page); await page._browser.close(); return; }
  log('clicking Save...');
  await page.click('#saveCfg');
  await page.waitForTimeout(1200);
  const y = await page.$('#confirm-yes'); if(y && await y.isVisible()){ log('confirm dialog -> yes'); await y.click(); }
  await page.waitForTimeout(3000);
  log('Save submitted for mode', MODE);
  // don't logout aggressively (session may drop as line retrains); try briefly
  try { await R.logout(page); } catch(e){}
  await page._browser.close();
  log('DONE');
})().catch(e=>{console.error(new Date().toISOString(),'FATAL', e.message); process.exit(1);});
