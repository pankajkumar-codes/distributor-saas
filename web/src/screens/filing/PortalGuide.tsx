/**
 * How to put the GSTR-1 file on the GST portal (R1-M10). The steps follow GSTN's own "FAQs and User Manual: Returns
 * Offline Tool" (sections 9 and F, no version or date printed on the document). Nobody here has opened the live portal
 * for this, so the page says that, and each step the manual does not cover or that may read differently today is
 * marked. The list of those steps goes to the team so the person testing on the portal can confirm each one.
 */
type Step = { text: string; check?: string };

export const GUIDE_STEPS = (periodLabel: string): Step[] => [
  {
    text: "Download the file from File and lock on your GSTR-1 and keep it somewhere you can find it. If we made more than one part, upload each part in turn.",
  },
  {
    text: "The portal does not take a file of 5 MB or more. If ours would be that large, we stop and tell you instead of making it.",
    check: "The 5 MB comes from the manual. Our own limit for it is provisional and not yet confirmed on the portal.",
  },
  { text: "Open gst.gov.in and sign in with your own GST login. We never ask for it." },
  { text: "Go to Services, then Returns, then Returns Dashboard." },
  {
    text: `Choose the financial year and the period "${periodLabel}", then press Search. If you file quarterly, choose the quarter and then the month shown in "${periodLabel}".`,
    check: "The manual shows the year, quarter and period lists. The current portal's wording and the quarterly extra screen have not been looked at.",
  },
  { text: "On the GSTR-1 (Outward supplies made by the taxpayer) tile, press Prepare offline." },
  { text: "On the upload page, press Choose file, pick the file you downloaded and press Open." },
  {
    text: "The portal gives a reference number and shows the status as In progress. Wait a few minutes. Your invoices then appear in the tiles for each table, with a count on each.",
    check: "The manual says the wait is \"a few minutes\". How long it takes today is not known.",
  },
  {
    text: 'If the status says "Processed with error", use the portal\'s Generate error report link, wait about 15 minutes and download the report. Fix what it names in your invoices here and make the file again.',
    check: "The 15 minutes comes from the manual. Whether the link still reads \"Generate error report\" is not confirmed.",
  },
  {
    text: "Press Generate GSTR-1 summary if a tile does not show your invoices. Compare the counts and totals on the portal with the totals on this page.",
    check: "Where the summary button sits on the current portal is not confirmed.",
  },
  {
    text: "When the numbers agree, sign and file the return on the portal with your DSC or EVC. Uploading the file does not file the return. Only you can file it.",
    check: "The manual says the return is signed with DSC or EVC. Which of the two your business can use is on your portal account, not here.",
  },
  { text: "Come back to this page and mark the return as filed." },
];

/** The guide's tabs, so each fits one laptop screen: key, name, first step (from 0) and the step after the last. */
export const GUIDE_PARTS: [string, string, number, number][] = [
  ["ready", "Get ready", 0, 4],
  ["upload", "Upload", 4, 8],
  ["file", "Check and file", 8, 99],
];
