import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';

// `--mode au` / `--mode us` build the Australian and US editions from the same code with their own saved data in public-<mode>/.
const editions = {
  uk: { title: 'Fiscal Space', description: 'Understanding the UK fiscal position, outlook and risks. Official data, transparent calculations and forecast vintages.', short: 'Fiscal Space: a guide to the UK public finances', url: 'https://patrickmschneider.github.io/fiscal-space/' },
  us: { title: 'Fiscal Space · United States', description: 'Understanding the US federal fiscal position, outlook and risks. Official data, transparent calculations and projection vintages.', short: 'Fiscal Space: a guide to the US federal finances', url: 'https://patrickmschneider.github.io/fiscal-space/us/' },
  au: { title: 'Fiscal Space · Australia', description: 'Understanding the Australian Government fiscal position, outlook and risks. Official data, transparent calculations and forecast vintages.', short: 'Fiscal Space: a guide to the Australian public finances', url: 'https://patrickmschneider.github.io/fiscal-space/au/' },
};

const editionId = (mode: string) => (mode === 'au' || mode === 'us' ? mode : 'uk');

function edition(mode: string): Plugin {
  const e = editions[editionId(mode)];
  return { name: 'fiscal-space-edition', transformIndexHtml: html => html.replaceAll('%EDITION_TITLE%', e.title).replaceAll('%EDITION_DESCRIPTION%', e.description).replaceAll('%EDITION_SHORT%', e.short).replaceAll('%EDITION_URL%', e.url) };
}

export default defineConfig(({ mode }) => ({
  plugins: [react(), edition(mode)],
  base: './',
  publicDir: editionId(mode) === 'uk' ? 'public' : `public-${editionId(mode)}`,
  define: { 'import.meta.env.VITE_COUNTRY': JSON.stringify(editionId(mode)) },
}));
