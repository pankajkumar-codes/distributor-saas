import type { ReactNode } from "react";

/** "Step n of 4" above the page heading and the 4-segment bar below it. The bar is decoration; the text is the accessible name. */
export function StepProgress({ step, title, of = 4 }: { step: number; title: ReactNode; of?: number }) {
  return (
    <>
      <p className="step">
        Step {step} of {of}
      </p>
      <h1>{title}</h1>
      <div className="progress" aria-hidden="true">
        {Array.from({ length: of }, (_, i) => (
          <span key={i} className={i < step ? "on" : undefined} />
        ))}
      </div>
    </>
  );
}
