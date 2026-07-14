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
  await clickRow(page,'Advanced'); await page.waitForTimeout(1200);
  await clickRow(page,'Network'); await page.waitForTimeout(1500);
  console.log('DSL Settings clicked:', await clickRow(page,'DSL Settings')); await page.waitForTimeout(2800);
  await page.screenshot({ path: SS+'/dsl-page.png', fullPage:true });
  const dump = await page.evaluate(()=>{
    const info=e=>({tag:e.tagName,type:e.type||'',id:e.id||'',name:e.name||'',cls:(e.className||'').toString().slice(0,45),checked:e.checked,value:(e.value||'').slice(0,20),txt:(e.innerText||'').trim().slice(0,35)});
    const vis=e=>e.offsetParent!==null;
    const q=s=>Array.from(document.querySelectorAll(s)).filter(vis).map(info);
    const selects=Array.from(document.querySelectorAll('select')).filter(vis).map(s=>({id:s.id,name:s.name,value:s.value,opts:Array.from(s.options).map(o=>({v:o.value,t:o.text,sel:o.selected}))}));
    // TP-Link custom dropdowns render as div widgets; capture them too
    const widgets=Array.from(document.querySelectorAll('.tp-select, .select-container, [class*=select]')).filter(vis).map(w=>({cls:(w.className||'').toString().slice(0,40),txt:(w.innerText||'').trim().slice(0,60),id:w.id}));
    return { url:location.href, selects, widgets, checkboxes:q('input[type=checkbox]'), radios:q('input[type=radio]'),
       buttons:q('button').filter(b=>!/login|confirm|msg/i.test(b.id+b.cls)),
       titles:q('.form-item-title, .text-desc, label, h1, h2, .title').map(x=>x.txt).filter(Boolean).slice(0,40) };
  });
  console.log(JSON.stringify(dump,null,1));
  await R.logout(page); await page._browser.close();
})().catch(e=>{console.error('FATAL', e.message); process.exit(1);});
