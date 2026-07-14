const R = require('./router');
const SS = process.env.SS_DIR, PW = process.env.ROUTER_PASSWORD;
(async () => {
  const page = await R.open();
  await R.login(page, PW);
  await R.clickText(page,'Advanced'); await page.waitForTimeout(1500);
  // click the Network menu entry (try anchor/li)
  await page.evaluate(()=>{ const e=Array.from(document.querySelectorAll('a,li,span,div')).find(x=>x.offsetParent!==null && (x.innerText||'').trim()==='Network'); if(e) e.click(); });
  await page.waitForTimeout(1800);
  await page.screenshot({ path: SS+'/network-menu.png', fullPage:false });
  const menu = await page.evaluate(()=>Array.from(document.querySelectorAll('#menuList a, #menuTree a, .T_menu a, .menu a, ul li a, ul li span'))
     .filter(e=>e.offsetParent!==null).map(e=>({txt:(e.innerText||'').trim().slice(0,30), id:e.id||'', cls:(e.className||'').toString().slice(0,40)})).filter(x=>x.txt));
  console.log(JSON.stringify(menu,null,1));
  await R.logout(page); await page._browser.close();
})().catch(e=>{console.error('FATAL', e.message); process.exit(1);});
