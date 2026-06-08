/**
 * Catch-all MDX route — Nextra 4 App Router pattern.
 *
 * Every URL under the site maps to a file under `content/`. The optional
 * `[[...mdxPath]]` slug lets `/` resolve to `content/index.mdx` and
 * `/getting-started/installation` to `content/getting-started/installation.mdx`.
 */

import { generateStaticParamsFor, importPage } from 'nextra/pages';
import { useMDXComponents as getMDXComponents } from '../../mdx-components';

export const generateStaticParams = generateStaticParamsFor('mdxPath');

export async function generateMetadata(props: {
  params: Promise<{ mdxPath: string[] }>;
}) {
  const params = await props.params;
  const { metadata } = await importPage(params.mdxPath);
  return metadata;
}

const Wrapper = getMDXComponents().wrapper;

export default async function Page(props: {
  params: Promise<{ mdxPath: string[] }>;
}) {
  const params = await props.params;
  const result = await importPage(params.mdxPath);
  const { default: MDXContent, toc, metadata } = result;
  return (
    <Wrapper toc={toc} metadata={metadata}>
      <MDXContent {...props} params={params} />
    </Wrapper>
  );
}
