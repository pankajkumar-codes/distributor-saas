import { Link } from "react-router-dom";

/** "Settings / Your team" over a settings page's heading (mocks v16). Settings links back to Business setup. */
export function SettingsEyebrow({ businessId, here }: { businessId: string; here?: string }) {
  return (
    <p className="eyebrow">
      {here ? <Link to={`/b/${businessId}/settings`}>Settings</Link> : "Settings"} / {here ?? "Business setup"}
    </p>
  );
}
