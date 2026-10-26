import { BookOpen, Dumbbell, Flag, LayoutDashboard, Link2, LogOut, Menu, Settings, Share2, Shield, Users } from "lucide-react";
import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../lib/auth.jsx";
import Logo from "./Logo.jsx";

const NAV = [
  { to: "/", label: "My training", icon: LayoutDashboard, end: true },
  { to: "/workouts", label: "Workouts", icon: Dumbbell },
  { to: "/races", label: "Races", icon: Flag },
  { to: "/connections", label: "Connections", icon: Link2 },
  { to: "/sharing", label: "Sharing", icon: Share2 },
  { to: "/athletes", label: "My athletes", icon: Users },
  { to: "/profile", label: "Profile", icon: Settings },
  { to: "/glossary", label: "Glossary", icon: BookOpen },
];

export default function Layout() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const nav = user.is_admin ? [...NAV, { to: "/admin", label: "Admin", icon: Shield }] : NAV;

  return (
    <div className="shell">
      <header className="topbar">
        <button className="icon-btn" aria-label="Menu" onClick={() => setOpen(!open)}>
          <Menu size={20} />
        </button>
        <NavLink to="/" className="brand" aria-label="CoachQuest home">
          <Logo variant="word" />
        </NavLink>
      </header>
      <aside className={`sidebar ${open ? "open" : ""}`}>
        <NavLink to="/" end className="brand sidebar-brand" aria-label="CoachQuest home" onClick={() => setOpen(false)}>
          <Logo />
        </NavLink>
        <nav>
          {nav.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} onClick={() => setOpen(false)}>
              <Icon size={18} /> {label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="muted small">{user.display_name}</div>
          <button className="link-btn" onClick={logout}>
            <LogOut size={16} /> Sign out
          </button>
        </div>
      </aside>
      {open && <div className="scrim" onClick={() => setOpen(false)} />}
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}
