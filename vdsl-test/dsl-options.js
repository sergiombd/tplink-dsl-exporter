const R = require('./router');
const SS = process.env.SS_DIR, PW = process.env.ROUTER_PASSWORD;
async function clickRow(page, txt){
  for (const sel of ['.click.more','.click','.text','li','a']) {
    const loc = page.locator(sel, { hasText:txt });
    const n = await loc.count();
    for (let i=0;i<n;i++){ const t=(await loc.nth(i).innerText().catch(()=>'')).trim(); if(t===txt){ await loc.nth(i).click({timeout:2000}).catch(()=>{}); return true; } }
  } return false;
}
(async () => {
  const page = await R.open();
  await R.login(page, PW);
  await clickRow(page,'Advanced'); await page.waitForTimeout(1000);
  await clickRow(page,'Network'); await page.waitForTimeout(1200);
  await clickRow(page,'DSL Settings'); await page.waitForTimeout(2500);
  // open the _adslMod dropdown and read options
  await page.locator('#_adslMod .select-box, #_adslMod .tp-select').first().click().catch(()=>{});
  await page.waitForTimeout(800);
  await page.screenshot({ path: SS+'/dsl-dropdown.png', fullPage:false });
  const opts = await page.evaluate(()=>{
    const box=document.querySelector('#_adslMod');
    const lis=Array.from(box.querySelectorAll('li, .select-item, option, a')).map(e=>({txt:(e.innerText||e.textContent||'').trim(), val:e.getAttribute('data-value')||e.value||'', cls:(e.className||'').toString().slice(0,30)})).filter(x=>x.txt);
    const annex=document.querySelector('#_annexMod');
    const alis=Array.from(annex.querySelectorAll('li, .select-item, option')).map(e=>({txt:(e.innerText||'').trim(), val:e.getAttribute('data-value')||e.value||''})).filter(x=>x.txt);
    return { adslModOptions:lis, annexOptions:alis };
  });
  console.log(JSON.stringify(opts,null,1));
  await R.logout(page); await page._browser.close();
})().catch(e=>{console.error('FATAL', e.message); process.exit(1);});
