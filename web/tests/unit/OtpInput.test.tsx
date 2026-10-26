import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { OtpInput } from "../../src/kit/OtpInput";

function Harness() {
  const [value, setValue] = useState("");
  return (
    <>
      <OtpInput value={value} onChange={setValue} />
      <output>{value}</output>
    </>
  );
}

const box = (n: number) => screen.getByLabelText(`Digit ${n} of 6`);

describe("OtpInput", () => {
  it("lets the browser fill the code from the email (autocomplete one-time-code)", () => {
    render(<Harness />);
    expect(box(1)).toHaveAttribute("autocomplete", "one-time-code");
    expect(box(1)).toHaveAttribute("inputmode", "numeric");
  });

  it("moves to the next box as digits are typed, and ignores letters", () => {
    render(<Harness />);
    fireEvent.change(box(1), { target: { value: "4" } });
    expect(box(2)).toHaveFocus();
    fireEvent.change(box(2), { target: { value: "x" } });
    fireEvent.change(box(2), { target: { value: "2" } });
    expect(document.querySelector("output")).toHaveTextContent("42");
  });

  it("fills every box from a paste", () => {
    render(<Harness />);
    fireEvent.paste(box(1), { clipboardData: { getData: () => "123 456" } });
    expect(document.querySelector("output")).toHaveTextContent("123456");
    expect(box(6)).toHaveValue("6");
  });

  it("goes back a box on Backspace", () => {
    render(<Harness />);
    fireEvent.paste(box(1), { clipboardData: { getData: () => "123" } });
    fireEvent.keyDown(box(4), { key: "Backspace" });
    expect(document.querySelector("output")).toHaveTextContent(/^12$/);
    expect(box(3)).toHaveFocus();
  });
});
