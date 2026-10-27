import { TopBar } from "../../kit/TopBar";

// M2 step 3 ("Your business and GST") is the next S1 PR; this page only proves the
// sign-up hand-off lands here.
export function BusinessPlaceholder() {
  return (
    <>
      <TopBar />
      <main className="page">
        <p className="step">Step 3 of 4</p>
        <h1>Your business and GST</h1>
        <p>Your account is ready. This step is coming next.</p>
      </main>
    </>
  );
}
