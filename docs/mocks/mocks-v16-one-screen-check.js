// Reports every screen / state / tab whose page is taller than one laptop screen.
const {chromium}=require('playwright');
(async()=>{const b=await chromium.launch();const sizes=[[1366,696],[1280,720],[1536,864]];const shots=process.argv.includes('--shots');
const p=await b.newPage({viewport:{width:1366,height:696}});await p.goto('file://'+process.cwd()+'/index.html');await p.waitForTimeout(300);await p.addStyleTag({content:'*{animation:none!important}'});
const screens=await p.$$eval('#screenSel option',o=>o.map(x=>x.value));const bad=[];let n=0;
for(const [w,h] of sizes){await p.setViewportSize({width:w,height:h});
 for(const s of screens){if(s==='landing')continue;await p.evaluate(k=>{location.hash=k},s);await p.waitForTimeout(40);
  const sts=await p.$$eval('#states button',x=>x.map(y=>y.dataset.state));
  for(const st of (sts.length?sts:[null])){if(st)await p.click(`#states button[data-state="${st}"]`);
   const tabs=await p.$$eval('.tabs [data-tab]',x=>x.map(y=>y.dataset.tab));
   for(const tb of (tabs.length?tabs:[null])){if(tb)await p.evaluate(k=>document.querySelector(`.tabs [data-tab="${k}"]`).click(),tb);await p.waitForTimeout(20);n++;
    const o=await p.evaluate(()=>{const sd=document.querySelector('.side');const so=sd&&sd.offsetParent?sd.scrollHeight-sd.clientHeight:0;return Math.max(document.documentElement.scrollHeight-innerHeight,so)});
    if(o>0){bad.push(`${w}x${h} ${s} / ${st||'-'} / ${tb||'-'} : +${o}`);if(shots&&w===1366)await p.screenshot({path:`over-${s}-${(st||'').replace(/\W+/g,'')}-${(tb||'').replace(/\W+/g,'')}.png`,fullPage:true})}
   }}}}
console.log(n+' views checked; taller than the screen: '+bad.length);console.log(bad.join('\n'));await b.close();process.exit(bad.length?1:0)})();
