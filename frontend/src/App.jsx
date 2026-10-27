import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import Layout from "./components/Layout.jsx";
import { useAuth } from "./lib/auth.jsx";
import Admin from "./pages/Admin.jsx";
import AthleteView from "./pages/AthleteView.jsx";
import Athletes from "./pages/Athletes.jsx";
import AuthPage from "./pages/AuthPage.jsx";
import Connections from "./pages/Connections.jsx";
import PlanView from "./pages/PlanView.jsx";
import { ForgotPassword, ResetPassword } from "./pages/PasswordReset.jsx";
import Glossary from "./pages/Glossary.jsx";
import News, { PostEditor, PostView } from "./pages/News.jsx";
import Profile from "./pages/Profile.jsx";
import Races from "./pages/Races.jsx";
import Sharing from "./pages/Sharing.jsx";
import Workouts from "./pages/Workouts.jsx";

export default function App() {
  const { user } = useAuth();
  const location = useLocation();
  if (user === undefined) return <div className="center muted">Loading…</div>;
  // Reset links work whether or not someone is signed in on this browser.
  if (location.pathname === "/reset-password") return <ResetPassword />;
  if (user === null) {
    return (
      <Routes>
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/register" element={<AuthPage mode="register" />} />
        <Route path="*" element={<AuthPage mode="login" />} />
      </Routes>
    );
  }
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<AthleteView self />} />
        <Route path="connections" element={<Connections />} />
        <Route path="sharing" element={<Sharing />} />
        <Route path="athletes" element={<Athletes />} />
        <Route path="athletes/:athleteId" element={<AthleteView />} />
        <Route path="athletes/:athleteId/plans/:planId" element={<PlanView />} />
        <Route path="workouts" element={<Workouts />} />
        <Route path="races" element={<Races />} />
        <Route path="profile" element={<Profile />} />
        <Route path="glossary" element={<Glossary />} />
        <Route path="news" element={<News />} />
        <Route path="news/:postId" element={<PostView />} />
        {user.is_admin && <Route path="news/new" element={<PostEditor />} />}
        {user.is_admin && <Route path="news/:postId/edit" element={<PostEditor />} />}
        {user.is_admin && <Route path="admin" element={<Admin />} />}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
