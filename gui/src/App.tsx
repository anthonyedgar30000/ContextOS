import { useCallback, useEffect, useState } from "react";
import { DetailsPanel } from "./components/DetailsPanel";
import { Sidebar } from "./components/Sidebar";
import { WorkspacePanel } from "./components/Panels";
import mockContext from "./data/mockContext.json";
import {
  fetchClassifierReport,
  mergeClassifierReport,
} from "./services/classifier";
import type { ContextOSDesktopData, NavigationSection } from "./types/contextos";

const fallbackData = mockContext as ContextOSDesktopData;

function App() {
  const [activeSection, setActiveSection] =
    useState<NavigationSection>("overview");
  const [data, setData] = useState<ContextOSDesktopData>(fallbackData);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dataSource, setDataSource] = useState<"mock" | "live">("mock");

  const refreshClassifierData = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const report = await fetchClassifierReport();
      setData(mergeClassifierReport(fallbackData, report));
      setDataSource("live");
    } catch (caughtError) {
      setData(fallbackData);
      setDataSource("mock");
      setError(
        caughtError instanceof Error
          ? caughtError.message
          : "Unable to load live ContextOS classification data.",
      );
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshClassifierData();
  }, [refreshClassifierData]);

  return (
    <main className="desktop-shell">
      <Sidebar
        activeSection={activeSection}
        onSectionChange={setActiveSection}
      />
      <section className="workspace" aria-live="polite">
        <div className="integration-toolbar">
          <div>
            <span className={`source-dot source-dot--${dataSource}`} />
            <strong>
              {dataSource === "live"
                ? "Live classifier data"
                : "Mock fallback data"}
            </strong>
            {isLoading ? <small>Refreshing ContextOS classification...</small> : null}
            {error ? <small className="integration-error">{error}</small> : null}
          </div>
          <button
            disabled={isLoading}
            onClick={() => void refreshClassifierData()}
            type="button"
          >
            {isLoading ? "Refreshing..." : "Refresh classification"}
          </button>
        </div>
        <WorkspacePanel activeSection={activeSection} data={data} />
      </section>
      <DetailsPanel data={data} />
    </main>
  );
}

export default App;
