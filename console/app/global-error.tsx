"use client";

/**
 * Last-resort boundary: renders when the root layout itself throws (for
 * example a missing/weak SESSION_SECRET in production). It replaces the whole
 * document, so it must include <html> and <body> and can't rely on the app's CSS.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: "system-ui, sans-serif",
          background: "#0b0d10",
          color: "#e6e8eb",
        }}
      >
        <main style={{ maxWidth: 440, padding: 24, textAlign: "center" }} role="alert">
          <h1 style={{ fontSize: 20, margin: "0 0 8px" }}>The console failed to start</h1>
          <p style={{ fontSize: 14, lineHeight: 1.6, color: "#9aa3ad", margin: 0 }}>
            Check the console server logs and its environment (ENGINE_BASE_URL, OPERATOR_PASSWORD, SESSION_SECRET).
          </p>
          {error.digest ? (
            <p style={{ fontFamily: "monospace", fontSize: 11, color: "#6b7480" }}>reference: {error.digest}</p>
          ) : null}
          <button
            type="button"
            onClick={reset}
            style={{
              marginTop: 20,
              padding: "8px 16px",
              borderRadius: 8,
              border: "1px solid #2a2f36",
              background: "transparent",
              color: "inherit",
              cursor: "pointer",
            }}
          >
            Try again
          </button>
        </main>
      </body>
    </html>
  );
}
