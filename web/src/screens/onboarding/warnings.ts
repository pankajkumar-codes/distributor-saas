import { gstinMessage } from "../../format/gstin";

// The words for the warning codes POST /b and POST /filing-profile/frequency return. They
// name no amount or date: those belong in refdata, and the window rows aren't loaded yet.
// Pending the GST expert's and the PO's read of the copy.
const WORDS: Record<string, string> = {
  pan_shape: gstinMessage("pan_shape"),
  gstin_not_z: gstinMessage("gstin_not_z"),
  address_state_mismatch:
    "Your address is in a different state from your GSTIN. A GSTIN belongs to one state, so please check both.",
  window_unknown:
    "We can't show the dates for changing your filing frequency yet. If you're not sure your choice applies this quarter, ask your CA.",
  outside_window:
    "Your filing frequency choice may fall outside the period when it can be changed on the GST portal. Please check with your CA.",
  last_return_unfiled:
    "A return that was due may not be filed yet, which can stop a change of filing frequency. Please check with your CA.",
  aato_above_threshold:
    "Your declared turnover is above the limit for quarterly filing (QRMP). Please check with your CA before filing quarterly.",
};

export function warningText(code: string): string {
  return WORDS[code] ?? "Please check your business details.";
}
