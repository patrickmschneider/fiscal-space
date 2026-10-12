import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';

// `--mode au` builds the Australian edition from the same code with its own saved data in public-au/.
const editions = {
  uk: { title: 'Fiscal Space', description: 'Understanding the UK fiscal position, outlook and risks. Official data, transparent calculations and forecast vintages.', short: 'Fiscal Space: a guide to the UK public finances', url: 'https://patrickmschneider.github.io/fiscal-space/' },
  au: { title: 'Fiscal Space · Australia', description: 'Understanding the Australian Government fiscal position, outlook and risks. Official data, transparent calculations and forecast vintages.', short: 'Fiscal Space: a guide to the Australian public finances', url: 'https://patrickmschneider.github.io/fiscal-space/au/' },
};

function edition(mode: string): Plugin {
  const e = editions[mode === 'au' ? 'au' : 'uk'];
  return { name: 'fiscal-space-edition', transformIndexHtml: html => html.replaceAll('%EDITION_TITLE%', e.title).replaceAll('%EDITION_DESCRIPTION%', e.description).replaceAll('%EDITION_SHORT%', e.short).replaceAll('%EDITION_URL%', e.url) };
}

export default defineConfig(({ mode }) => ({
  plugins: [react(), edition(mode)],
  base: './',
  publicDir: mode === 'au' ? 'public-au' : 'public',
  define: { 'import.meta.env.VITE_COUNTRY': JSON.stringify(mode === 'au' ? 'au' : 'uk') },
}));
