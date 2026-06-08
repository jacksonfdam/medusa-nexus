/**
 * MDX component overrides exposed to every page.
 *
 * Nextra 4 expects this file at the project root. We just re-export the
 * theme's default components so headings/links/callouts/code blocks
 * use the cyberpunk styling defined in styles/globals.css.
 */
import { useMDXComponents as getDocsMDXComponents } from 'nextra-theme-docs';

const themeComponents = getDocsMDXComponents();

export function useMDXComponents(components) {
  return { ...themeComponents, ...components };
}
