import AuthGate from "@/components/AuthGate";
import Chat from "@/components/Chat";
import SiteHeader from "@/components/SiteHeader";

export default function Home() {
  return (
    // A fixed app shell: the thread, cart and menu scroll inside, the page never
    // does. dvh (not vh) so the mobile address bar cannot crop the composer.
    <div className="flex h-[100dvh] flex-col overflow-hidden">
      <SiteHeader />
      <AuthGate>
        <Chat />
      </AuthGate>
    </div>
  );
}
