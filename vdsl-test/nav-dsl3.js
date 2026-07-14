const R = require('./router');
const SS = process.env.SS_DIR, PW = process.env.ROUTER_PASSWORD;
(async () => {
  const page = await R.open();
  await R.login(page, PW);
  await page.locator('.T_adv, .T_menu, a', {hasText:'Advanced'}).first().click().catch(()=>{});
  await page.waitForTimeout(1500);
  // Click the Network row (menu item). Try several strategies.
  let clicked=false;
  for (const sel of ['.click.more','.click','li','a']) {
    const loc = page.locator(sel, { hasText:'Network' });
    const n = await loc.count();
    for (let i=0;i<n;i++){
      const t=(await loc.nth(i).innerText().catch(()=>'')).trim();
      if (t==='Network'){ await loc.nth(i).click({timeout:2000}).catch(()=>{}); clicked=true; break; }
    }
    if(clicked){ console.log('clicked Network via', sel); break; }
  }
  await page.waitForTimeout(2000);
  await page.screenshot({ path: SS+'/network-expanded.png', fullPage:false });
  const sub = await page.evaluate(()=>Array.from(document.querySelectorAll('.text, a, span, li'))
     .filter(e=>e.offsetParent!==null).map(e=>(e.innerText||'').trim())
     .filter(t=>/dsl|internet|interface group|lan setting|dynamic dns|static rout|ipv6/i.test(t)));
  console.log('submenu candidates:', JSON.stringify([...new Set(sub)],null,1));
  await R.logout(page); await page._browser.close();
})().catch(e=>{console.error('FATAL', e.message); process.exit(1);});
