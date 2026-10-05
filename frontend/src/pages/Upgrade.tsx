import Subscription from "@/pages/Subscription";

// Shown when the free trial has ended and no plan is active: the same plans page, so people can pay straight away.
export default function Upgrade({ email, onSignOut }: { email: string | null; onSignOut: () => void; onApproved?: () => void }) {
  return <Subscription expired email={email} onSignOut={onSignOut} />;
}
