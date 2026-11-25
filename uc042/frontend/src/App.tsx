import { Link, Navigate, Route, Routes, useParams } from "react-router-dom";
import { CasePage } from "./pages/CasePages";
import { InvestigationPage } from "./pages/InvestigationPage";
import { Empty, Panel } from "./components/common";
import { AppShell } from "./components/layout/AppShell";
import { BatchPage } from "./pages/ArchivePages";
import { DashboardPage } from "./pages/DashboardPage";
import { FinalPackPage, FinalPacksPage } from "./pages/FinalPackPages";
import { PackDetailPage } from "./pages/PackDetailPage";
import { NewReportPage, ReportPage, ReportsPage } from "./pages/ReportPages";
import { OpenReviewPage, ReviewPage, ReviewsPage } from "./pages/ReviewPages";
import { UploadPage } from "./pages/UploadPage";
import { WorkspacePage } from "./pages/WorkspacePage";

// Every screen is addressable by URL: a refresh or a shared link reopens the same pack, exception, review or final pack.
export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<DashboardPage />} />
        <Route path="upload" element={<UploadPage />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="reports/new" element={<NewReportPage />} />
        <Route path="reports/:periodId" element={<ReportPage />} />
        <Route path="periods/:periodId" element={<PeriodRedirect />} />
        <Route path="uploads/:batchId" element={<BatchPage />} />
        <Route path="packs/:packId" element={<PackDetailPage />} />
        <Route path="packs/:packId/workspace" element={<WorkspacePage />} />
        <Route path="packs/:packId/workspace/:exceptionId" element={<WorkspacePage />} />
        <Route path="packs/:packId/exceptions/:exceptionId" element={<LegacyException />} />
        <Route path="packs/:packId/review" element={<OpenReviewPage />} />
        <Route path="reviews" element={<ReviewsPage />} />
        <Route path="reviews/:reviewId" element={<ReviewPage />} />
        <Route path="final-packs" element={<FinalPacksPage />} />
        <Route path="final-packs/:finalPackId" element={<FinalPackPage />} />
        <Route path="investigations/:investigationId" element={<InvestigationPage />} />
        <Route path="cases/:caseId" element={<CasePage />} />
        <Route path="*" element={<Panel><Empty title="Page not found"><Link to="/">Back to the dashboard</Link></Empty></Panel>} />
      </Route>
    </Routes>
  );
}

function LegacyException() {
  const { packId, exceptionId } = useParams();
  return <Navigate to={`/packs/${packId}/workspace/${exceptionId}`} replace />;
}

/** The Phase 4 period archive URL now opens the monthly report workspace of the same period. */
function PeriodRedirect() {
  const { periodId } = useParams();
  return <Navigate to={`/reports/${periodId}`} replace />;
}
