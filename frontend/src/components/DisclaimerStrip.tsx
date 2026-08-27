import { DISCLAIMER_LONG } from "../constants";
import { InfoIcon } from "./icons";

export default function DisclaimerStrip() {
  return (
    <div className="flex items-start gap-3 rounded-r border-l-4 border-warning-accent bg-warning-surface p-3 sm:p-4">
      <InfoIcon className="mt-0.5 h-5 w-5 shrink-0 text-warning-accent" />
      <p className="text-label-sm text-warning-text">{DISCLAIMER_LONG}</p>
    </div>
  );
}
