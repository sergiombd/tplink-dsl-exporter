const { chromium } = require('playwright-core');
const SS = process.env.SS_DIR, PW = process.env.ROUTER_PASSWORD;
(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: '/usr/bin/google-chrome-stable', args:['--no-sandbox'] });
  const page = await (await browser.newContext()).newPage();
  const errs=[]; page.on('console', m=>{ if(m.type()==='error') errs.push(m.text().slice(0,120)); });
  await page.goto('http://192.168.1.1/', { waitUntil:'networkidle', timeout:20000 });
  await page.waitForTimeout(1000);
  // fill password + submit
  await page.fill('#pc-login-password', PW);
  // find a login button
  const btn = await page.evaluate(()=>{
    const cands = Array.from(document.querySelectorAll('button,a,input[type=button],input[type=submit]'));
    const b = cands.find(e=>/login/i.test(e.id)||/login/i.test((e.innerText||e.value||'')));
    return b? (b.id||b.className):null;
  });
  console.log('login control:', btn);
  await page.click('#pc-login-btn').catch(async()=>{ await page.keyboard.press('Enter'); });
  await page.waitForTimeout(3500);
  await page.screenshot({ path: SS+'/after-login.png', fullPage:true });
  const nav = await page.evaluate(()=>{
    const menu = Array.from(document.querySelectorAll('a,li,span')).map(e=>({id:e.id||'',txt:(e.innerText||'').trim().slice(0,40)})).filter(x=>x.txt && x.txt.length<40);
    // top tabs
    const tabs = Array.from(document.querySelectorAll('#tabModeChoose a,#topTab a,.tab a,[id*=tab] a')).map(a=>({id:a.id,txt:(a.innerText||'').trim()}));
    return { title:document.title, url:location.href, tabs, menuSample: menu.filter(m=>/dsl|internet|advanced|network|xdsl|wan|connection/i.test(m.txt)).slice(0,40) };
  });
  console.log(JSON.stringify(nav,null,1));
  console.log('console errors:', errs.slice(0,8));
  await browser.close();
})().catch(e=>{console.error('FATAL', e.message); process.exit(1);});
