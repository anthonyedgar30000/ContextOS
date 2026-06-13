import { useState } from "react";
import { DetailsPanel } from "./components/DetailsPanel";
import { Sidebar } from "./components/Sidebar";
import { WorkspacePanel } from "./components/Panels";
import mockContext from "./data/mockContext.json";
import type { ContextOSDesktopData, NavigationSection } from "./types/contextos";

const data = mockContext as ContextOSDesktopData;

function App() {
  const [activeSection, setActiveSection] =
    useState<NavigationSection>("overview");

  return (
    <main className="desktop-shell">
      <Sidebar
        activeSection={activeSection}
        onSectionChange={setActiveSection}
      />
      <section className="workspace" aria-live="polite">
        <WorkspacePanel activeSection={activeSection} data={data} />
      </section>
      <DetailsPanel data={data} />
    </main>
  );
}

export default App;
