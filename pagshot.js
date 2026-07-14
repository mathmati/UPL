const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const p = await b.newPage({ viewport: { width: 720, height: 480 } });
  await p.goto('http://127.0.0.1:8478/');
  await p.waitForSelector('.miura-item');
  await p.screenshot({ path: 'miura-v07.png' });
  // read back the prefilled value of the first item's edit form title input
  const val = await p.$eval('.miura-item form input[name=title]', el => el.value);
  console.log('PREFILLED_TITLE=' + val);
  const btn = await p.$eval('.miura-item form button[type=submit]', el => el.textContent);
  console.log('SUBMIT_LABEL=' + btn);
  await b.close();
})();
