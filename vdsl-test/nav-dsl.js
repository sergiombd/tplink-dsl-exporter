const R = require('./router');
const SS = process.env.SS_DIR, PW = process.env.ROUTER_PASSWORD;
(async () => {
  const page = await R.open();
  const ok = await R.login(page, PW);
  console.log('login ok:', ok);
  console.log('Advanced:', await R.clickText(page,'Advanced')); await page.waitForTimeout(1500);
  console.log('Network:', await R.clickText(page,'Network')); await page.waitForTimeout(1200);
  console.log('DSL Settings:', await R.clickText(page,'DSL Settings')); await page.waitForTimeout(2500);
  await page.screenshot({ path: SS+'/dsl-settings.png', fullPage:true });
  const dump = await page.evaluate(()=>{
    const info=e=>({tag:e.tagName,type:e.type||'',id:e.id||'',name:e.name||'',cls:(e.className||'').toString().slice(0,50),checked:e.checked,value:(e.value||'').slice(0,30),txt:(e.innerText||'').trim().slice(0,40),vis:e.offsetParent!==null});
    const q=s=>Array.from(document.querySelectorAll(s)).map(info).filter(x=>x.vis);
    const selects=Array.from(document.querySelectorAll('select')).filter(s=>s.offsetParent!==null).map(s=>({id:s.id,name:s.name,value:s.value,opts:Array.from(s.options).map(o=>({v:o.value,t:o.text,sel:o.selected}))}));
    return { url:location.href, selects, checkboxes:q('input[type=checkbox]'), radios:q('input[type=radio]'), buttons:q('button').filter(b=>!/login|confirm/i.test(b.id)) };
  });
  console.log(JSON.stringify(dump,null,1));
  await R.logout(page);
  await page._browser.close();
})().catch(e=>{console.error('FATAL', e.message); process.exit(1);});
