/**
 * 404 page rendered inside the root layout (no own html/body wrapper).
 */

export default function NotFound() {
  return (
    <div
      style={{
        minHeight: '50vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: '1rem',
        padding: '4rem 2rem',
        textAlign: 'center',
      }}
    >
      <div style={{ fontSize: '4rem' }} aria-hidden>
        🔱
      </div>
      <h1 style={{ margin: 0, fontSize: '2.5rem' }}>
        404 — every head looked, no page found
      </h1>
      <p style={{ opacity: 0.7, maxWidth: '40rem' }}>
        The page you wanted has been redacted, never existed, or moved with a
        ProGuard pass. Try the <a href="/">home page</a> or the{' '}
        <a href="/reference">reference index</a>.
      </p>
    </div>
  );
}
