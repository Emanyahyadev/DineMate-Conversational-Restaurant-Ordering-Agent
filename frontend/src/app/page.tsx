import AuthGate from "@/components/AuthGate";
import Chat from "@/components/Chat";
import SiteHeader from "@/components/SiteHeader";

export default function Home() {
  return (
    // A fixed app shell: the thread, cart and menu scroll inside, the page never
    // does. dvh (not vh) so the mobile address bar cannot crop the composer.
    <div className="flex h-[100dvh] flex-col overflow-hidden">
      {/* The header sits INSIDE the gate: signed out, the sign-in panel gets the
          whole viewport, and its logo is not competing with a second one 68px
          above it. */}
      <AuthGate>
        <SiteHeader />
        <Chat />
      </AuthGate>
    </div>
  );
}
