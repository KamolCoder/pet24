// Render mobile mockups to PNG at iPhone size (390x844, @3x).
// Usage: node design/mockups/shot.js [file.html ...]   (default: every *.html in this folder)
const path = require('path');
const fs = require('fs');
const { chromium } = require('playwright');

(async () => {
  const dir = __dirname;
  const files = process.argv.slice(2).length
    ? process.argv.slice(2).map((f) => path.resolve(f))
    : fs.readdirSync(dir).filter((f) => f.endsWith('.html')).map((f) => path.join(dir, f));
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 3 });
  for (const file of files) {
    await page.goto('file://' + file);
    await page.waitForTimeout(200);
    const out = file.replace(/\.html$/, '.png');
    await page.screenshot({ path: out });
    console.log(out);
  }
  await browser.close();
})();
