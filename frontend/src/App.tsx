import { Navigate, Route, Routes } from "react-router";

import { AppShell } from "./components/AppShell";
import { StudyLayout } from "./components/StudyLayout";
import { LoginPage } from "./pages/LoginPage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { SettingsPage } from "./pages/SettingsPage";
import { ContextPage } from "./pages/study/ContextPage";
import { DesignPage } from "./pages/study/DesignPage";
import { HypothesesPage } from "./pages/study/HypothesesPage";
import { InsightsPage } from "./pages/study/InsightsPage";
import { InterviewsPage } from "./pages/study/InterviewsPage";
import { ReportPage } from "./pages/study/ReportPage";
import { RespondentsPage } from "./pages/study/RespondentsPage";
import { ScenarioPage } from "./pages/study/ScenarioPage";
import { StenogramPage } from "./pages/study/StenogramPage";
import { ValidationPage } from "./pages/study/ValidationPage";
import { SystemPage } from "./pages/SystemPage";

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/login/forgot" element={<LoginPage view="forgot" />} />
      <Route path="/login/forgot/sent" element={<LoginPage view="sent" />} />
      <Route path="/login/reset" element={<LoginPage view="reset" />} />
      <Route element={<AppShell />}>
        <Route index element={<Navigate to="/projects" replace />} />
        <Route path="projects" element={<ProjectsPage />} />
        <Route path="projects/:projectId" element={<StudyLayout />}>
          <Route index element={<Navigate to="context" replace />} />
          <Route path="context" element={<ContextPage />} />
          <Route path="hypotheses" element={<HypothesesPage />} />
          <Route path="scenario" element={<ScenarioPage />} />
          <Route path="respondents" element={<RespondentsPage />} />
          <Route path="design" element={<DesignPage />} />
          <Route path="interviews" element={<InterviewsPage />} />
          <Route path="stenogram" element={<StenogramPage />} />
          <Route path="insights" element={<InsightsPage />} />
          <Route path="validation" element={<ValidationPage />} />
          <Route path="report" element={<ReportPage />} />
        </Route>
        <Route path="settings" element={<Navigate to="/settings/profile" replace />} />
        <Route path="settings/:tab" element={<SettingsPage />} />
        <Route path="system" element={<SystemPage />} />
        <Route path="*" element={<Navigate to="/projects" replace />} />
      </Route>
    </Routes>
  );
}
