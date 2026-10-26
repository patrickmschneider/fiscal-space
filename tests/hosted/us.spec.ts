import {test,expect} from '@playwright/test';
import fs from 'node:fs/promises';
import AxeBuilder from '@axe-core/playwright';

// The US edition is published beneath the UK app at us/.
test('US edition loads its own data, pages and charts beneath us/',async({page,request},testInfo)=>{
 const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));
 const fiscal=await (await request.get('us/data/fiscal.json')).json();
 expect(fiscal.scope).toMatch(/federal/i);
 await page.goto('./us/?page=overview');
 await expect(page.getByText('A GUIDE TO THE US FEDERAL FINANCES')).toBeVisible();
 await expect(page.getByText(/The federal deficit was|federal surplus/).first()).toBeVisible();
 await expect(page.getByText('Some saved data could not be loaded')).toHaveCount(0);
 const editions=page.getByRole('group',{name:'Country edition'});
 await expect(editions.getByRole('link',{name:'United States'})).toHaveAttribute('aria-current','page');
 await expect(editions.getByRole('link',{name:'UK',exact:true})).toHaveAttribute('href','../?page=overview');
 await expect(editions.getByRole('link',{name:'Australia'})).toHaveAttribute('href','../au/?page=overview');
 await page.goto('./us/?page=fiscal&section=position');
 await expect(page.getByRole('heading',{name:'America’s fiscal position.'})).toBeVisible();
 await page.getByRole('button',{name:'Debt & financing',exact:true}).click();
 await expect(page.getByRole('heading',{name:'The stock. The cost. The calendar.'})).toBeVisible();
 await page.goto('./us/?page=pricing');
 for(const id of ['yield-curve','real-curve','breakeven'])await expect(page.locator(`[aria-labelledby="${id}-title"] .recharts-line-curve`).first()).toBeVisible();
 const pending=page.waitForEvent('download');await page.getByRole('button',{name:'Download Nominal Treasury yield curve CSV',exact:true}).click();
 const path=testInfo.outputPath('us-curve.csv');await (await pending).saveAs(path);
 const text=await fs.readFile(path,'utf8');expect(text).toContain('Treasury');expect(text).not.toContain('Bank of England');
 await page.goto('./us/?page=fiscal&section=composition');
 await expect(page.getByRole('heading',{name:'Spending and revenue composition'})).toBeVisible();
 await page.setViewportSize({width:375,height:900});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 const accessibility=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa']).analyze();
 expect(accessibility.violations.map(v=>v.id)).toEqual([]);
 for(const view of ['?page=overview','?page=fiscal&section=position','?page=fiscal&section=composition','?page=fiscal&section=outlook','?page=fiscal&section=rules','?page=fiscal&section=deficits','?page=debt','?page=pricing','?page=explore&view=reliefs','?page=explore&view=methodology']){
  await page.goto(`./us/${view}`);await expect(page.locator('main footer')).toBeVisible();
  await expect(page.locator('main')).not.toContainText(/\b(?:OBR|ONS|RPI|HMRC|DMO|AOFM|RBA|PSNB|PSND)\b|£|A\$|\b[Gg]ilts?\b|Bank of England/);
  await expect(page.locator('main')).not.toContainText(/financial year/i);
 }
 expect(errors).toEqual([]);
});
